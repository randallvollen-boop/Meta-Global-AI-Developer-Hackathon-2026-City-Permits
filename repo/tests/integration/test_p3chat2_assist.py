"""The Muse path of the applicant help panel, through the portal.

The panel shows a replay fixture with its source label, usage and latency, a
declined question with its reason, and the deterministic rule text when the
validation refuses a recorded output.  Staff never read a chat run.  No test
here reaches a provider.
"""
# REQUIRES: PORTAL-02, AI-01, AI-04, PER-04, SEC-03

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import model_run
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

FENCE = "Do I need a permit for a 6 ft fence?"
DECLINE = "Will my fence permit be approved?"
FALLBACK_DEMO = "Show me the ACME rule text for a fence"
FALLBACK_LABEL = "Matching ACME rule text (not an AI answer)"


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'assist-portal.db'}",
            "ACME_SECRET_KEY": "assist-portal-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment, monkeypatch) -> TestClient:
    import acme_city.applicant_help.assist as assist

    def refuse(*args, **kwargs):  # pragma: no cover - the call must not happen
        raise AssertionError("a replay or a fallback must not reach the provider")

    monkeypatch.setattr(assist, "MuseClient", refuse)
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200


def token(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def ask(client: TestClient, question: str, path: str = "/apply", **extra) -> str:
    response = client.post(
        "/apply/help",
        data={
            "csrf_token": token(client, path),
            "question": question,
            "conversation_version": "0",
            "conversation_id": "",
            "placement": extra.pop("placement", "chooser"),
            **extra,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    match = re.search(r"(?:help|conversation)=([^&]+)", response.headers["location"])
    assert match
    return client.get("/apply", params={"help": match.group(1)}).text


def test_the_fence_answer_quotes_the_rule_and_shows_its_source(client) -> None:
    choose(client, "persona_applicant")
    page = ask(client, FENCE)
    assert 'data-testid="muse-source"' in page
    assert 'data-mode="replay"' in page
    assert "Recorded replay" in page
    assert " in · " in page and " out" in page  # usage is shown
    assert "ACME Code §14-305" in page
    assert page.count('data-testid="help-quote"') >= 2
    assert "Threshold: 4." in page
    # The next step comes from the server, not from the recorded output.
    assert 'data-testid="help-next-steps"' in page or 'data-testid="help-ask-the-city"' in page
    assert "will be approved" not in page.lower()


def test_the_declined_question_shows_the_reason_and_the_way_to_a_person(client) -> None:
    choose(client, "persona_applicant")
    page = ask(client, DECLINE)
    assert 'data-testid="help-declined"' in page
    assert 'data-reason="needs_a_person"' in page
    assert "The assistant did not answer." in page
    assert 'data-testid="help-ask-the-city"' in page
    assert "Matching ACME rule text (not an AI answer)" in page or 'data-testid="help-no-match"' in page


def test_the_failing_fixture_shows_the_deterministic_rule_text(client) -> None:
    choose(client, "persona_applicant")
    page = ask(client, FALLBACK_DEMO)
    assert FALLBACK_LABEL in page
    assert 'data-testid="muse-source"' not in page
    assert 'data-outcome="rejected"' in page
    assert "Fence height in the front yard is 4 feet." not in page  # the bad quote never shows


def test_the_demo_questions_are_offered_as_chips_in_demo_mode(client) -> None:
    choose(client, "persona_applicant")
    page = client.get("/apply").text
    assert DECLINE in page
    assert "Show me the ACME rule text for a fence" in page


def test_the_form_placement_replays_with_the_type_in_context(client) -> None:
    choose(client, "persona_applicant")
    page = ask(client, FENCE, path="/apply/deck_fence", placement="form", type_key="deck_fence")
    assert 'data-mode="replay"' in page or "Recorded replay" in page


def test_staff_cannot_read_a_chat_run(client, environment) -> None:
    choose(client, "persona_applicant")
    ask(client, FENCE)
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            run_id = session.execute(select(model_run.ModelRun.id)).scalars().first()
    finally:
        factory.dispose()
    assert run_id
    for persona in ("persona_data_steward", "persona_permit_reviewer", "persona_city_administrator"):
        choose(client, persona)
        listed = client.get("/api/muse/runs")
        if listed.status_code == 200:
            assert all(r.get("task") != "applicant_assist" for r in listed.json()["runs"])
            assert run_id not in listed.text
        detail = client.get(f"/detail/muse-run/{run_id}")
        assert detail.status_code in (403, 404)


def test_every_suggested_chip_hits_a_fixture_or_the_plain_fallback(client, environment) -> None:
    """The demo chips are the questions of the fixtures, word for word."""
    from acme_city.applicant_help.config import load_config

    chips = [text for _, text in load_config().questions(demo_mode=True)]
    assert DECLINE in chips and FALLBACK_DEMO in chips and FENCE in chips
    from acme_city.applicant_help.assist import load_replay_fixtures, normalize_question

    keys = {f["question_key"] for f in load_replay_fixtures().values()}
    for text in (FENCE, DECLINE, FALLBACK_DEMO):
        assert normalize_question(text) in keys

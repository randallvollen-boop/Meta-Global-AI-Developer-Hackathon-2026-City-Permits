"""The batch the Data Steward accepts in one press.

The batch opens a preview of exactly the recommendations it would accept, and
the steward confirms that list.  Every item goes through the same path as a
single acceptance, so the stale guard and the held guard apply to it as
well.  An item that changed since the preview is skipped and named, never
accepted silently.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, PER-04, SEC-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import audit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-batch-ui.db'}",
            "ACME_SECRET_KEY": "steward-batch-ui-secret-value",
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
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, next_path), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def post_many(
    client: TestClient,
    action: str,
    names: list[str],
    next_path: str,
    digest: str = "",
):
    """Post one field several times, the way the preview form does."""
    return client.post(
        f"/ui/actions/{action}",
        data={
            "csrf_token": csrf(client, next_path),
            "next": next_path,
            "preview_item": list(names),
            "preview_digest": digest,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def wake_the_assistant(client: TestClient) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    choose(client, "persona_agent_operator")
    response = client.post(
        "/ui/actions/agent.toggle",
        data={
            "csrf_token": csrf(client, "/agent/steward_assist"),
            "next": "/agent/steward_assist",
            "agent_key": "steward_assist",
            "mode": "awake",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    choose(client, "persona_data_steward")


def prepare(client: TestClient) -> None:
    """Ask the assistant to prepare the work of the queue."""
    wake_the_assistant(client)
    response = post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
    assert response.status_code == 200, response.text


def stored_recommendations(environment: Settings) -> list[StewardRecommendation]:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(StewardRecommendation).order_by(
                        StewardRecommendation.made_at, StewardRecommendation.id
                    )
                ).scalars().all()
            )
    finally:
        factory.dispose()


def certain_recommendations(environment: Settings) -> list[StewardRecommendation]:
    """Return the recommendations the batch may accept."""
    return [row for row in stored_recommendations(environment) if row.confidence == "high"]


def batch_button(client: TestClient) -> str:
    """Return the markup of the batch button of the queue."""
    body = client.get("/steward").text
    button = re.search(
        r'<(?:button|a)[^>]*data-testid="assistant-batch-preview"[^>]*>', body
    )
    assert button is not None, body[:400]
    return button.group(0)


def preview_ids(client: TestClient) -> list[str]:
    """Return the identifiers the preview form confirms."""
    body = client.get("/steward/batch").text
    return [
        value.split(":", 1)[0]
        for value in re.findall(r'name="preview_item" value="([^"]+)"', body)
    ]


def preview_items(client: TestClient) -> list[str]:
    """Return the values the preview form confirms, with their versions."""
    body = client.get("/steward/batch").text
    return re.findall(r'name="preview_item" value="([^"]+)"', body)


def preview_digest(client: TestClient) -> str:
    """Return the proof of the list the preview shows."""
    body = client.get("/steward/batch").text
    match = re.search(r'name="preview_digest" value="([^"]+)"', body)
    assert match is not None, body[:400]
    return match.group(1)


def preview_form(client: TestClient) -> tuple[list[str], str]:
    """Return the list the preview confirms and the proof of that list."""
    return preview_items(client), preview_digest(client)


def preview_labels(client: TestClient) -> list[str]:
    """Return the names the preview shows."""
    body = client.get("/steward/batch").text
    return re.findall(r'data-testid="batch-item"[^>]*>\s*<strong>([^<]+)</strong>', body)


# ------------------------------------------------------------------ the queue


def test_the_batch_button_is_off_and_says_why_when_nothing_is_sure(
    client: TestClient, environment: Settings
) -> None:
    """An empty batch is a disabled button and a note that says why."""
    wake_the_assistant(client)
    choose(client, "persona_data_steward")
    button = batch_button(client)
    assert "disabled" in button
    assert "Accept all high-confidence (0)" in client.get("/steward").text
    body = client.get("/steward").text
    assert 'data-testid="assistant-batch-note"' in body
    assert "sure enough" in body


def test_the_queue_shows_how_many_recommendations_the_batch_holds(
    client: TestClient, environment: Settings
) -> None:
    """The button names the number of the recommendations the batch holds."""
    prepare(client)
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    expected = len(certain_recommendations(environment))
    assert expected == 3
    assert f"Accept all high-confidence ({expected})" in body
    assert "disabled" not in batch_button(client)


def test_the_batch_button_is_only_offered_to_the_steward(
    client: TestClient, environment: Settings
) -> None:
    """A persona without the grant of the steward does not see the queue."""
    prepare(client)
    choose(client, "persona_permit_reviewer")
    assert client.get("/steward").status_code == 403


# ----------------------------------------------------------------- the preview


def test_the_preview_names_exactly_the_items_the_batch_accepts(
    client: TestClient, environment: Settings
) -> None:
    """The preview lists the recommendations and confirms exactly those."""
    prepare(client)
    choose(client, "persona_data_steward")
    body = client.get("/steward/batch").text
    ids = preview_ids(client)
    assert ids == [row.id for row in certain_recommendations(environment)]
    assert len(ids) == 3
    # Every item is named in the words of the queue.
    labels = preview_labels(client)
    assert len(labels) == 3
    assert any("PER-AP-0003" in label for label in labels)
    assert 'data-testid="assistant-batch-confirm"' in body


def test_a_persona_outside_the_grants_may_not_open_the_preview(
    client: TestClient, environment: Settings
) -> None:
    """The preview is a screen of the Data Steward alone."""
    prepare(client)
    choose(client, "persona_permit_reviewer")
    assert client.get("/steward/batch").status_code == 403


# ---------------------------------------------------------------- the confirmation


def test_confirming_the_preview_accepts_every_item_and_records_it(
    client: TestClient, environment: Settings
) -> None:
    """Each item is a decision of the steward, with the recommendation named."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    ids = [item.split(":", 1)[0] for item in items]
    response = post_many(
        client, "steward.assist.batch_accept", items, "/steward/batch", digest
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "accepted"
    assert "Accepted 3 of 3" in payload["message"]

    # The links of the three source records are approved by the steward.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.link_status == "approved"
                )
            ).scalars().all()
            assert len(links) == 3
            assert all(link.decision_actor_id == "persona_data_steward" for link in links)

            # Every item is a separate decision that names its recommendation.
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "steward.recommendation.accept"
                )
            ).scalars().all()
            assert len(events) == 3
            assert {tuple(event.references or [])[0] for event in events} == set(ids)
            assert all(event.actor_id == "persona_data_steward" for event in events)

            # The accepted recommendations are cleared, so no task holds an
            # answer twice.  The recommendation the batch did not offer is
            # untouched.
            rows = session.execute(select(StewardRecommendation)).scalars().all()
            assert {row.id for row in rows if row.cleared} == set(ids)
            assert len(rows) == 4
    finally:
        factory.dispose()


def test_an_item_that_changed_since_the_preview_is_skipped_and_named(
    client: TestClient, environment: Settings
) -> None:
    """A record that changed is not accepted silently; it is named."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    ids = [item.split(":", 1)[0] for item in items]
    # The link of one recommendation changes after the preview.
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, ids[0])
            assert row is not None
            crosswalk_id = str((row.evidence or {}).get("crosswalk_id") or "")
            assert crosswalk_id
            crosswalk = session.get(registry.Crosswalk, crosswalk_id)
            assert crosswalk is not None
            crosswalk.version += 1
    finally:
        factory.dispose()

    response = post_many(
        client, "steward.assist.batch_accept", items, "/steward/batch", digest
    )
    assert response.status_code == 200, response.text
    message = response.json()["message"]
    assert "Accepted 2 of 3" in message
    assert "Skipped" in message
    assert "changed" in message

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.link_status == "approved"
                )
            ).scalars().all()
            assert len(links) == 2
            # The item that changed was not accepted.
            stale = session.get(StewardRecommendation, ids[0])
            assert stale is not None
            assert stale.cleared is False
    finally:
        factory.dispose()


def test_an_item_whose_confidence_changed_is_skipped_and_named(
    client: TestClient, environment: Settings
) -> None:
    """A recommendation that is no longer sure is skipped and named."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    ids = [item.split(":", 1)[0] for item in items]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, ids[0])
            assert row is not None
            row.confidence = "review"
    finally:
        factory.dispose()

    response = post_many(
        client, "steward.assist.batch_accept", items, "/steward/batch", digest
    )
    assert response.status_code == 200, response.text
    message = response.json()["message"]
    assert "Accepted 2 of 3" in message
    assert "confidence" in message

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            changed = session.get(StewardRecommendation, ids[0])
            assert changed is not None
            assert changed.cleared is False
    finally:
        factory.dispose()


def test_the_batch_accepts_nothing_when_no_recommendation_is_confirmed(
    client: TestClient, environment: Settings
) -> None:
    """A confirmation without an item is refused."""
    prepare(client)
    choose(client, "persona_data_steward")
    response = post(client, "steward.assist.batch_accept", {"next": "/steward/batch"}, "/steward/batch")
    assert response.status_code == 422, response.text
    assert response.json()["status"] == "denied"


def test_a_confirmation_of_a_shorter_list_is_refused(
    client: TestClient, environment: Settings
) -> None:
    """A confirmation that leaves an item of the preview out is refused."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    assert len(items) == 3
    response = post_many(
        client, "steward.assist.batch_accept", items[:1], "/steward/batch", digest
    )
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["status"] == "denied"
    assert "not the list you were shown" in payload["message"]

    # Nothing was accepted.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            links = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.link_status == "approved"
                )
            ).scalars().all()
            assert links == []
            rows = session.execute(select(StewardRecommendation)).scalars().all()
            assert all(row.cleared is False for row in rows)
    finally:
        factory.dispose()


def test_a_confirmation_of_another_recommendation_is_refused(
    client: TestClient, environment: Settings
) -> None:
    """A confirmation that names a record the preview did not show is refused."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    other = [row.id for row in stored_recommendations(environment) if row.confidence != "high"]
    assert other
    response = post_many(
        client,
        "steward.assist.batch_accept",
        [*items, f"{other[0]}:1"],
        "/steward/batch",
        digest,
    )
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["status"] == "denied"
    assert "not the list you were shown" in payload["message"]


def test_the_assistant_may_not_accept_a_batch_for_the_steward(
    client: TestClient, environment: Settings
) -> None:
    """The run grant of the assistant belongs to the Data Steward alone."""
    prepare(client)
    choose(client, "persona_data_steward")
    items, digest = preview_form(client)
    choose(client, "persona_city_administrator")
    response = post_many(
        client, "steward.assist.batch_accept", items, "/steward", digest
    )
    assert response.status_code == 403, response.text
    assert response.json()["status"] == "denied"

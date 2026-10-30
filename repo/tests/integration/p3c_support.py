"""Shared helpers for the P3c and chat 3 integration tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from acme_city.core.config import Settings
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import help as help_models
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

ADMIN = "persona_city_administrator"
APPLICANT = "persona_applicant"
STEWARD = "persona_data_steward"
REVIEWER = "persona_permit_reviewer"
OPERATOR = "persona_agent_operator"


def build_settings(directory: Path, name: str = "p3c.db") -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / name}",
            "ACME_SECRET_KEY": "p3c-test-secret-value",
        },
        key_file=directory / "missing.env",
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


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def _any_token(client: TestClient, page: str) -> str:
    """Return the CSRF token from the first screen the persona may open."""
    for candidate in (
        page,
        "/ops/checks",
        "/queue/intake",
        "/steward",
        "/permits/app_synth_001",
        "/agent/intake",
        "/agent/adjudication",
        "/apply/deck_fence",
        "/apply",
    ):
        match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(candidate).text)
        if match:
            return match.group(1)
    raise AssertionError(f"no CSRF token for {page}")


def post_action(client: TestClient, action_id: str, fields: dict, *, csrf: str | None = None, page: str = "/ops/checks"):
    """Post one dispatcher action and return the response."""
    if csrf is None:
        csrf = _any_token(client, page)
    data = {
        "csrf_token": csrf,
        "next": page,
        **fields,
    }
    return client.post(
        f"/ui/actions/{action_id}",
        data=data,
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def seed_help_request(
    settings: Settings,
    *,
    application_id: str | None = None,
    question: str = "Who decides my fictional permit?",
    earlier: tuple[str, ...] = (),
    later: tuple[str, ...] = (),
    owner: str = APPLICANT,
) -> dict:
    """Insert a conversation with turns, one help request and optional later turns."""
    factory = SessionFactory(settings.database_url)
    base = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    try:
        with transaction(factory) as session:
            conversation = help_models.HelpConversation(
                id=new_id("helpconv"),
                correlation_id=new_id("corr"),
                created_at=base,
                owner_actor_id=owner,
                owner_session_hash="",
                application_id=application_id,
                placement="track" if application_id else "chooser",
                turn_count=len(earlier) + len(later),
                version=1,
            )
            session.add(conversation)
            session.flush()
            number = 0
            for text in earlier:
                number += 1
                session.add(_turn(conversation.id, text, number, base + timedelta(minutes=number)))
            request = help_models.HelpRequest(
                id=new_id("helpreq"),
                correlation_id=conversation.correlation_id,
                created_at=base + timedelta(minutes=20),
                conversation_id=conversation.id,
                applicant_actor_id=owner,
                application_id=application_id,
                question=question,
                status="open",
                version=1,
            )
            session.add(request)
            for text in later:
                number += 1
                session.add(_turn(conversation.id, text, number, base + timedelta(minutes=30 + number)))
            session.flush()
            return {"request_id": request.id, "conversation_id": conversation.id, "version": request.version}
    finally:
        factory.dispose()


def _turn(conversation_id: str, text: str, number: int, when: datetime) -> help_models.HelpTurn:
    return help_models.HelpTurn(
        id=new_id("helpturn"),
        created_at=when,
        conversation_id=conversation_id,
        question=text,
        outcome="no_match",
        answer={"label": "No published text matched", "paragraphs": [], "cannot_answer": True},
        sources=[],
        mode="fallback",
        turn_number=number,
    )

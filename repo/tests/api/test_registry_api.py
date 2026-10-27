"""Registry API tests: authorization, decisions, conflicts and the trusted view."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.registry.router import router as registry_router


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'registry-api.db'}",
            "ACME_SECRET_KEY": "registry-api-secret-value",
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
    return settings, bundle


@pytest.fixture()
def client(environment: tuple[Settings, FixtureBundle]) -> TestClient:
    settings, _ = environment
    app = create_app(settings)
    app.include_router(registry_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def propose(client: TestClient, record_id: str = "PER-AP-0003") -> dict:
    """Propose the links of one source record."""
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": record_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def decide(client: TestClient, payload: dict) -> dict:
    """Record a steward decision."""
    response = client.post("/api/registry/decisions", json=payload)
    assert response.status_code in {200, 409}, response.text
    return response.json()


def test_the_registry_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/registry/crosswalks").status_code == 401
    assert client.get("/api/registry/entities/party_cedarline/trusted-view").status_code == 401
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert response.status_code == 401


def test_an_applicant_may_not_propose_or_decide(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            before = session.execute(
                select(registry.Crosswalk)
            ).scalars().all()
        select_persona(client, "persona_applicant")
        proposed = client.post(
            "/api/registry/proposals",
            json={
                "source_system_id": "permitting",
                "dataset_key": "applicant_profiles",
                "source_record_id": "PER-AP-0003",
            },
        )
        assert proposed.status_code == 403
        assert proposed.json()["code"] == "permission_denied"
        decided = client.post(
            "/api/registry/decisions",
            json={
                "source_system_id": "permitting",
                "source_record_id": "PER-AP-0003",
                "decision": "approve",
                "reason": "an applicant may not decide a link",
            },
        )
        assert decided.status_code == 403
        with factory() as session:
            after = session.execute(select(registry.Crosswalk)).scalars().all()
        assert len(after) == len(before)
    finally:
        factory.dispose()


def test_a_proposal_carries_its_evidence_and_an_uncalibrated_score(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    payload = propose(client)
    assert payload["disposition"] == "supported"
    assert payload["candidate_ids"] == ["party_cedarline"]
    assert payload["score_is_calibrated"] is False
    assert payload["score_label"] == "uncalibrated_heuristic"
    assert payload["supporting_evidence"]
    assert all(item["direction"] == "supporting" for item in payload["supporting_evidence"])


def test_a_steward_decision_records_the_actor_the_time_the_reason_and_the_evidence(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    propose(client)
    select_persona(client, "persona_city_administrator")
    payload = decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the recorded alias and the declared reference name the same party",
            "evidence": [
                {
                    "field": "party_ref",
                    "value": "party_cedarline",
                    "note": "the declared reference names the canonical party",
                }
            ],
        },
    )
    assert payload["value"]["link_status"] == "approved"
    assert payload["value"]["decision_actor_id"] == "persona_city_administrator"
    assert payload["value"]["decided_at"]
    assert "recorded alias" in payload["value"]["decision"]

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            proposals = session.execute(
                select(registry.MatchProposal).where(
                    registry.MatchProposal.method == "steward_decision"
                )
            ).scalars().all()
            assert len(proposals) == 1
            assert proposals[0].disposition == "approve"
            assert proposals[0].created_by_actor_id == "persona_city_administrator"
            assert proposals[0].supporting_evidence
            assert proposals[0].supporting_evidence[0]["field"] == "party_ref"
    finally:
        factory.dispose()


def test_a_stale_expected_version_returns_a_conflict(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    propose(client)
    payload = decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "a stale read of the link",
            "expected_version": 99,
        },
    )
    assert payload["code"] == "version_conflict"
    assert payload["current_version"] == 1
    assert payload["expected_version"] == 99
    assert payload["differences"]


def test_only_one_approved_link_survives_a_source_record(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    propose(client)
    first = decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the first approval",
        },
    )
    assert first["value"]["link_status"] == "approved"

    propose(client)
    second = decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "a second approval of the same source record",
        },
    )
    assert second["value"]["link_status"] == "approved"

    history = client.get(
        "/api/registry/crosswalks/history",
        params={"source_system_id": "permitting", "source_record_id": "PER-AP-0003"},
    )
    assert history.status_code == 200
    statuses = [row["link_status"] for row in history.json()["crosswalks"]]
    assert statuses.count("approved") == 1
    assert len(statuses) == 1


def test_a_correction_supersedes_the_earlier_decision_without_destroying_it(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    propose(client)
    decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the first approval",
        },
    )
    corrected = decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "correct",
            "entity_id": "party_false_friend",
            "reason": "the steward corrected the link to the other party",
            "evidence": [
                {
                    "field": "party_ref",
                    "value": "party_false_friend",
                    "note": "the source reference names the other party",
                }
            ],
        },
    )
    assert corrected["value"]["link_status"] == "approved"
    assert corrected["value"]["entity_id"] == "party_false_friend"

    history = client.get(
        "/api/registry/crosswalks/history",
        params={"source_system_id": "permitting", "source_record_id": "PER-AP-0003"},
    )
    assert history.status_code == 200
    rows = history.json()["crosswalks"]
    statuses = [row["link_status"] for row in rows]
    assert statuses.count("approved") == 1
    assert statuses.count("superseded") == 1
    superseded = next(row for row in rows if row["link_status"] == "superseded")
    assert superseded["entity_id"] == "party_cedarline"
    assert superseded["decision"] == "the first approval"
    assert superseded["decision_actor_id"] == "persona_data_steward"
    assert superseded["decided_at"]
    assert superseded["superseded_by_crosswalk_id"]


def test_the_trusted_view_is_available_for_a_linked_entity(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    propose(client)
    decide(
        client,
        {
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the declared reference and the recorded alias agree",
        },
    )
    response = client.get("/api/registry/entities/party_cedarline/trusted-view")
    assert response.status_code == 200
    payload = response.json()
    assert payload["entity_id"] == "party_cedarline"
    fields = {field["attribute_path"]: field for field in payload["fields"]}
    assert fields["display_name"]["state"] == "authoritative"
    assert fields["display_name"]["value"] == "Cedar Line Coffee Roasters"

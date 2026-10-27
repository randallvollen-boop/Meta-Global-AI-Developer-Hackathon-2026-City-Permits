"""AT20: a link is corrected reversibly and the impact is registered.

The earlier decision survives the correction, the new link carries its own
version and reason, and the dependent records are registered for review
instead of being changed in place.
"""
# REQUIRES: AT20, MDM-05, CHG-03, CHG-04
# A link correction is reversible, names its reason and expected version, and
# registers the dependent work while the issued history stays untouched.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.changes.router import router as changes_router
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import change, permit, registry
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at20.db'}",
            "ACME_SECRET_KEY": "at20-acceptance-secret-value",
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
    app.include_router(changes_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def approve_link(client: TestClient, record_id: str = "PER-AP-0003") -> dict:
    """Propose and approve the link of one source record."""
    select_persona(client, "persona_data_steward")
    proposed = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": record_id,
        },
    )
    assert proposed.status_code == 200, proposed.text
    decided = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": record_id,
            "decision": "approve",
            "reason": "the declared reference and the recorded alias agree",
            "evidence": [
                {"field": "party_ref", "value": "party_cedarline", "note": "the reference"}
            ],
        },
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


def test_at20_a_link_correction_keeps_the_earlier_decision(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    first = approve_link(client)
    original_crosswalk_id = first["value"]["crosswalk_id"]

    select_persona(client, "persona_data_steward")
    corrected = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "correct",
            "entity_id": "party_false_friend",
            "reason": "the steward corrected the link after the unit was checked again",
            "evidence": [
                {
                    "field": "business_address",
                    "value": "400 Lantern Row Unit 5",
                    "note": "the unit of the source record is unit five",
                }
            ],
        },
    )
    assert corrected.status_code == 200, corrected.text
    payload = corrected.json()
    assert payload["value"]["link_status"] == "approved"
    assert payload["value"]["entity_id"] == "party_false_friend"
    assert payload["value"]["crosswalk_id"] != original_crosswalk_id
    assert payload["value"]["decision"] == (
        "the steward corrected the link after the unit was checked again"
    )

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "PER-AP-0003"
                )
            ).scalars().all()
            assert len(rows) == 2
            original = session.get(registry.Crosswalk, original_crosswalk_id)
            assert original.link_status == "superseded"
            assert original.decision == "the declared reference and the recorded alias agree"
            assert original.decision_actor_id == "persona_data_steward"
            assert original.decided_at is not None
            assert original.superseded_by_crosswalk_id == payload["value"]["crosswalk_id"]
            approved = [row for row in rows if row.link_status == "approved"]
            assert len(approved) == 1
    finally:
        factory.dispose()

    record_property(
        "evidence",
        {
            "source_record_id": "PER-AP-0003",
            "superseded_crosswalk_id": original_crosswalk_id,
            "new_crosswalk_id": payload["value"]["crosswalk_id"],
            "new_entity_id": "party_false_friend",
            "deciding_actor": "persona_data_steward",
            "reason": payload["value"]["decision"],
        },
    )


def test_at20_the_correction_registers_the_dependent_review_work(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    approve_link(client)
    select_persona(client, "persona_data_steward")
    corrected = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "correct",
            "entity_id": "party_false_friend",
            "reason": "the steward corrected the link after the unit was checked again",
        },
    )
    assert corrected.status_code == 200, corrected.text
    crosswalk_id = corrected.json()["value"]["crosswalk_id"]

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            tasks = session.execute(
                select(change.ReviewTask).where(
                    change.ReviewTask.deduplication_key.like(
                        f"crosswalk_revalidation:{crosswalk_id}:%"
                    )
                )
            ).scalars().all()
            assert tasks
            keys = [task.deduplication_key for task in tasks]
            assert len(keys) == len(set(keys))
            reviews = session.execute(
                select(permit.ImpactReview).where(
                    permit.ImpactReview.target_id == crosswalk_id
                )
            ).scalars().all()
            assert len(reviews) == 1
            assert reviews[0].status == "open"
    finally:
        factory.dispose()

    record_property(
        "evidence",
        {
            "crosswalk_id": crosswalk_id,
            "review_task_count": len(tasks),
            "impact_review_id": reviews[0].id,
        },
    )


def test_at20_the_impact_preview_names_the_dependent_records(
    client: TestClient, environment: tuple[Settings, FixtureBundle], record_property
) -> None:
    settings, _ = environment
    approve_link(client)
    select_persona(client, "persona_data_steward")
    preview = client.post(
        "/api/changes/impact/preview",
        json={"target_type": "canonical_entity", "target_id": "party_cedarline"},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert "app_synth_001" in payload["applications"]
    assert payload["total_affected"] >= 1
    assert payload["rechecks"]
    record_property(
        "evidence",
        {
            "target_entity_id": "party_cedarline",
            "affected_applications": payload["applications"],
            "total_affected": payload["total_affected"],
        },
    )


def test_at20_the_issued_history_is_not_rewritten(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    approve_link(client)
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            issued = session.get(permit.Permit, "permit_d07")
            assert issued is not None
            assert issued.permit_number == "ACME-2026-000731"
            assert issued.artifact_hash
            assert issued.issued_at is not None
            assert issued.snapshot["declared_valuation_cents"] == 12000000
            decision = session.get(permit.Decision, "decision_d07")
            assert decision is not None
            assert decision.stale is False
            assert decision.outcome == "approved"
    finally:
        factory.dispose()

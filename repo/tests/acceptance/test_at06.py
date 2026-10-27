"""AT06: every link is evidence based and every new link needs a steward.

A proposal names the evidence it was built from, a similar name or a shared
address never establishes a link on its own, and the unit, issuer and
credential distinctions stay visible as conflicting evidence.
"""
# REQUIRES: AT06, MDM-02, MDM-03
# A link is proposed with its evidence, it is never approved automatically, and
# a false friend keeps the contradicting evidence visible.

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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at06.db'}",
            "ACME_SECRET_KEY": "at06-acceptance-secret-value",
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


def test_at06_a_proposal_carries_its_supporting_and_conflicting_evidence(
    client: TestClient, record_property
) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "erp_finance",
            "dataset_key": "business_licensing_register",
            "source_record_id": "ERP-BL-00413",
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["disposition"] == "unresolved"
    assert proposal["candidate_ids"]
    supporting = proposal["supporting_evidence"]
    conflicting = proposal["conflicting_evidence"]
    assert supporting and conflicting
    for item in supporting:
        assert item["direction"] == "supporting"
        assert item["field"]
        assert item["method"]
        assert item["source_snapshot_id"]
    for item in conflicting:
        assert item["direction"] == "conflicting"
    methods = {item["method"] for item in conflicting}
    assert "source_reference_mismatch" in methods
    assert "credential_number_conflict" in methods
    assert "address_unit_conflict" in methods
    record_property(
        "evidence",
        {
            "proposal_id": proposal["proposal_id"],
            "source_snapshot_id": proposal["source_snapshot_id"],
            "disposition": proposal["disposition"],
            "supporting_methods": sorted({item["method"] for item in supporting}),
            "conflicting_methods": sorted(methods),
        },
    )


def test_at06_a_proposal_never_approves_a_link(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["disposition"] in {"supported", "unresolved"}
    assert proposal["created_by_actor_id"] == "persona_data_steward"

    links = client.get(
        "/api/registry/crosswalks",
        params={"source_system_id": "permitting", "source_record_id": "PER-AP-0003"},
    ).json()["crosswalks"]
    assert links
    assert {row["link_status"] for row in links} == {"proposed"}
    assert {row["decision_actor_id"] for row in links} == {None}


def test_at06_the_proposal_score_is_never_presented_as_calibrated(
    client: TestClient,
) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "erp_finance",
            "dataset_key": "business_licensing_register",
            "source_record_id": "ERP-BL-00412",
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["score_is_calibrated"] is False
    assert proposal["score_label"] == "uncalibrated_heuristic"
    assert proposal["proposal_score"] is None or 0.0 <= proposal["proposal_score"] <= 1.0


def test_at06_a_similar_name_and_a_shared_address_do_not_establish_a_link(
    client: TestClient, environment: tuple[Settings, FixtureBundle]
) -> None:
    settings, _ = environment
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "erp_finance",
            "dataset_key": "business_licensing_register",
            "source_record_id": "ERP-BL-00413",
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            approved = session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_record_id == "ERP-BL-00413",
                    registry.Crosswalk.link_status == "approved",
                )
            ).scalars().all()
            assert approved == []
    finally:
        factory.dispose()
    assert "party_cedarline" in proposal["candidate_ids"]


def test_at06_a_record_without_a_shared_key_is_an_explicit_no_match(
    client: TestClient, record_property
) -> None:
    select_persona(client, "persona_data_steward")
    response = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applications_and_permits",
            "source_record_id": "PER-APP-SYN-APP-004",
            "entity_type": "parcel",
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["disposition"] == "no_match"
    assert proposal["candidate_ids"] == []
    record_property(
        "evidence",
        {
            "proposal_id": proposal["proposal_id"],
            "disposition": proposal["disposition"],
            "candidate_count": len(proposal["candidate_ids"]),
        },
    )

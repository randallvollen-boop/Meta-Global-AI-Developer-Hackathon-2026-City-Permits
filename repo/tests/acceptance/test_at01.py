"""AT01: the governed foundation the registry and the sources rest on.

The acceptance run observes the governance of the published datasets through
the real endpoints: the registration is complete, the responsibility resolves
through effective assignments, the queue has its people, and a governed record
shows its owner, its steward, its source and its versions.
"""
# REQUIRES: AT01, GOV-01, GOV-02, GOV-03, GOV-04, GOV-05, GOV-06, EDIT-01
# The datasets the registry publishes are fully registered, the responsibility
# resolves through the effective assignments, and a governed record shows where
# it came from and where it may be changed.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.changes.router import router as changes_router
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.governance.router import router as governance_router
from acme_city.ingestion.router import router as ingestion_router
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at01.db'}",
            "ACME_SECRET_KEY": "at01-acceptance-secret-value",
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
    app.include_router(governance_router)
    app.include_router(ingestion_router)
    app.include_router(registry_router)
    app.include_router(changes_router)
    with TestClient(app) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_at01_every_published_dataset_is_fully_registered(
    client: TestClient, record_property
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/api/governance/datasets")
    assert response.status_code == 200, response.text
    registrations = response.json()["registrations"]
    assert registrations
    incomplete = [row for row in registrations if not row["publishable"]]
    # The registry's own link-decision record has no single accountable owner:
    # a link is owned by the domain of the entity it links.
    assert [row["dataset_key"] for row in incomplete] == ["source_crosswalk"]
    assert incomplete[0]["missing_bindings"]
    for row in registrations:
        if not row["publishable"]:
            continue
        assert row["accountable_owner_actor_id"]
        assert row["steward_queue_id"]
        assert row["system_custodian_actor_id"]
        assert row["authority_policy_id"]
        assert row["correction_route"]
        assert row["registration_state"] == "complete"
    record_property(
        "evidence",
        {
            "registered_dataset_count": len(registrations),
            "publishable_dataset_count": len(registrations) - len(incomplete),
            "unpublishable_datasets": [row["dataset_key"] for row in incomplete],
        },
    )


def test_at01_the_responsibility_resolves_through_the_effective_assignments(
    client: TestClient, record_property
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/api/governance/responsibility/permits")
    assert response.status_code == 200, response.text
    panel = response.json()
    assert panel["domain_id"] == "permits"
    assert panel["owner"] == "service_owner_building_safety"
    assert panel["steward"] == "persona_data_steward"
    assert panel["source"] == "permitting"
    assert panel["version"] >= 1
    responsibilities = {row["responsibility"] for row in panel["assignments"]}
    assert {"owner", "steward", "delegate", "escalation", "custodian"} <= responsibilities
    assert all(row["effective_to"] is None for row in panel["assignments"])
    record_property(
        "evidence",
        {
            "domain_id": panel["domain_id"],
            "owner": panel["owner"],
            "steward": panel["steward"],
            "source": panel["source"],
            "assignments": sorted(responsibilities),
        },
    )


def test_at01_a_governed_record_shows_its_destination_and_its_steward(
    client: TestClient, record_property
) -> None:
    select_persona(client, "persona_data_steward")
    created = client.post(
        "/api/changes",
        json={
            "target_type": "source_record",
            "target_id": "gis/address_register/GIS-AD-0400",
            "title": "Fictional correction of an official address",
            "reason": "the postcode of the official address is wrong in the demonstration",
            "proposed_value": {"address_id": "GIS-AD-0400"},
        },
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["destination"] == "GIS address register"
    assert payload["assignee_actor_id"] == "persona_data_steward"
    assert payload["expected_version"] == 5
    assert payload["requester_actor_id"] == "persona_data_steward"
    record_property(
        "evidence",
        {
            "change_case_id": payload["change_case_id"],
            "destination": payload["destination"],
            "assignee_actor_id": payload["assignee_actor_id"],
            "expected_source_version": payload["expected_version"],
        },
    )


def test_at01_the_source_systems_are_simulated_and_labeled(client: TestClient) -> None:
    select_persona(client, "persona_data_steward")
    response = client.get("/api/sources/systems")
    assert response.status_code == 200, response.text
    payload = response.json()
    systems = {row["source_system_id"]: row for row in payload["source_systems"]}
    for source_system_id in ("permitting", "gis", "erp_finance"):
        assert systems[source_system_id]["simulated"] is True
        assert systems[source_system_id]["incoming"] is True
    assert systems["registry"]["simulated"] is False

    adapters = {row["source_system_id"]: row for row in payload["adapters"]}
    assert set(adapters) == {"permitting", "gis", "erp_finance"}
    for row in adapters.values():
        assert row["simulated"] is True
        assert "simulated" in row["label"].lower()
        assert row["dataset_keys"]

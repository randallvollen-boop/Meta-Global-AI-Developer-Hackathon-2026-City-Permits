"""VC01: normalization is safe.

The raw value survives beside its comparison form, the unit distinction
survives, and a normalized value never carries authority or an identity.
"""
# REQUIRES: VC01, ING-04
# Normalization keeps the raw value, keeps the unit boundary, and never
# establishes authority or identity.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.normalization import (
    address_unit_conflicts,
    normalize_address,
    normalize_name,
)
from acme_city.ingestion.router import router as ingestion_router
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc01.db'}",
            "ACME_SECRET_KEY": "vc01-supplementary-secret-value",
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
    app.include_router(ingestion_router)
    with TestClient(app) as test_client:
        yield test_client


def test_vc01_the_raw_payload_is_preserved_next_to_the_record(
    client: TestClient,
) -> None:
    response = client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
    assert response.status_code == 200, response.text
    raw = {
        "party_ref": "party_applicant_1",
        "display_name": "  Demo   Applicant  ",
        "contact_email": "DEMO.APPLICANT@Example.invalid",
        "contact_phone": "+1 (555) 0141",
        "preferred_contact": "email",
    }
    ingested = client.post(
        "/api/sources/permitting/applicant_profiles/intake",
        json={
            "records": [
                {
                    "source_record_id": "PER-AP-VC01-0001",
                    "source_record_version": "1",
                    "payload": raw,
                }
            ]
        },
    )
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["accepted"] == 1

    snapshots = client.get(
        "/api/sources/permitting/applicant_profiles/snapshots",
        params={"record_id": "PER-AP-VC01-0001"},
    ).json()["snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["raw_payload"] == raw
    assert snapshots[0]["payload_hash"]


def test_vc01_the_unit_distinction_survives_the_comparison_form() -> None:
    unit_two = normalize_address("400 Lantern Row, Suite 2, ACME City")
    unit_five = normalize_address("400 Lantern Row Unit 5")
    assert unit_two.unit_number == "2"
    assert unit_five.unit_number == "5"
    assert address_unit_conflicts(unit_two, unit_five)
    assert unit_two.raw == "400 Lantern Row, Suite 2, ACME City"


def test_vc01_a_normalized_value_carries_no_identity_or_authority() -> None:
    normalized = normalize_name("Cedar Line Coffee Roasters")
    assert normalized.raw == "Cedar Line Coffee Roasters"
    assert normalized.normalized == "cedar line coffee roasters"
    for field_name in normalized.__dataclass_fields__:
        assert "entity" not in field_name
        assert "link" not in field_name
        assert "authority" not in field_name
        assert "decision" not in field_name

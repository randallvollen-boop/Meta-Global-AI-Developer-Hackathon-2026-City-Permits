"""Address to parcel: the locator, the steward, the reviewer, the record and the map.

The GIS is simulated in-app.  The parcel number is the key; an address only
finds it.  Nothing is approved until the Data Steward approves the parcel link
and the Permit Reviewer confirms the parcel.
"""
# REQUIRES: GIS-03, GIS-04, GIS-05, GIS-06

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
from acme_city.persistence.models import gis, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'property.db'}",
            "ACME_SECRET_KEY": "property-test-secret-value",
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
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, *paths: str) -> str:
    """Return the CSRF token of the first page that carries a form."""
    for path in paths:
        match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
        if match:
            return match.group(1)
    raise AssertionError(f"no form with a CSRF token on {paths}")


def post_action(client: TestClient, action_id: str, fields: dict, next_path: str):
    return client.post(
        f"/ui/actions/{action_id}",
        data={"csrf_token": csrf(client, next_path, "/agent/intake", "/agent/adjudication", "/queue", "/masters"), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def act(client: TestClient, action_id: str, fields: dict, next_path: str) -> dict:
    response = post_action(client, action_id, fields, next_path)
    assert response.status_code == 200, response.text
    return response.json()


def run_scenario(client: TestClient, scenario: str) -> str:
    """Simulate a scenario, wake the intake agent and run it; return the case id."""
    choose(client, "persona_city_administrator")
    response = client.post("/api/intake/simulate", json={"scenario": scenario})
    assert response.status_code == 200, response.text
    (result,) = response.json()["results"]
    act(client, "agent.toggle", {"agent_key": "intake", "mode": "awake"}, "/agent/intake")
    choose(client, "persona_data_steward")
    act(client, "agent.run.intake", {}, "/agent/intake")
    return result["application_id"]


def match_row(settings, application_id: str) -> dict:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == application_id
                )
            ).scalar_one()
            return {
                "state": row.link_state,
                "version": row.version,
                "score": row.score,
                "status": row.locator_status,
                "parcel": row.parcel_number,
                "matched": row.matched_address,
                "candidates": list(row.candidates or []),
                "confirmed": row.confirmed_at is not None,
            }
    finally:
        factory.dispose()


def findings(settings, application_id: str) -> list[str]:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return [
                row.message
                for row in session.execute(
                    select(permit.ApplicationFinding).where(
                        permit.ApplicationFinding.application_id == application_id
                    )
                ).scalars()
            ]
    finally:
        factory.dispose()


def test_address_typo_is_corrected_and_proposed(client, environment) -> None:
    case = run_scenario(client, "address-typo")
    row = match_row(environment, case)
    assert row["state"] == "proposed"
    assert row["score"] >= 90 and row["status"] == "M"
    assert row["parcel"] == "ACME-P-1004"
    assert row["matched"].startswith("412 Maple Ridge Drive")
    body = client.get(f"/permits/{case}").text
    assert 'data-testid="property-card"' in body
    assert "412 Mapel Rdg Dr" in body and "412 Maple Ridge Drive" in body
    assert 'data-testid="property-inset"' in body and "<svg" in body
    assert "ACME-P-1004" in body
    review = client.get("/steward").text
    assert 'data-testid="parcel-proposal"' in review


def test_proposal_needs_steward_then_reviewer_before_approval(client, environment) -> None:
    case = run_scenario(client, "address-typo")
    version = match_row(environment, case)["version"]
    # The reviewer cannot approve the link: that is the steward's identity decision.
    choose(client, "persona_permit_reviewer")
    denied = post_action(
        client,
        "parcel.link.decide",
        {"application_id": case, "decision": "approve", "reason": "x", "expected_version": str(version)},
        "/steward",
    )
    assert denied.status_code == 403, denied.text
    # The steward cannot confirm the parcel: that is the reviewer's check.
    choose(client, "persona_data_steward")
    denied = post_action(
        client,
        "parcel.confirm",
        {"application_id": case, "expected_version": str(version)},
        f"/permits/{case}",
    )
    assert denied.status_code == 403, denied.text
    approved = act(
        client,
        "parcel.link.decide",
        {"application_id": case, "decision": "approve", "reason": "the point is inside the parcel", "expected_version": str(version)},
        "/steward",
    )
    assert approved["status"] == "accepted"
    assert match_row(environment, case)["state"] == "approved"
    # A stale version is refused.
    stale = post_action(
        client,
        "parcel.link.decide",
        {"application_id": case, "decision": "reject", "reason": "x", "expected_version": str(version)},
        "/steward",
    )
    assert stale.status_code == 409, stale.text
    choose(client, "persona_permit_reviewer")
    version = match_row(environment, case)["version"]
    confirmed = act(
        client,
        "parcel.confirm",
        {"application_id": case, "expected_version": str(version), "reason": "right property"},
        f"/permits/{case}",
    )
    assert confirmed["status"] == "accepted"
    assert match_row(environment, case)["confirmed"] is True


def test_decision_blocked_until_parcel_approved_and_confirmed(client, environment) -> None:
    from acme_city.permits.service import PermitService

    case = run_scenario(client, "address-typo")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, case)
            codes = [b.code for b in PermitService(session).parcel_link_blockers(application)]
            assert codes == ["parcel_link_unapproved"]
    finally:
        factory.dispose()
    version = match_row(environment, case)["version"]
    act(
        client,
        "parcel.link.decide",
        {"application_id": case, "decision": "approve", "reason": "ok", "expected_version": str(version)},
        "/steward",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, case)
            codes = [b.code for b in PermitService(session).parcel_link_blockers(application)]
            assert codes == ["parcel_unconfirmed"]
    finally:
        factory.dispose()


def test_ambiguous_address_needs_a_person_to_choose(client, environment) -> None:
    case = run_scenario(client, "address-ambiguous")
    row = match_row(environment, case)
    assert row["state"] == "needs_choice"
    assert len(row["candidates"]) >= 2
    assert any("Address needs a person to choose the property" in m for m in findings(environment, case))
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert session.get(permit.Application, case).status == "needs_information"
    finally:
        factory.dispose()
    choose(client, "persona_permit_reviewer")
    chosen = row["candidates"][0]["address_id"]
    result = act(
        client,
        "parcel.candidate.choose",
        {
            "application_id": case,
            "address_id": chosen,
            "reason": "the applicant means the building",
            "expected_version": str(row["version"]),
        },
        f"/permits/{case}",
    )
    assert result["status"] == "accepted"
    after = match_row(environment, case)
    assert after["state"] == "proposed" and after["parcel"] == "ACME-P-1001"


def test_unknown_address_is_not_found_and_parcel_can_be_found_by_number(client, environment) -> None:
    case = run_scenario(client, "address-unknown")
    row = match_row(environment, case)
    assert row["state"] == "not_found"
    assert any("Address not found in the city locator" in m for m in findings(environment, case))
    choose(client, "persona_permit_reviewer")
    result = act(
        client,
        "parcel.find",
        {
            "application_id": case,
            "parcel_number": "ACME-P-1004",
            "reason": "the applicant gave the parcel number by phone",
            "expected_version": str(row["version"]),
        },
        f"/permits/{case}",
    )
    assert result["status"] == "accepted"
    after = match_row(environment, case)
    assert after["state"] == "proposed" and after["parcel"] == "ACME-P-1004"
    missing = post_action(
        client,
        "parcel.find",
        {
            "application_id": case,
            "parcel_number": "ACME-P-9999",
            "reason": "typo",
            "expected_version": str(after["version"]),
        },
        f"/permits/{case}",
    )
    assert missing.status_code == 422


def test_property_record_search_map_and_shared_with(client, environment) -> None:
    case = run_scenario(client, "address-typo")
    version = match_row(environment, case)["version"]
    act(
        client,
        "parcel.link.decide",
        {"application_id": case, "decision": "approve", "reason": "ok", "expected_version": str(version)},
        "/steward",
    )
    record = client.get("/property/ACME-P-1004")
    assert record.status_code == 200
    text = record.text
    assert 'data-testid="shared-with"' in text
    for department in ("Tax / Assessor", "Fire and life safety", "Code enforcement", "Utilities"):
        assert department in text
    assert "simulated consumers" in text
    assert 'data-testid="record-applications"' in text and case in text
    assert 'data-testid="record-owner"' in text
    assert client.get("/property/ACME-P-0000").status_code == 404

    found = client.get("/property", params={"q": "412 Mapel Rdg Dr"})
    assert found.status_code == 200
    assert "412 Maple Ridge Drive" in found.text and "ACME-P-1004" in found.text

    town = client.get("/map", params={"parcel": "ACME-P-1004"})
    assert town.status_code == 200
    assert 'data-testid="town-map"' in town.text and 'data-testid="map-parcel-table"' in town.text
    assert "<title>" in town.text and 'data-testid="map-legend"' in town.text
    assert "https://" not in town.text.replace("http://www.w3.org", "")

    masters = client.get("/masters").text
    assert 'data-testid="find-property"' in masters

    choose(client, "persona_city_administrator")
    governance = client.get("/governance").text
    assert "Property master (parcel, address, owner, zoning)" in governance
    assert 'data-testid="dataset-subscribers"' in governance


def test_applicant_does_not_get_the_staff_map(client) -> None:
    choose(client, "persona_applicant")
    assert client.get("/map").status_code == 403
    assert client.get("/property/ACME-P-1001").status_code == 403

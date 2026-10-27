"""AT02: edit destinations.

Every record family names exactly one correction destination and one
responsible queue.  A person who may not edit a record freely is refused and
is shown the route to request a correction instead.  The correction carries
the old value, the proposed value, the evidence, the destination and the
records it would affect before anybody approves it.
"""
# REQUIRES: AT02, EDIT-01, EDIT-02, EDIT-03, UX-01
# Each record family names one correction destination. An unauthorized person is refused and
# offered the correction route, and the preview names the affected records before approval.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

#: The five record families the check opens, with the dataset that carries the
#: record facts of that family.
RECORD_FAMILIES: dict[str, str] = {
    "Applicant": "applicant_profiles",
    "Property": "parcel_register",
    "Contractor": "contractor_register",
    "Permit": "applications_and_permits",
    "Reconciliation": "fee_assessments",
}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Return a client for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at02.db'}",
            "ACME_SECRET_KEY": "at02-edit-destinations-secret-value",
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
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def sign_in(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def test_at02_every_record_family_names_one_correction_destination(
    client: TestClient,
) -> None:
    sign_in(client, "persona_city_administrator")
    listed = client.get("/api/governance/datasets")
    assert listed.status_code == 200, listed.text
    registrations = {entry["dataset_key"]: entry for entry in listed.json()["registrations"]}

    destinations: dict[str, str] = {}
    for family, dataset_key in RECORD_FAMILIES.items():
        assert dataset_key in registrations, f"{family} has no registered dataset"
        registration = registrations[dataset_key]
        route = registration["correction_route"]
        assert route, f"{family} has no correction destination"
        assert registration["steward_queue_id"], f"{family} has no responsible queue"
        assert registration["domain_id"], f"{family} has no owning domain"
        destinations[family] = route

    # Each family routes its corrections somewhere of its own.
    assert len(set(destinations.values())) == len(RECORD_FAMILIES)
    assert destinations["Applicant"] == "Permitting applicant profile"
    assert destinations["Property"] == "GIS parcel register"
    assert destinations["Contractor"] == "Permitting contractor register"
    assert destinations["Permit"] == "Permitting application workspace"
    assert destinations["Reconciliation"] == "Governed fee assessment"


def test_at02_the_responsible_queue_is_resolved_for_every_family(
    client: TestClient,
) -> None:
    sign_in(client, "persona_city_administrator")
    listed = client.get("/api/governance/datasets")
    registrations = {entry["dataset_key"]: entry for entry in listed.json()["registrations"]}
    for dataset_key in RECORD_FAMILIES.values():
        domain_id = registrations[dataset_key]["domain_id"]
        panel = client.get(f"/api/governance/responsibility/{domain_id}")
        assert panel.status_code == 200, panel.text
        payload = panel.json()
        assert payload["owner"], f"{domain_id} has no accountable owner"
        assert payload["steward"], f"{domain_id} has no effective steward"
        assert payload["queue"], f"{domain_id} has no responsible queue"


def test_at02_an_unauthorized_person_is_refused_and_is_offered_the_route(
    client: TestClient,
) -> None:
    sign_in(client, "persona_applicant")

    # An unrestricted edit of another applicant's case is refused.
    refused = client.post(
        "/api/permits/applications/app_synth_001/revisions",
        json={
            "application_id": "app_synth_001",
            "facts": {"contact_email": "someone@example.invalid"},
            "reason": "a fictional edit",
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    # An authorized steward verifies the refused edit left the record untouched.
    sign_in(client, "persona_data_steward")
    application = client.get("/api/permits/applications/app_synth_001")
    assert application.status_code == 200
    assert application.json()["revision_number"] == 1

    # The applicant may ask for a correction, and the case names the route
    # and the responsible steward.
    sign_in(client, "persona_applicant")
    requested = client.post(
        "/api/changes",
        json={
            "target_type": "application",
            "target_id": "SYN-APP-005",
            "title": "Fictional correction of the contact address",
            "reason": "the applicant typed a different address in the demonstration",
            "proposed_value": {"contact_email": "t.aldous.new@example.invalid"},
            "old_value": {"contact_email": "t.aldous@example.invalid"},
        },
    )
    assert requested.status_code == 200, requested.text
    case = requested.json()
    assert case["status"] == "requested"
    assert case["destination"] == "Permitting application workspace"
    assert case["assignee_actor_id"], "the correction has no responsible steward"
    assert case["requester_actor_id"] == "persona_applicant"
    assert case["old_value"]["contact_email"] == "t.aldous@example.invalid"
    assert case["proposed_value"]["contact_email"] == "t.aldous.new@example.invalid"

    # The offered route is a request, not an edit: nothing changed.
    unchanged = client.get("/api/permits/applications/app_d05")
    assert unchanged.status_code == 200
    assert unchanged.json()["snapshot"]["contact_email"] == "t.aldous@example.invalid"


def test_at02_the_correction_is_previewed_before_it_is_approved(
    client: TestClient,
) -> None:
    sign_in(client, "persona_data_steward")
    requested = client.post(
        "/api/changes",
        json={
            "target_type": "source_record",
            "target_id": "gis/parcel_register/GIS-PCL-1001",
            "title": "Fictional correction of the official parcel record",
            "reason": "the demonstration parcel record is out of date",
            "old_value": {"parcel_number": "ACME-P-1001"},
            "proposed_value": {"parcel_number": "ACME-P-1001", "status": "corrected"},
            "evidence": [
                {
                    "field": "parcel_number",
                    "value": "ACME-P-1001",
                    "note": "the steward compared the official register with the application",
                }
            ],
        },
    )
    assert requested.status_code == 200, requested.text
    case = requested.json()
    assert case["destination"] == "GIS parcel register"
    assert case["evidence"][0]["field"] == "parcel_number"

    preview = client.get(f"/api/changes/{case['change_case_id']}/impact")
    assert preview.status_code == 200, preview.text
    impact = preview.json()
    assert impact["target_id"] == "gis/parcel_register/GIS-PCL-1001"
    assert impact["applications"], "the preview names no affected application"
    assert "app_synth_001" in impact["applications"]
    assert impact["rechecks"], "the preview names no recheck"
    assert impact["total_affected"] >= len(impact["applications"])

    # The case is still waiting: a preview never approves anything.
    still = client.get(f"/api/changes/{case['change_case_id']}")
    assert still.json()["status"] == "requested"
    assert still.json()["approver_actor_id"] is None


def test_at02_the_field_level_authority_is_available_on_demand(
    client: TestClient,
) -> None:
    sign_in(client, "persona_data_steward")
    proposed = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert proposed.status_code == 200, proposed.text
    decided = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "the alias spelling names the same organization in the demonstration",
            "evidence": [
                {
                    "field": "organization_name",
                    "value": "Cedar Line Coffee Roasters",
                    "note": "the steward compared the alias with the recorded party",
                }
            ],
        },
    )
    assert decided.status_code == 200, decided.text

    view = client.get("/api/registry/entities/party_cedarline/trusted-view")
    assert view.status_code == 200, view.text
    payload = view.json()
    fields = payload["fields"]
    assert fields, "the trusted view shows no field"
    for field in fields:
        assert field["attribute_path"]
        assert field["state"] in {"authoritative", "disputed", "absent"}
        assert field["authority_policy_id"], f"{field['attribute_path']} names no authority"
        assert field["reasons"], f"{field['attribute_path']} explains no reason"
    contact = next(item for item in fields if item["attribute_path"] == "contact_email")
    assert contact["state"] == "authoritative"
    assert contact["source_system_id"] == "permitting"
    assert contact["source_record_id"] == "PER-AP-0003"
    assert contact["authority_policy_id"] == "authority_applicant_contact"

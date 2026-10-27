"""AT03: direct access controls.

A person who acts outside their grant is refused by the server, and no
business record changes when they try: another applicant's case, a permit
approval by a clerk, a source link change by an applicant, a receipt edit by
a reviewer and a permit approval by the City Administrator, whose
configuration grants never imply a business approval.
"""
# REQUIRES: AT03, SEC-01, SEC-02, SEC-03
# Every attempt outside the persisted grant is refused by the server and leaves the business
# records unchanged.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import change, finance, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[TestClient, Settings]:
    """Return a client and the settings of a freshly reset demonstration."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at03.db'}",
            "ACME_SECRET_KEY": "at03-direct-access-controls-secret",
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
        yield test_client, settings


def sign_in(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def business_counts(settings: Settings) -> dict[str, int]:
    """Return the number of business records that an attempt may not change."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return {
                "decisions": session.execute(
                    select(func.count()).select_from(permit.Decision)
                ).scalar_one(),
                "crosswalks": session.execute(
                    select(func.count()).select_from(registry.Crosswalk)
                ).scalar_one(),
                "allocations": session.execute(
                    select(func.count()).select_from(finance.Allocation)
                ).scalar_one(),
                "payments": session.execute(
                    select(func.count()).select_from(finance.PaymentEvent)
                ).scalar_one(),
                "revisions": session.execute(
                    select(func.count()).select_from(permit.ApplicationRevision)
                ).scalar_one(),
                "change_cases": session.execute(
                    select(func.count()).select_from(change.ChangeCase)
                ).scalar_one(),
            }
    finally:
        factory.dispose()


def test_at03_an_applicant_may_not_change_another_applicants_record(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    before = business_counts(settings)
    sign_in(client, "persona_applicant")

    refused = client.post(
        "/api/permits/applications/app_synth_001/revisions",
        json={
            "application_id": "app_synth_001",
            "facts": {"contact_email": "someone@example.invalid"},
            "reason": "a fictional edit of another organization's case",
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    after = business_counts(settings)
    assert after == before, "a refused edit changed a business record"


def test_at03_the_work_queue_of_an_applicant_shows_only_its_own_records(
    environment: tuple[TestClient, Settings],
) -> None:
    client, _settings = environment
    sign_in(client, "persona_applicant")
    listed = client.get("/api/permits/applications")
    assert listed.status_code == 200, listed.text
    identifiers = {entry["application_id"] for entry in listed.json()["applications"]}
    assert "app_d05" in identifiers
    assert "app_synth_001" not in identifiers
    assert "app_d02" not in identifiers


def test_at03_a_clerk_may_not_approve_a_permit(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    before = business_counts(settings)
    sign_in(client, "persona_data_steward")

    refused = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"outcome": "approved", "reason": "a fictional approval by a clerk"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    also_refused = client.post("/api/permits/applications/app_synth_001/evaluate")
    assert also_refused.status_code == 403, also_refused.text

    after = business_counts(settings)
    assert after == before, "a refused approval changed a business record"


def test_at03_the_city_administrator_may_not_approve_a_permit(
    environment: tuple[TestClient, Settings],
) -> None:
    """The administrator grants configuration, never a business approval."""
    client, settings = environment
    before = business_counts(settings)
    sign_in(client, "persona_city_administrator")

    refused = client.post(
        "/api/permits/applications/app_synth_001/decisions",
        json={"outcome": "approved", "reason": "a fictional approval by the administrator"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    after = business_counts(settings)
    assert after == before, "a refused approval changed a business record"


def test_at03_an_applicant_may_not_change_a_source_link(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    before = business_counts(settings)
    sign_in(client, "persona_applicant")

    refused = client.post(
        "/api/registry/decisions",
        json={
            "source_system_id": "permitting",
            "source_record_id": "PER-AP-0003",
            "decision": "approve",
            "reason": "a fictional link decision by an applicant",
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    proposed = client.post(
        "/api/registry/proposals",
        json={
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    assert proposed.status_code == 403, proposed.text

    after = business_counts(settings)
    assert after == before, "a refused link change created a business record"


def test_at03_a_reviewer_may_not_edit_a_receipt(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    before = business_counts(settings)
    sign_in(client, "persona_permit_reviewer")

    refused = client.post(
        "/api/finance/allocations",
        json={
            "payment_id": "payment_d01_settled",
            "assessment_id": "assess_d01_v1",
            "amount": "150.00",
            "currency": "USD",
            "idempotency_key": "at03-reviewer-allocation",
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "permission_denied"

    import_refused = client.post(
        "/api/finance/payments",
        json={
            "source_transaction_id": "ERP-EVT-AT03-1",
            "source_event_id": "ERP-EVT-AT03-1",
            "event_type": "settled",
            "amount": "150.00",
            "currency": "USD",
        },
    )
    assert import_refused.status_code == 403, import_refused.text

    after = business_counts(settings)
    assert after == before, "a refused receipt edit changed a business record"


def test_at03_an_applicant_may_not_read_another_applicants_record(
    environment: tuple[TestClient, Settings],
) -> None:
    """SEC-02: the record scope reaches a direct URL, not only a list."""
    client, _settings = environment
    sign_in(client, "persona_applicant")
    refused = client.get("/api/permits/applications/app_synth_001")
    assert refused.status_code == 403, (
        "the application of another applicant was served to the applicant: "
        f"{refused.status_code} {refused.text[:200]}"
    )
    assert refused.json()["code"] == "permission_denied"


def test_at03_an_applicant_may_not_read_foreign_evaluations_or_documents(
    environment: tuple[TestClient, Settings],
) -> None:
    """SEC-02 applies to related-record URLs and document bytes."""
    client, _settings = environment
    sign_in(client, "persona_data_steward")
    uploaded = client.post(
        "/api/permits/applications/app_synth_001/documents",
        data={"document_type": "construction_plans"},
        files={
            "file": (
                "at03-fictional.txt",
                b"fictional scoped document",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["document_id"]

    sign_in(client, "persona_applicant")
    evaluations = client.get("/api/permits/applications/app_synth_001/evaluations")
    documents = client.get("/api/permits/applications/app_synth_001/documents")
    content = client.get(f"/api/permits/documents/{document_id}/content")
    for response in (evaluations, documents, content):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "permission_denied"

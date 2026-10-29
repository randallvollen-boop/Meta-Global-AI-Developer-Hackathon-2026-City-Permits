"""AUTHZ-001: internal read and preview endpoints refuse an Applicant session."""
# REQUIRES: SEC-01, SEC-02
# The governance, change, registry and source read routes need an internal-view grant.

from __future__ import annotations

import pytest

READS = (
    ("GET", "/api/governance/datasets", None),
    ("GET", "/api/governance/assignments", None),
    ("GET", "/api/governance/responsibility/permits", None),
    ("GET", "/api/changes/chg_missing/impact", None),
    ("POST", "/api/changes/impact/preview", {"target_type": "party", "target_id": "party_cedarline"}),
    ("GET", "/api/registry/crosswalks", None),
    (
        "GET",
        "/api/registry/crosswalks/history?source_system_id=permitting&source_record_id=x",
        None,
    ),
    ("GET", "/api/registry/entities/party_cedarline/trusted-view", None),
    ("GET", "/api/sources/systems", None),
    ("GET", "/api/sources/permitting/applicant_profiles/snapshots", None),
    ("GET", "/api/sources/permitting/applicant_profiles/observations", None),
    ("GET", "/api/sources/permitting/applicant_profiles/quarantine", None),
)


@pytest.mark.parametrize(("method", "path", "body"), READS)
def test_an_applicant_session_is_refused_on_internal_reads(
    audit_client, pick, method: str, path: str, body: dict | None
) -> None:
    pick(audit_client, "persona_applicant")
    response = audit_client.request(method, path, json=body)
    assert response.status_code == 403, (path, response.status_code, response.text)


@pytest.mark.parametrize(
    "path",
    (
        "/api/governance/datasets",
        "/api/changes",
        "/api/registry/crosswalks",
        "/api/sources/systems",
    ),
)
def test_the_data_steward_still_reads_internal_records(audit_client, pick, path: str) -> None:
    pick(audit_client, "persona_data_steward")
    assert audit_client.get(path).status_code == 200


def _request_change(client, target_id: str) -> str:
    response = client.post(
        "/api/changes",
        json={
            "target_type": "application",
            "target_id": target_id,
            "title": "Fictional correction of a submitted description",
            "reason": "the submitted description names the wrong counter",
            "change_kind": "factual",
            "proposed_value": {"project_description": "A corrected fictional description."},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["change_case_id"]


def test_an_applicant_sees_only_the_changes_it_requested(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    steward_case = _request_change(audit_client, "SYN-APP-001")
    pick(audit_client, "persona_applicant")
    own_case = _request_change(audit_client, "SYN-APP-005")
    listed = [row["change_case_id"] for row in audit_client.get("/api/changes").json()["change_cases"]]
    assert own_case in listed
    assert steward_case not in listed
    assert audit_client.get(f"/api/changes/{own_case}").status_code == 200
    assert audit_client.get(f"/api/changes/{steward_case}").status_code == 404

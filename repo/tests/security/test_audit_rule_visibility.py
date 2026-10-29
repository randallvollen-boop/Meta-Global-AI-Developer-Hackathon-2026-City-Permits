"""AUTHZ-004: an unpublished rule version is not disclosed to a non-author."""
# REQUIRES: SEC-01, SEC-02
# Only rule authors read draft, in-review and approved rule versions.

from __future__ import annotations

DRAFT = {
    "rule_id": "CT-3",
    "permit_type_key": "com_ti",
    "title": "Emergency access review",
    "citation": "ACME Code 14-418",
    "field_path": "occupancy_load",
    "operator": "max",
    "limit_value": "60",
    "on_violate": "review",
    "effective_from": "2027-01-01T00:00:00Z",
    "reason": "Fictional demonstration rule.",
}


def _draft_as_steward(client, pick) -> str:
    pick(client, "persona_data_steward")
    response = client.post("/api/rules", json=DRAFT)
    assert response.status_code == 200, response.text
    return response.json()["value"]["row_id"]


def test_a_draft_rule_is_hidden_from_an_applicant(audit_client, pick) -> None:
    row_id = _draft_as_steward(audit_client, pick)
    listed = audit_client.get("/api/rules").json()["versions"]
    assert row_id in [item["row_id"] for item in listed]
    assert audit_client.get(f"/api/rules/{row_id}").status_code == 200

    pick(audit_client, "persona_applicant")
    listed = audit_client.get("/api/rules").json()["versions"]
    assert listed, "published rules stay visible"
    assert row_id not in [item["row_id"] for item in listed]
    assert all(item["status"] in ("published", "retired") for item in listed)
    assert audit_client.get(f"/api/rules/{row_id}").status_code == 404
    # A published version is still readable.
    assert audit_client.get(f"/api/rules/{listed[0]['row_id']}").status_code == 200

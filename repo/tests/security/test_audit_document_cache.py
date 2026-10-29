"""PROTO-001: a stored document download is never cached."""
# REQUIRES: SEC-01, SEC-02
# The binary document response carries Cache-Control: no-store.

from __future__ import annotations


def test_a_document_download_is_not_cacheable(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    stored = audit_client.post(
        "/api/permits/applications/app_synth_001/documents",
        data={"document_type": "construction_plans"},
        files={"file": ("plans.pdf", b"%PDF-1.4 fictional demonstration bytes", "application/pdf")},
    )
    assert stored.status_code == 200, stored.text
    content = audit_client.get(f"/api/permits/documents/{stored.json()['document_id']}/content")
    assert content.status_code == 200
    assert content.headers["cache-control"] == "no-store"

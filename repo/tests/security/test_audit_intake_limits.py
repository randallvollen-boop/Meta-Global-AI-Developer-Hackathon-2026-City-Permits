"""DOS-001: source intake bounds the batch size and the payload size."""
# REQUIRES: SEC-01, SEC-02
# One intake request carries a bounded number of records, each of bounded size.

from __future__ import annotations

PATH = "/api/sources/permitting/applicant_profiles/intake"


def _record(index: int, payload: dict | None = None) -> dict:
    return {
        "source_record_id": f"PER-LIMIT-{index:05d}",
        "source_record_version": "1",
        "payload": payload or {},
        "source_updated_at": "2026-10-20T08:00:00Z",
    }


def test_an_oversized_batch_is_refused(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    records = [_record(index) for index in range(2000)]
    response = audit_client.post(PATH, json={"records": records})
    assert response.status_code == 422, response.text


def test_an_oversized_record_payload_is_refused(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    big = {"note": "x" * (200_000)}
    response = audit_client.post(PATH, json={"records": [_record(1, big)]})
    assert response.status_code == 422, response.text
    write = audit_client.post(
        "/api/sources/permitting/records",
        json={"dataset_key": "applicant_profiles", "record_id": "PER-1", "payload": big},
    )
    assert write.status_code == 422, write.text


def test_a_normal_batch_is_still_taken(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    response = audit_client.post(PATH, json={"records": [_record(1), _record(2)]})
    assert response.status_code == 200, response.text

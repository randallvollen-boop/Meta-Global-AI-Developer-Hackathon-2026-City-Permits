"""API-001: submitting an application cannot name a record outside the actor's scope."""
# REQUIRES: SEC-01, SEC-02
# Every identity a scoped submission names must be inside the record scope.

from __future__ import annotations


def _submit(client, **identity):
    return client.post(
        "/api/permits/applications",
        json={"permit_type_key": "com_ti", "facts": {"project_description": "Fictional."}, **identity},
    )


def test_an_applicant_cannot_submit_into_another_party_through_a_second_identity(
    audit_client, pick
) -> None:
    pick(audit_client, "persona_applicant")
    # SYN-APP-005 is in scope; the party is not.
    response = _submit(
        audit_client, source_application_number="SYN-APP-005X", applicant_party_id="party_cedarline"
    )
    assert response.status_code == 403, response.text
    response = _submit(
        audit_client, source_application_number="SYN-APP-005", applicant_party_id="party_cedarline"
    )
    assert response.status_code == 403, response.text
    response = _submit(
        audit_client, source_application_number="SYN-APP-999", applicant_party_id="party_applicant_1"
    )
    assert response.status_code == 403, response.text


def test_an_applicant_can_still_submit_inside_the_scope(audit_client, pick) -> None:
    pick(audit_client, "persona_applicant")
    response = _submit(audit_client, applicant_party_id="party_applicant_1")
    assert response.status_code == 200, response.text


def test_the_data_steward_submits_for_any_party(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    response = _submit(audit_client, applicant_party_id="party_cedarline")
    assert response.status_code == 200, response.text

"""The applicant is told of each decision, with no email sent."""

from __future__ import annotations

import smtplib
import socket

import pytest
from fastapi.testclient import TestClient

from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory
from acme_city.permits.service import PermitService

from test_lifecycle_actions import (  # noqa: F401  (fixtures and helpers)
    application_version,
    choose,
    client,
    environment,
    post,
)

DISCLAIMER = "Email notice recorded for the applicant (the demonstration sends no email)."


def _evaluation_version(environment, application_id: str) -> int:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = PermitService(session).current_evaluation(application_id)
            assert row is not None
            return row.version
    finally:
        factory.dispose()


def _ask(client: TestClient, environment, application_id: str, reason: str) -> dict:
    choose(client, "persona_permit_reviewer")
    evaluated = post(
        client,
        "permit.evaluate",
        {"application_id": application_id},
        f"/permits/{application_id}",
    )
    assert evaluated["status"] == "accepted", evaluated
    return post(
        client,
        "permit.decide",
        {
            "application_id": application_id,
            "outcome": "information_requested",
            "reason": reason,
            "expected_application_version": str(application_version(environment, application_id)),
            "expected_evaluation_version": str(_evaluation_version(environment, application_id)),
        },
        f"/permits/{application_id}",
    )


@pytest.fixture()
def no_outbound(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("an outbound call was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(smtplib.SMTP, "sendmail", refuse)
    monkeypatch.setattr(smtplib.SMTP, "send_message", refuse)


def test_a_decision_creates_a_notice_for_its_applicant_only(
    client: TestClient, environment, no_outbound
) -> None:
    result = _ask(client, environment, "app_d05", "Please send the site plan with the setback.")
    assert result["status"] == "accepted", result
    assert DISCLAIMER in result["message"], result

    # The reviewer's workspace lists the notice, with the disclaimer once.
    workspace = client.get("/permits/app_d05").text
    assert 'data-testid="applicant-notices"' in workspace
    assert "Applicant notices" in workspace
    assert "needs more information" in workspace
    assert "The demonstration sends no email." in workspace

    # The applicant of that case reads it on the tracker.
    choose(client, "persona_applicant")
    tracker = client.get("/apply/track", params={"ref": "SYN-APP-005"}).text
    assert "Messages from the City" in tracker
    assert 'data-testid="city-notices"' in tracker
    assert "Please send the site plan with the setback." in tracker
    assert "The City would also send this by email. The demonstration sends no email." in tracker
    assert "needs more information" in client.get("/permits/app_d05").text


def test_another_applicant_never_sees_the_notice(
    client: TestClient, environment, no_outbound
) -> None:
    result = _ask(client, environment, "app_synth_001", "A private reviewer rationale 7731.")
    assert result["status"] == "accepted", result
    choose(client, "persona_applicant")
    # SYN-APP-001 is not this applicant's case: no tracker, no workspace.
    other = client.get("/apply/track", params={"ref": "SYN-APP-001"}).text
    assert "A private reviewer rationale 7731." not in other
    assert client.get("/permits/app_synth_001").status_code == 404
    own = client.get("/apply/track", params={"ref": "SYN-APP-005"}).text
    assert "A private reviewer rationale 7731." not in own
    assert 'data-testid="city-notices"' not in own


def test_an_issued_permit_yields_an_issued_notice(environment) -> None:
    from acme_city.permits.notices import applicant_notices

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, "app_d07")
            number = session.query(permit.Permit).filter_by(application_id="app_d07").one().permit_number
            subjects = [item["subject"] for item in applicant_notices(session, application)]
            assert f"Your permit {number} is issued" in subjects
    finally:
        factory.dispose()

"""LOGIC-002: permit decisions need both expected versions and commit atomically."""
# REQUIRES: SEC-01, SEC-02
# A decision names the versions it was made against; two decisions on one version cannot both commit.

from __future__ import annotations

import pytest
from sqlalchemy import select

from acme_city.core.errors import ConflictError
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory
from acme_city.permits.decisions import PermitDecisionService
from acme_city.auth.context import ActorContext


def _reviewer_state(settings):
    """Evaluate a fictional case and return (application id, application version, evaluation version)."""
    from acme_city.auth.context import ActorContext
    from acme_city.permits.service import PermitService

    reviewer = ActorContext(actor_id="persona_permit_reviewer")
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            evaluation = service.evaluate("app_synth_001", reviewer)
            application = service.load_application("app_synth_001")
            state = (application.id, application.version, evaluation.version)
            session.commit()
            return state
    finally:
        factory.dispose()


def test_a_decision_without_expected_versions_is_refused(audit_client, audit_settings, pick) -> None:
    app_id, app_version, eval_version = _reviewer_state(audit_settings)
    pick(audit_client, "persona_permit_reviewer")
    for body in (
        {"outcome": "information_requested", "reason": "Need a site plan."},
        {"outcome": "information_requested", "reason": "Need a site plan.",
         "expected_application_version": app_version},
        {"outcome": "information_requested", "reason": "Need a site plan.",
         "expected_evaluation_version": eval_version},
    ):
        response = audit_client.post(f"/api/permits/applications/{app_id}/decisions", json=body)
        assert response.status_code == 422, (body, response.status_code, response.text)


def test_a_second_decision_on_the_same_version_cannot_commit(audit_settings) -> None:
    app_id, app_version, _ = _reviewer_state(audit_settings)
    factory = SessionFactory(audit_settings.database_url)
    try:
        stale_session = factory()
        stale = stale_session.get(permit.Application, app_id)
        assert stale.version == app_version
        # A concurrent decision commits first and advances the version.
        with factory() as other:
            other.execute(
                permit.Application.__table__.update()
                .where(permit.Application.id == app_id)
                .values(version=app_version + 1)
            )
            other.commit()
        evaluation = stale_session.execute(
            select(permit.Evaluation).where(permit.Evaluation.application_id == app_id)
        ).scalars().first()
        service = PermitDecisionService(stale_session)
        with pytest.raises(ConflictError):
            service._record(  # noqa: SLF001 - the commit step is the unit under test
                application=stale,
                evaluation=evaluation,
                outcome="information_requested",
                reason="Need a site plan.",
                actor=ActorContext(actor_id="persona_permit_reviewer"),
                decision_type="review",
            )
        stale_session.rollback()
        stale_session.close()
    finally:
        factory.dispose()


def test_a_decision_with_both_versions_is_recorded_once(audit_client, audit_settings, pick) -> None:
    app_id, app_version, eval_version = _reviewer_state(audit_settings)
    pick(audit_client, "persona_permit_reviewer")
    body = {
        "outcome": "information_requested",
        "reason": "Need a site plan.",
        "expected_application_version": app_version,
        "expected_evaluation_version": eval_version,
    }
    first = audit_client.post(f"/api/permits/applications/{app_id}/decisions", json=body)
    assert first.status_code == 200, first.text
    again = audit_client.post(f"/api/permits/applications/{app_id}/decisions", json=body)
    assert again.status_code in (409, 422), again.text

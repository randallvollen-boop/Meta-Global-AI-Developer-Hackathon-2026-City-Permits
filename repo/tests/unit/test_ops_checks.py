"""The eight read-only invariant checks of the checks screen (S14).

Each check has a passing fixture and a failing fixture.  The historical seed
(D07: an approved decision and an issued permit inserted by the reset without
a decision or issuance audit event) is reported as not applicable, never as a
pass and never as a failure, and no audit event is made up for it.
"""
# REQUIRES: PER-04, SEC-02, SEC-03, GOV-04

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.ids import new_id
from acme_city.ops import checks
from acme_city.ops.checks import FAIL, NOT_APPLICABLE, PASS, ChecksService, run_checks
from acme_city.persistence.models import audit, finance, gis, governance, permit
from acme_city.persistence.session import SessionFactory, transaction

from ops_helpers import (
    ADMIN,
    add_audit,
    add_decision,
    add_permit,
    build_template,
    context_for,
    copy_of,
)


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    return build_template(tmp_path_factory.mktemp("ops-checks"))


@pytest.fixture()
def session(template, tmp_path):
    settings = copy_of(template, tmp_path)
    factory = SessionFactory(settings.database_url)
    with transaction(factory) as open_session:
        yield open_session
    factory.dispose()


def result_of(session, check):
    return check(session)


# ------------------------------------------------------------ the baseline


def test_the_fresh_database_has_no_failing_check_and_reports_the_seed(session) -> None:
    results = {item.check_id: item for item in run_checks(session)}
    assert [item.status for item in results.values() if item.status == FAIL] == []
    # D07 is a historical seed: reported as such, never as a pass.
    audited = results["audited"]
    assert audited.status == NOT_APPLICABLE
    assert "not applicable (historical seed)" in audited.reason
    approved = results["issuances_approved"]
    assert approved.status == NOT_APPLICABLE
    assert "not applicable (historical seed)" in approved.reason
    assert audited.passed == 0 and approved.passed == 0


def test_no_event_is_made_up_for_the_seed(session) -> None:
    before = session.execute(select(func.count()).select_from(audit.AuditEvent)).scalar_one()
    run_checks(session)
    after = session.execute(select(func.count()).select_from(audit.AuditEvent)).scalar_one()
    assert before == after  # running the checks itself writes nothing; the service writes one event
    assert session.execute(
        select(func.count()).select_from(audit.AuditEvent).where(audit.AuditEvent.target_id == "decision_d07")
    ).scalar_one() == 0


def test_the_baseline_names_the_d07_rows_from_the_fixture_bundle() -> None:
    baseline = checks.fixture_baseline()
    assert "decision_d07" in baseline.decision_ids
    assert "permit_d07" in baseline.permit_ids


# ------------------------------------------------------- 1 personas


def test_personas_pass_with_the_four(session) -> None:
    result = checks.check_personas(session)
    assert result.status == PASS and result.passed == 4


def test_personas_fail_with_a_fifth_selectable_actor(session) -> None:
    session.add(governance.Actor(id=new_id("actor"), actor_id="persona_extra", label="Extra Persona", selectable=True))
    session.flush()
    result = checks.check_personas(session)
    assert result.status == FAIL and "Extra Persona" in result.reason


# ------------------------------------------------- 2 agents decided nothing


def test_agents_pass_when_only_people_decided(session) -> None:
    add_decision(session)
    result = checks.check_agents_decided_nothing(session)
    assert result.status == PASS and result.failed == 0


def test_agents_fail_when_an_agent_identity_decided(session) -> None:
    decision = add_decision(session, decided_by="service_agent_adjudication")
    result = checks.check_agents_decided_nothing(session)
    assert result.status == FAIL
    assert f"decision {decision.id}" in result.offenders


def test_agents_fail_when_an_agent_identity_issued(session) -> None:
    decision = add_decision(session)
    issued = add_permit(session, decision=decision, issued_by="service_agent_intake")
    result = checks.check_agents_decided_nothing(session)
    assert result.status == FAIL and f"permit {issued.id}" in result.offenders


# ---------------------------------------------------------- 3 audited


def test_audited_passes_for_a_post_seed_decision_with_an_event(session) -> None:
    decision = add_decision(session)
    add_audit(session, action="permit.decide", target_type="decision", target_id=decision.id)
    result = checks.check_audited(session)
    assert result.status == PASS and result.passed == 1
    assert result.exempt == 2  # the two D07 rows stay exceptions, not passes


def test_audited_fails_for_a_post_seed_decision_without_an_event(session) -> None:
    decision = add_decision(session)
    result = checks.check_audited(session)
    assert result.status == FAIL and f"decision {decision.id}" in result.offenders


def test_audited_fails_for_a_post_seed_issuance_without_an_event(session) -> None:
    decision = add_decision(session)
    add_audit(session, action="permit.decide", target_type="decision", target_id=decision.id)
    issued = add_permit(session, decision=decision)
    result = checks.check_audited(session)
    assert result.status == FAIL and f"permit {issued.id}" in result.offenders


def test_audited_does_not_accept_a_denied_event(session) -> None:
    decision = add_decision(session)
    add_audit(session, action="permit.decide", target_type="decision", target_id=decision.id)
    event = session.execute(select(audit.AuditEvent).where(audit.AuditEvent.target_id == decision.id)).scalar_one()
    event.outcome = "denied"
    event.denial_reason = "refused"
    session.flush()
    assert checks.check_audited(session).status == FAIL


# --------------------------------------------- 4 administrator powers


def test_administrator_passes_with_the_seeded_grants(session) -> None:
    result = checks.check_administrator_powers(session)
    assert result.status == PASS


@pytest.mark.parametrize("permission", ["permit.decide", "permit.issue", "permit.case.return", "permit.finding.waive"])
def test_administrator_fails_with_a_forbidden_grant(session, permission: str) -> None:
    session.add(
        governance.ActorGrant(
            id=new_id("act"),
            actor_id=ADMIN,
            permission_id=permission,
            domain_id=None,
            record_scope=[],
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            source="test",
        )
    )
    session.flush()
    result = checks.check_administrator_powers(session)
    assert result.status == FAIL and permission in result.reason


# ------------------------------- 5 issuances: approved and parcel-confirmed


def _match(session, application_id: str, *, confirmed: bool) -> None:
    session.add(
        gis.ApplicationParcelMatch(
            id=new_id("pmatch"),
            correlation_id=new_id("corr"),
            application_id=application_id,
            submitted_text="a fictional address",
            link_state="approved",
            confirmed_at=datetime(2026, 10, 28, 11, 0, tzinfo=UTC) if confirmed else None,
            confirmed_by="persona_permit_reviewer" if confirmed else None,
        )
    )
    session.flush()


def test_issuance_passes_with_an_approved_confirmed_decision(session) -> None:
    decision = add_decision(session)
    add_permit(session, decision=decision)
    _match(session, decision.application_id, confirmed=True)
    result = checks.check_issuances_approved(session)
    assert result.status == PASS and result.passed == 1 and result.failed == 0


def test_issuance_fails_when_the_decision_is_not_an_approval(session) -> None:
    decision = add_decision(session, outcome="denied")
    issued = add_permit(session, decision=decision)
    result = checks.check_issuances_approved(session)
    assert result.status == FAIL and any(issued.id in item for item in result.offenders)


def test_issuance_fails_when_the_matched_parcel_is_not_confirmed(session) -> None:
    decision = add_decision(session)
    issued = add_permit(session, decision=decision)
    _match(session, decision.application_id, confirmed=False)
    result = checks.check_issuances_approved(session)
    assert result.status == FAIL and any("parcel not confirmed" in item and issued.id in item for item in result.offenders)


def test_an_issuance_with_no_parcel_match_is_an_exception_and_not_a_pass(session) -> None:
    decision = add_decision(session)
    add_permit(session, decision=decision)
    result = checks.check_issuances_approved(session)
    assert result.passed == 0 and result.exempt == 2  # D07 and this one
    assert result.status == NOT_APPLICABLE  # an exception is never counted as a pass


# ------------------------------------------------------- 6 fee totals


def test_fee_totals_pass_on_the_seeded_assessments(session) -> None:
    result = checks.check_fee_totals(session)
    assert result.status == PASS and result.passed >= 1


def test_fee_totals_fail_when_a_stored_total_drifts(session) -> None:
    assessment = session.execute(select(finance.Assessment)).scalars().first()
    assessment.assessed_total_cents += 100
    session.flush()
    result = checks.check_fee_totals(session)
    assert result.status == FAIL and any(assessment.id in item for item in result.offenders)


# ------------------------------------------- 7 archived not in an active queue


def _archive(session, application_id: str, *, status: str) -> permit.Application:
    row = session.get(permit.Application, application_id)
    row.archived_at = datetime(2026, 10, 20, tzinfo=UTC)
    row.status_before_archive = "submitted"
    row.status = status
    session.flush()
    return row


def test_archived_passes_when_archived_cases_are_archived(session) -> None:
    row = _archive(session, "app_d02", status="archived")
    result = checks.check_archived_not_active(session)
    assert result.status == PASS and result.failed == 0 and row.status == "archived"


def test_archived_fails_when_an_archived_case_is_active_without_a_restore(session) -> None:
    row = _archive(session, "app_d02", status="submitted")
    result = checks.check_archived_not_active(session)
    assert result.status == FAIL and any(row.id in item for item in result.offenders)


def test_archived_passes_when_a_restore_is_on_record(session) -> None:
    row = _archive(session, "app_d02", status="submitted")
    session.add(
        permit.ApplicationAction(
            id=new_id("act"),
            correlation_id=new_id("corr"),
            application_id=row.id,
            action="restore",
            actor_id=ADMIN,
            occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
        )
    )
    session.flush()
    assert checks.check_archived_not_active(session).status == PASS


# ------------------------------------------- 8 internal comments private


def _comment(session, application_id: str, body: str, visibility: str) -> None:
    session.add(
        permit.ApplicationComment(
            id=new_id("comment"),
            correlation_id=new_id("corr"),
            application_id=application_id,
            body=body,
            visibility=visibility,
            author_actor_id="persona_permit_reviewer",
            version=1,
        )
    )
    session.flush()


def test_internal_comments_pass_when_they_stay_internal(session) -> None:
    _comment(session, "app_d02", "internal: check the setback twice", "internal")
    _comment(session, "app_d02", "Please send a site plan.", "applicant")
    result = checks.check_internal_comments(session)
    assert result.status == PASS and result.passed == 1


def test_internal_comments_fail_when_the_text_is_repeated_for_the_applicant(session) -> None:
    _comment(session, "app_d02", "internal: check the setback twice", "internal")
    _comment(session, "app_d02", "Internal: Check the setback twice", "applicant")
    result = checks.check_internal_comments(session)
    assert result.status == FAIL and "repeated as an applicant-visible comment" in result.reason


def test_internal_comments_fail_when_the_applicant_reader_returns_one(session, monkeypatch) -> None:
    _comment(session, "app_d02", "internal: a private note", "internal")
    internal = session.execute(
        select(permit.ApplicationComment).where(permit.ApplicationComment.visibility == "internal")
    ).scalar_one()
    from acme_city.permits import comments

    monkeypatch.setattr(comments, "comments_for", lambda *a, **k: [internal])
    result = checks.check_internal_comments(session)
    assert result.status == FAIL and "is read by an applicant" in result.reason


def test_internal_comments_are_not_applicable_when_none_exist(session) -> None:
    assert checks.check_internal_comments(session).status == NOT_APPLICABLE


# ------------------------------------------------------------ the service


def test_a_run_writes_one_canonical_event_with_the_counts_and_no_text(session) -> None:
    admin = context_for(session, ADMIN)
    service = ChecksService(session)
    assert service.runs_so_far(admin) == 0
    run_id, results = service.run(admin, expected_version=0)
    events = session.execute(select(audit.AuditEvent).where(audit.AuditEvent.action == "checks.run")).scalars().all()
    assert len(events) == 1 and events[0].target_id == run_id
    meta = events[0].metadata_json
    assert sum(meta["counts"].values()) == len(results) == 8
    assert service.runs_so_far(admin) == 1
    recorded = service.recorded(admin)
    assert recorded["run_id"] == run_id and len(recorded["results"]) == 8


def test_a_run_needs_a_current_expected_version(session) -> None:
    admin = context_for(session, ADMIN)
    service = ChecksService(session)
    with pytest.raises(ValidationError):
        service.run(admin, expected_version=None)
    service.run(admin, expected_version=0)
    with pytest.raises(ValidationError):
        service.run(admin, expected_version=0)  # stale: a run is recorded now


@pytest.mark.parametrize("actor_id", ["persona_applicant", "persona_data_steward", "persona_permit_reviewer"])
def test_a_run_needs_the_grant(session, actor_id: str) -> None:
    with pytest.raises(PermissionDeniedError):
        ChecksService(session).run(context_for(session, actor_id), expected_version=0)

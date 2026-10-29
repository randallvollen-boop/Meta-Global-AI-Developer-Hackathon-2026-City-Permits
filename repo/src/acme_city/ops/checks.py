"""The checks screen (S14): a fixed list of read-only invariant checks.

The checks run in process: no subprocess, no test runner and no network.  Each
check reads stored rows and returns one of three results:

* ``pass``: at least one record was inspected and every one held;
* ``fail``: a record broke the invariant, and its identifier is listed;
* ``not_applicable``: nothing inspectable exists, for example because every
  record is part of the historical seed.

The historical seed is a fixed baseline, not a guess.  The fixture bundle
inserts one approved decision and one issued permit for D07 (``app_d07``)
without a decision or an issuance audit event, and phase 2 exempts seeded
cases from parcel matching.  Those records are reported as **not applicable
(historical seed)**.  No event is ever fabricated for them, and an exception
is never counted as a pass.  A record that is *not* in the fixture bundle and
has no audit record is a failure.

One canonical ``checks.run`` audit event is written per run.  It carries the
counts and the identifiers of the offending records, never any text.
"""
# REQUIRES: PER-04, SEC-02, SEC-03, GOV-04
# Eight read-only invariant checks run in process; the historical seed is
# reported as not applicable and never as a pass; a run writes one audit event.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.ops.audit_log import identity_sets
from acme_city.persistence.models import audit, finance, governance, permit

PERMISSION_RUN = "ops.checks.run"
ACTION_RUN = "checks.run"

PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"

#: The wording of the not-applicable result for the historical seed.
SEED_WORDS = "not applicable (historical seed)"

#: The five personas the interface may select, in selector order.
PERSONAS: tuple[str, ...] = (
    "Applicant",
    "Data Steward",
    "Permit Reviewer",
    "City Administrator",
    "Agent Operator",
)

#: The grants the City Administrator never holds.
FORBIDDEN_FOR_ADMINISTRATOR: tuple[str, ...] = (
    "permit.decide",
    "permit.issue",
    "permit.case.return",
    "permit.finding.waive",
)

#: The audit actions a decision and an issuance leave.
DECISION_ACTIONS: tuple[str, ...] = ("permit.decide", "permit.reconfirm")
ISSUANCE_ACTIONS: tuple[str, ...] = ("permit.issue",)

#: The statuses of the active queues.
ACTIVE_QUEUE_STATUSES: frozenset[str] = frozenset(
    {"submitted", "needs_information", "ready_for_review", "under_review", "revisions_requested"}
)


@dataclass(frozen=True)
class CheckResult:
    """The result of one check."""

    check_id: str
    title: str
    status: str
    reason: str
    passed: int = 0
    failed: int = 0
    exempt: int = 0
    offenders: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status,
            "reason": self.reason,
            "passed": self.passed,
            "failed": self.failed,
            "exempt": self.exempt,
            "offenders": list(self.offenders),
        }


@dataclass(frozen=True)
class Baseline:
    """The historical seed: the identifiers the fixture bundle inserted."""

    decision_ids: frozenset[str]
    permit_ids: frozenset[str]


@lru_cache(maxsize=1)
def fixture_baseline() -> Baseline:
    """Return the decisions and permits of the committed fixture bundle."""
    from acme_city.fixtures.loader import FixtureBundle

    population = FixtureBundle.load().base_population
    return Baseline(
        decision_ids=frozenset(row.decision_id for row in population.decisions),
        permit_ids=frozenset(row.permit_id for row in population.permits),
    )


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _result(
    check_id: str,
    title: str,
    *,
    passed: int,
    offenders: list[str],
    exempt: int = 0,
    seed: int = 0,
    unit: str,
    detail: str = "",
) -> CheckResult:
    """Build a result from the counts of one check.

    ``seed`` counts records of the historical seed; ``exempt`` counts records
    inspected but exempted by a stated rule.  Neither counts as a pass.
    """
    if offenders:
        return CheckResult(
            check_id,
            title,
            FAIL,
            f"{_plural(len(offenders), unit)} broke the rule: {', '.join(offenders[:5])}"
            + (" and more" if len(offenders) > 5 else "")
            + ".",
            passed=passed,
            failed=len(offenders),
            exempt=exempt + seed,
            offenders=tuple(offenders),
        )
    notes = []
    if seed:
        notes.append(f"{_plural(seed, unit)} {SEED_WORDS}")
    if exempt:
        notes.append(f"{_plural(exempt, unit)} exempted by a stated rule and not counted as passed")
    if detail:
        notes.append(detail)
    suffix = ("; " + "; ".join(notes)) if notes else ""
    if passed:
        return CheckResult(
            check_id,
            title,
            PASS,
            f"{_plural(passed, unit)} checked and all hold{suffix}.",
            passed=passed,
            exempt=exempt + seed,
        )
    return CheckResult(
        check_id,
        title,
        NOT_APPLICABLE,
        (f"nothing to check{suffix}" if (seed or exempt) else f"no {unit} exists yet to check")
        + ".",
        exempt=exempt + seed,
    )


# --------------------------------------------------------------------- checks


def check_personas(session: Session) -> CheckResult:
    """Exactly five personas are selectable, and they are the five named ones."""
    title = f"Exactly {len(PERSONAS)} selectable personas"
    labels = sorted(
        row[0]
        for row in session.execute(
            select(governance.Actor.label).where(governance.Actor.selectable.is_(True))
        ).all()
    )
    if labels == sorted(PERSONAS):
        return CheckResult("personas", title, PASS, "the selector offers " + ", ".join(PERSONAS) + ".", passed=len(PERSONAS))
    return CheckResult(
        "personas",
        title,
        FAIL,
        f"{len(labels)} selectable actors found ({', '.join(labels) or 'none'}); "
        f"expected exactly {', '.join(PERSONAS)}.",
        failed=1,
        offenders=tuple(labels),
    )


def check_agents_decided_nothing(session: Session) -> CheckResult:
    """No agent identity appears as the decider or issuer of anything."""
    title = "No agent identity decided anything"
    _, agent_ids = identity_sets(session)
    decisions = list(session.execute(select(permit.Decision)).scalars())
    permits = list(session.execute(select(permit.Permit)).scalars())
    offenders = [f"decision {d.id}" for d in decisions if d.decided_by_actor_id in agent_ids]
    offenders += [f"permit {p.id}" for p in permits if p.issued_by_actor_id in agent_ids]
    offenders += [
        f"audit {e.id}"
        for e in session.execute(
            select(audit.AuditEvent).where(
                audit.AuditEvent.action.in_(DECISION_ACTIONS + ISSUANCE_ACTIONS),
                audit.AuditEvent.outcome == "accepted",
            )
        ).scalars()
        if e.actor_id in agent_ids
    ]
    offenders += [
        f"recommendation {r.id}"
        for r in session.execute(select(permit.Recommendation)).scalars()
        if r.confirmed_by in agent_ids
    ]
    inspected = len(decisions) + len(permits)
    return _result(
        "agents_decided_nothing",
        title,
        passed=inspected if not offenders else 0,
        offenders=offenders,
        unit="decision/issuance record",
        detail=f"{len(agent_ids)} agent identities known",
    )


def _audited(session: Session, actions: tuple[str, ...], target_type: str) -> set[str]:
    return {
        row[0]
        for row in session.execute(
            select(audit.AuditEvent.target_id).where(
                audit.AuditEvent.action.in_(actions),
                audit.AuditEvent.target_type == target_type,
                audit.AuditEvent.outcome == "accepted",
            )
        ).all()
    }


def check_audited(session: Session) -> CheckResult:
    """Every post-seed decision and issuance has an accepted audit record."""
    title = "Every post-seed decision and issuance has an audit record"
    baseline = fixture_baseline()
    audited_decisions = _audited(session, DECISION_ACTIONS, "decision")
    audited_permits = _audited(session, ISSUANCE_ACTIONS, "permit")
    passed = seed = synthetic = 0
    offenders: list[str] = []
    for decision in session.execute(select(permit.Decision)).scalars():
        if decision.id in baseline.decision_ids:
            seed += 1
        elif decision.synthetic:
            synthetic += 1
        elif decision.id in audited_decisions:
            passed += 1
        else:
            offenders.append(f"decision {decision.id}")
    for issued in session.execute(select(permit.Permit)).scalars():
        if issued.id in baseline.permit_ids:
            seed += 1
        elif issued.synthetic:
            synthetic += 1
        elif issued.id in audited_permits:
            passed += 1
        else:
            offenders.append(f"permit {issued.id}")
    return _result(
        "audited",
        title,
        passed=passed,
        offenders=offenders,
        seed=seed,
        unit="decision/issuance record",
        detail=f"{synthetic} synthetic history rows are not audited acts" if synthetic else "",
    )


def check_administrator_powers(session: Session) -> CheckResult:
    """The City Administrator holds none of decide, issue, return or waive."""
    title = "The City Administrator holds none of decide, issue, return, waive"
    now = utc_now()
    admins = {
        row[0]
        for row in session.execute(
            select(governance.Actor.actor_id).where(
                (governance.Actor.actor_id == "persona_city_administrator")
                | (governance.Actor.persona_role == "City Administrator")
            )
        ).all()
    }
    held: list[str] = []
    for grant in session.execute(
        select(governance.ActorGrant).where(
            governance.ActorGrant.actor_id.in_(admins or {""}),
            governance.ActorGrant.permission_id.in_(FORBIDDEN_FOR_ADMINISTRATOR),
        )
    ).scalars():
        if grant.effective_to is None or grant.effective_to > now:
            held.append(f"{grant.actor_id} holds {grant.permission_id}")
    if not admins:
        return CheckResult(
            "administrator_powers", title, NOT_APPLICABLE, "no City Administrator exists yet."
        )
    if held:
        return CheckResult(
            "administrator_powers",
            title,
            FAIL,
            f"{_plural(len(held), 'forbidden grant')} found: {'; '.join(held)}.",
            failed=len(held),
            offenders=tuple(held),
        )
    return CheckResult(
        "administrator_powers",
        title,
        PASS,
        f"{_plural(len(admins), 'administrator identity')} checked against "
        f"{', '.join(FORBIDDEN_FOR_ADMINISTRATOR)}; none is held.",
        passed=len(admins),
    )


def check_issuances_approved(session: Session) -> CheckResult:
    """Every post-seed issuance rests on an approved, parcel-confirmed decision."""
    from acme_city.gis.matching import ParcelMatchService

    title = "Every post-seed issuance has an approved, parcel-confirmed decision"
    baseline = fixture_baseline()
    matcher = ParcelMatchService(session)
    passed = exempt = seed = 0
    offenders: list[str] = []
    for issued in session.execute(select(permit.Permit)).scalars():
        if issued.id in baseline.permit_ids:
            seed += 1
            continue
        if issued.synthetic:
            continue
        decision = session.get(permit.Decision, issued.decision_id)
        if decision is None or decision.outcome != "approved" or decision.application_id != issued.application_id:
            offenders.append(f"permit {issued.id}: no approved decision")
            continue
        if matcher.for_application(issued.application_id) is None:
            # Phase 2: a case with no parcel match (a seeded case) is exempt
            # from parcel confirmation.  It is an exception, never a pass.
            exempt += 1
            continue
        if matcher.blocker_states(issued.application_id):
            offenders.append(f"permit {issued.id}: parcel not confirmed")
            continue
        passed += 1
    return _result(
        "issuances_approved",
        title,
        passed=passed,
        offenders=offenders,
        exempt=exempt,
        seed=seed,
        unit="issuance",
    )


def check_fee_totals(session: Session) -> CheckResult:
    """Every assessment's stored total equals the sum of its lines."""
    title = "Fee totals recompute to stored amounts"
    sums = {
        row[0]: int(row[1] or 0)
        for row in session.execute(
            select(finance.AssessmentLine.assessment_id, func.sum(finance.AssessmentLine.amount_cents))
            .group_by(finance.AssessmentLine.assessment_id)
        ).all()
    }
    offenders: list[str] = []
    checked = 0
    for assessment in session.execute(select(finance.Assessment)).scalars():
        checked += 1
        recomputed = sums.get(assessment.id, 0)
        if recomputed != assessment.assessed_total_cents:
            offenders.append(
                f"assessment {assessment.id}: stored {assessment.assessed_total_cents}, "
                f"recomputed {recomputed}"
            )
    return _result(
        "fee_totals",
        title,
        passed=checked - len(offenders),
        offenders=offenders,
        unit="assessment",
    )


def check_archived_not_active(session: Session) -> CheckResult:
    """No archived case sits in an active queue.

    The saved views define their membership by status.  An archived case is
    in an active queue only when its status was moved out of ``archived``
    without a recorded restore, so that is what the check looks for.
    """
    from acme_city.permits.queues import INTAKE_TABS

    title = "No archived case in an active queue"
    offenders: list[str] = []
    for tab in INTAKE_TABS:
        if tab["key"] != "archived" and "archived" in tab["statuses"]:
            offenders.append(f"queue view {tab['key']} lists the archived status")
    archived_ever = list(
        session.execute(
            select(permit.Application).where(permit.Application.archived_at.is_not(None))
        ).scalars()
    )
    restored = {
        row[0]
        for row in session.execute(
            select(permit.ApplicationAction.application_id).where(
                permit.ApplicationAction.action == "restore"
            )
        ).all()
    }
    for application in archived_ever:
        if application.status in ACTIVE_QUEUE_STATUSES and application.id not in restored:
            offenders.append(f"application {application.id} is active with no restore on record")
    return _result(
        "archived_not_active",
        title,
        passed=len(archived_ever) if archived_ever else 0,
        offenders=offenders,
        unit="archived case",
    )


def check_internal_comments(session: Session) -> CheckResult:
    """No internal comment is readable by an applicant."""
    from acme_city.permits.comments import comments_for

    title = "No internal comment is applicant-visible"
    probe = ActorContext(actor_id="check_applicant_probe")
    internal = list(
        session.execute(
            select(permit.ApplicationComment).where(permit.ApplicationComment.visibility == "internal")
        ).scalars()
    )
    offenders: list[str] = []
    for application_id in sorted({row.application_id for row in internal}):
        shown = {row.id for row in comments_for(session, application_id, probe)}
        leaked = [row.id for row in internal if row.application_id == application_id and row.id in shown]
        offenders += [f"comment {item} is read by an applicant" for item in leaked]
        visible_bodies = {
            row.body.strip().lower()
            for row in session.execute(
                select(permit.ApplicationComment).where(
                    permit.ApplicationComment.application_id == application_id,
                    permit.ApplicationComment.visibility == "applicant",
                )
            ).scalars()
        }
        offenders += [
            f"comment {row.id} is repeated as an applicant-visible comment"
            for row in internal
            if row.application_id == application_id and row.body.strip().lower() in visible_bodies
        ]
    return _result(
        "internal_comments",
        title,
        passed=len(internal) if not offenders else len(internal) - len(offenders),
        offenders=offenders,
        unit="internal comment",
    )


#: The fixed list, in the order the screen shows it.
CHECKS = (
    check_personas,
    check_agents_decided_nothing,
    check_audited,
    check_administrator_powers,
    check_issuances_approved,
    check_fee_totals,
    check_archived_not_active,
    check_internal_comments,
)


def run_checks(session: Session) -> list[CheckResult]:
    """Run every check, in process and read only."""
    return [check(session) for check in CHECKS]


# -------------------------------------------------------------------- service


class ChecksService:
    """Runs the checks and records the run."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    def _authorize(self, actor: ActorContext) -> None:
        self._permissions.authorize(actor, PERMISSION_RUN, ResourceContext(domain_id=None))

    def runs_so_far(self, actor: ActorContext) -> int:
        """Return the number of recorded runs, which is the version of the screen."""
        self._authorize(actor)
        return int(
            self._session.execute(
                select(func.count()).select_from(audit.AuditEvent).where(
                    audit.AuditEvent.action == ACTION_RUN
                )
            ).scalar_one()
            or 0
        )

    def run(self, actor: ActorContext, *, expected_version: int | None) -> tuple[str, list[CheckResult]]:
        """Run the checks and write the one canonical ``checks.run`` event."""
        self._authorize(actor)
        if expected_version is None:
            raise ValidationError("an expected version is required to run the checks")
        current = self.runs_so_far(actor)
        if expected_version != current:
            raise ValidationError(
                "the checks were run since the screen was read; read it again and retry"
            )
        results = run_checks(self._session)
        run_id = new_id("checkrun")
        counts = {
            status: sum(1 for item in results if item.status == status)
            for status in (PASS, FAIL, NOT_APPLICABLE)
        }
        self._audit.append(
            action=ACTION_RUN,
            actor=actor,
            target_type="checks_run",
            target_id=run_id,
            before_version=current,
            after_version=current + 1,
            reason="the read-only invariant checks were run",
            metadata={
                "run_id": run_id,
                "counts": counts,
                "results": [item.to_dict() for item in results],
            },
        )
        self._session.flush()
        return run_id, results

    def recorded(self, actor: ActorContext, run_id: str = "") -> dict[str, Any] | None:
        """Return a recorded run (the latest when no identifier is given)."""
        self._authorize(actor)
        statement = select(audit.AuditEvent).where(audit.AuditEvent.action == ACTION_RUN)
        if run_id:
            statement = statement.where(audit.AuditEvent.target_id == run_id)
        event = self._session.execute(
            statement.order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id.desc())
        ).scalars().first()
        if event is None:
            if run_id:
                raise NotFoundError("no recorded run has that identifier")
            return None
        meta = dict(event.metadata_json or {})
        return {
            "run_id": event.target_id,
            "ran_at": event.occurred_at.isoformat(),
            "ran_by": event.actor_id,
            "counts": dict(meta.get("counts") or {}),
            "results": list(meta.get("results") or []),
        }


__all__ = [
    "CHECKS",
    "FAIL",
    "NOT_APPLICABLE",
    "PASS",
    "PERMISSION_RUN",
    "SEED_WORDS",
    "CheckResult",
    "ChecksService",
    "fixture_baseline",
    "run_checks",
]

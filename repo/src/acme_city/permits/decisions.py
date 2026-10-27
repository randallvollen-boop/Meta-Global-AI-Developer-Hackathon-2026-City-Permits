"""Actual reviewer decisions.

A decision is recorded by an authorized reviewer, with the actor, the time,
the reason and the versions it was made against.  A recommendation never
supplies the reviewer identity and never performs the transition.

A reconfirmation is a new decision version that refers to the current
evaluation.  The earlier decision keeps its content and is marked superseded;
it is never rewritten in place.
"""
# REQUIRES: PER-04, PER-03, CHG-01, SEC-03
# A reviewer confirm, modify, deny or request-information action is
# authenticated, authorized and persisted with the actor, the time, the reason
# and the versions it used.  An unresolved blocker refuses an approval, and a
# request that only supplies a ruling is not a transition at all.

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult, VersionedResult
from acme_city.permits.schemas import Blocker, PermitModel
from acme_city.permits.service import PERMIT_DOMAIN, PermitService
from acme_city.persistence.models import permit

#: The outcomes a reviewer may record.
DECISION_OUTCOMES: tuple[str, ...] = (
    "approved",
    "denied",
    "modified",
    "information_requested",
)

#: The outcomes that require an application without unresolved blockers.
OUTCOMES_REQUIRING_CLEARANCE: frozenset[str] = frozenset({"approved", "modified"})

#: The statuses an application may hold when a decision is recorded.
DECIDABLE_STATUSES: frozenset[str] = frozenset(
    {"submitted", "ready_for_review", "under_review", "needs_information"}
)


class PermitDecisionCommand(PermitModel):
    """Record a reviewer decision.

    Unknown fields are refused rather than ignored, so a request that only
    carries a ruling is rejected before it reaches the service.
    """

    model_config = ConfigDict(extra="forbid")

    application_id: str | None = None
    outcome: str
    reason: str = ""
    expected_application_version: int | None = None
    expected_evaluation_version: int | None = None


class DecisionView(PermitModel):
    """One recorded reviewer decision."""

    decision_id: str
    application_id: str
    evaluation_id: str | None = None
    decision_type: str = "review"
    outcome: str
    decided_by_actor_id: str
    decided_at: datetime
    reason: str | None = None
    input_versions: dict[str, Any] = {}
    rule_versions: dict[str, Any] = {}
    status: str = "current"
    stale: bool = False
    version: int = 1


class PermitDecisionService:
    """Records the actual decisions of an authorized reviewer."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._permits = PermitService(session, now=self._now)

    def decide(
        self, command: PermitDecisionCommand, actor: ActorContext
    ) -> VersionedResult[DecisionView] | ConflictResult:
        """Record a reviewer decision on an application."""
        outcome = str(command.outcome or "").strip().lower()
        if outcome not in DECISION_OUTCOMES:
            raise ValidationError(
                f"unsupported decision outcome: {command.outcome!r}; use one of "
                + ", ".join(DECISION_OUTCOMES)
            )
        application = self._load_application(command)
        self._permissions.authorize(
            actor,
            "permit.decide",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )

        conflict = self._version_conflict(command, application)
        if conflict is not None:
            return conflict
        if application.status not in DECIDABLE_STATUSES:
            raise ValidationError(
                f"an application in status {application.status!r} cannot take a reviewer decision"
            )

        evaluation = self._permits.current_evaluation(application.id)
        if evaluation is None:
            raise ValidationError("the application has no current evaluation to decide against")
        if evaluation.stale:
            raise ValidationError("the current evaluation is stale; it must be evaluated again")
        if (
            command.expected_evaluation_version is not None
            and evaluation.version != command.expected_evaluation_version
        ):
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_evaluation_version,
                current_version=evaluation.version,
                differences=(
                    {
                        "field": "evaluation_version",
                        "expected": command.expected_evaluation_version,
                        "current": evaluation.version,
                    },
                ),
            )

        blockers = self.blockers(application, evaluation)
        if outcome in OUTCOMES_REQUIRING_CLEARANCE and blockers:
            raise ValidationError(
                "the application has unresolved blockers and cannot be approved",
                blockers=[blocker.model_dump(mode="json") for blocker in blockers],
            )

        decision = self._record(
            application=application,
            evaluation=evaluation,
            outcome=outcome,
            reason=command.reason,
            actor=actor,
            decision_type="review",
        )
        event = self._audit.append(
            action="permit.decide",
            actor=actor,
            target_type="decision",
            target_id=decision.id,
            after_version=decision.version,
            reason=command.reason or None,
            references=[application.id, evaluation.id],
            correlation_id=application.correlation_id,
        )
        self._session.flush()
        return VersionedResult(
            value=self.view(decision), version=decision.version, audit_event_id=event.id
        )

    def reconfirm(
        self, command: PermitDecisionCommand, actor: ActorContext
    ) -> VersionedResult[DecisionView] | ConflictResult:
        """Record a reviewer reconfirmation of a stale decision.

        The earlier decision keeps its content and becomes superseded; the
        reconfirmation is a new decision version that refers to the current
        evaluation.
        """
        outcome = str(command.outcome or "approved").strip().lower()
        if outcome not in DECISION_OUTCOMES:
            raise ValidationError(f"unsupported decision outcome: {command.outcome!r}")
        application = self._load_application(command)
        self._permissions.authorize(
            actor,
            "permit.decide",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        conflict = self._version_conflict(command, application)
        if conflict is not None:
            return conflict

        previous = self._permits.current_decision(application.id)
        if previous is None:
            raise ValidationError("the application has no decision to reconfirm")
        evaluation = self._permits.current_evaluation(application.id)
        if evaluation is None:
            raise ValidationError("the application has no current evaluation to decide against")
        if evaluation.stale:
            raise ValidationError("the current evaluation is stale; it must be evaluated again")
        if (
            command.expected_evaluation_version is not None
            and evaluation.version != command.expected_evaluation_version
        ):
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_evaluation_version,
                current_version=evaluation.version,
                differences=(
                    {
                        "field": "evaluation_version",
                        "expected": command.expected_evaluation_version,
                        "current": evaluation.version,
                    },
                ),
            )

        blockers = self.blockers(application, evaluation)
        if outcome in OUTCOMES_REQUIRING_CLEARANCE and blockers:
            raise ValidationError(
                "the application has unresolved blockers and cannot be approved",
                blockers=[blocker.model_dump(mode="json") for blocker in blockers],
            )

        decision = self._record(
            application=application,
            evaluation=evaluation,
            outcome=outcome,
            reason=command.reason,
            actor=actor,
            decision_type="reconfirmation",
        )
        previous.status = "superseded"
        previous.version += 1
        self._session.flush()
        event = self._audit.append(
            action="permit.reconfirm",
            actor=actor,
            target_type="decision",
            target_id=decision.id,
            after_version=decision.version,
            reason=command.reason or None,
            references=[application.id, evaluation.id, previous.id],
            correlation_id=application.correlation_id,
        )
        self._session.flush()
        return VersionedResult(
            value=self.view(decision), version=decision.version, audit_event_id=event.id
        )

    # ------------------------------------------------------------- internals

    def _load_application(self, command: PermitDecisionCommand) -> permit.Application:
        """Return the application a decision command names."""
        if not command.application_id:
            raise ValidationError("the decision command names no application")
        return self._permits.load_application(command.application_id)

    def _version_conflict(
        self, command: PermitDecisionCommand, application: permit.Application
    ) -> ConflictResult | None:
        """Return the conflict of a stale expected application version."""
        if (
            command.expected_application_version is not None
            and application.version != command.expected_application_version
        ):
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_application_version,
                current_version=application.version,
                differences=(
                    {
                        "field": "application_version",
                        "expected": command.expected_application_version,
                        "current": application.version,
                    },
                ),
            )
        return None

    def blockers(
        self, application: permit.Application, evaluation: permit.Evaluation
    ) -> list[Blocker]:
        """Return the unresolved conditions of an application.

        A missing or invalid identity link, an unresolved site, an invalid
        credential and an unresolved rule result all block an approval.
        """
        blockers: list[Blocker] = []
        stored = dict(evaluation.source_versions or {}).get("blockers") or []
        for blocker in stored:
            blockers.append(Blocker(**blocker))
        blockers.extend(self._permits.identity_link_blockers(application))
        blockers.extend(self._permits.finance_link_blockers(application))
        for result in evaluation.results or []:
            status = str(result.get("status", "review"))
            if status in {"fail", "review"}:
                blockers.append(
                    Blocker(
                        code=f"rule_{status}",
                        detail=(
                            f"{result.get('rule_id')} is {status}: "
                            f"{result.get('detail') or result.get('message') or ''}"
                        ).strip(),
                        subject_type="rule",
                        subject_id=str(result.get("rule_id")),
                    )
                )
        return blockers

    def _record(
        self,
        *,
        application: permit.Application,
        evaluation: permit.Evaluation,
        outcome: str,
        reason: str,
        actor: ActorContext,
        decision_type: str,
    ) -> permit.Decision:
        """Write one decision and move the application to its new state."""
        source_versions = dict(evaluation.source_versions or {})
        dependency_versions = dict(source_versions.get("dependency_versions") or {})
        decision = permit.Decision(
            id=new_id("decision"),
            application_id=application.id,
            evaluation_id=evaluation.id,
            decision_type=decision_type,
            outcome=outcome,
            decided_by_actor_id=actor.actor_id,
            decided_at=self._now,
            reason=reason or None,
            input_versions={
                "application_version": application.version,
                "evaluation_id": evaluation.id,
                "evaluation_version": evaluation.version,
                "evaluation_performed_at": evaluation.performed_at.isoformat(),
                "dependency_versions": dependency_versions,
            },
            rule_versions=dict(evaluation.rule_versions or {}),
            status="current",
            stale=False,
        )
        self._session.add(decision)
        application.status = {
            "approved": "approved",
            "modified": "approved",
            "denied": "denied",
            "information_requested": "needs_information",
        }[outcome]
        application.version += 1
        self._session.flush()
        return decision

    def view(self, decision: permit.Decision) -> DecisionView:
        """Return the view of one stored decision."""
        return DecisionView(
            decision_id=decision.id,
            application_id=decision.application_id,
            evaluation_id=decision.evaluation_id,
            decision_type=decision.decision_type,
            outcome=decision.outcome,
            decided_by_actor_id=decision.decided_by_actor_id,
            decided_at=decision.decided_at,
            reason=decision.reason,
            input_versions=dict(decision.input_versions or {}),
            rule_versions=dict(decision.rule_versions or {}),
            status=decision.status,
            stale=decision.stale,
            version=decision.version,
        )


__all__ = [
    "DECIDABLE_STATUSES",
    "DECISION_OUTCOMES",
    "OUTCOMES_REQUIRING_CLEARANCE",
    "DecisionView",
    "PermitDecisionCommand",
    "PermitDecisionService",
]

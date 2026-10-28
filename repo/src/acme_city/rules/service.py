"""The rule and fee catalogue service.

The service owns the catalogue lifecycle: it selects the published versions
that are in force at a recorded basis date, it evaluates inputs against them
and it moves a version through Draft, In review, Approved, Published and
Retired.  Under the ``independent`` approval policy an author may never
approve or publish their own version; under ``single`` the author may, with a
confirmation and a reason that are recorded.  An overlapping published version
is refused unless an explicit precedence policy says which version wins.
"""
# REQUIRES: REF-01, REF-02, PER-02, PER-06, CHG-01
# The catalogue selects one published version per basis date, evaluates against
# it and records the citation it used.  Publication is a separate authorized
# transition and self-approval is refused.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult, VersionedResult
from acme_city.persistence.models import finance
from acme_city.rules import approval_policy, catalog
from acme_city.rules.evaluator import evaluate as evaluate_inputs
from acme_city.rules.schemas import (
    DraftFeeScheduleCommand,
    DraftRuleCommand,
    FeeScheduleLifecycleCommand,
    FeeScheduleView,
    PublishRuleCommand,
    RetireRuleCommand,
    RuleLifecycleCommand,
    RuleResult,
    RuleSetVersion,
    RuleSetView,
)

#: The domain a rule change is authorized in.
RULE_DOMAIN = "building_rules"

#: The domain a fee schedule change is authorized in.
FEE_DOMAIN = "finance"


class RuleCatalogService:
    """Retrieval, execution and governance of the rule catalogue."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ----------------------------------------------------------------- reading

    def resolve(
        self,
        kind: str,
        permit_type: str | None,
        basis_at: datetime,
        *,
        basis_label: str = "initial_submitted_at",
    ) -> RuleSetVersion:
        """Return the catalogue versions in force at ``basis_at``.

        Args:
            kind: ``executable`` for the rule versions or ``fee_schedule`` for
                the fee schedule.
            permit_type: The permit type key, for example ``com_ti``.
            basis_at: The recorded date the selection is based on.
            basis_label: The recorded reason the basis date was chosen.

        Returns:
            The selected versions, their citations and the basis they were
            selected on.
        """
        permit_type_id = (
            catalog.permit_type_id_for_key(self._session, permit_type) if permit_type else None
        )
        rule_set_id = f"ruleset:{kind}:{permit_type or 'all'}:{basis_at.isoformat()}"
        if kind == "fee_schedule":
            row = catalog.select_fee_schedule(self._session, basis_at, permit_type)
            schedule = None if row is None else catalog.fee_schedule_view(row)
            return RuleSetVersion(
                rule_set_id=rule_set_id,
                kind=kind,
                permit_type_key=permit_type,
                basis_at=basis_at,
                basis_label=basis_label,
                rules=[],
                fee_schedule=schedule,
                citations=[],
            )
        rows = catalog.select_rule_versions(self._session, permit_type_id, basis_at)
        rules = [
            catalog.rule_view(row, catalog.permit_type_key(self._session, row.permit_type_id))
            for row in rows
        ]
        return RuleSetVersion(
            rule_set_id=rule_set_id,
            kind=kind,
            permit_type_key=permit_type,
            basis_at=basis_at,
            basis_label=basis_label,
            rules=rules,
            fee_schedule=None,
            citations=catalog.citations_of(rules),
        )

    def evaluate(
        self, inputs: dict[str, Any], rule_set: RuleSetVersion
    ) -> tuple[RuleResult, ...]:
        """Evaluate ``inputs`` against the selected versions."""
        return evaluate_inputs(inputs, rule_set)

    def list_versions(
        self, permit_type: str | None = None, *, status: str | None = None
    ) -> list[RuleSetView]:
        """Return the stored rule versions, newest catalogue order first."""
        query = select(finance.RuleVersion).order_by(
            finance.RuleVersion.rule_id, finance.RuleVersion.effective_from
        )
        if status is not None:
            query = query.where(finance.RuleVersion.status == status)
        rows = self._session.execute(query).scalars().all()
        views: list[RuleSetView] = []
        for row in rows:
            key = catalog.permit_type_key(self._session, row.permit_type_id)
            if permit_type is not None and key != permit_type:
                continue
            views.append(
                RuleSetView(
                    **catalog.rule_view(row, key).model_dump(exclude={"row_id"}),
                    row_id=row.id,
                )
            )
        return views

    def get_version(self, rule_version_id: str) -> RuleSetView:
        """Return one stored rule version."""
        row = self._session.execute(
            select(finance.RuleVersion).where(finance.RuleVersion.id == rule_version_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that rule version does not exist")
        key = catalog.permit_type_key(self._session, row.permit_type_id)
        return RuleSetView(
            **catalog.rule_view(row, key).model_dump(exclude={"row_id"}), row_id=row.id
        )

    # --------------------------------------------------------------- lifecycle

    def draft(self, command: DraftRuleCommand, actor: ActorContext) -> VersionedResult[RuleSetView]:
        """Create a new draft rule version."""
        self._permissions.authorize(
            actor, "rule.version.draft", ResourceContext(domain_id=RULE_DOMAIN)
        )
        permit_type_id = catalog.permit_type_id_for_key(self._session, command.permit_type_key)
        if permit_type_id is None:
            raise ValidationError("that permit type is not configured")
        if not command.citation.strip():
            raise ValidationError("a rule version must carry exactly one citation")
        if command.operator and command.operator.lower() not in ("min", "max", "equals"):
            raise ValidationError(f"unsupported rule operator: {command.operator!r}")

        business_version = 1
        existing = self._session.execute(
            select(finance.RuleVersion).where(finance.RuleVersion.rule_id == command.rule_id)
        ).scalars().all()
        if existing:
            business_version = max(catalog.business_version(row) for row in existing) + 1

        mapping: dict[str, Any] = {"business_version": business_version}
        row = finance.RuleVersion(
            id=new_id("rulever"),
            rule_id=command.rule_id,
            permit_type_id=permit_type_id,
            kind="executable",
            title=command.title,
            citation=command.citation.strip(),
            field_path=command.field_path,
            operator=command.operator.lower() if command.operator else None,
            limit_value=command.limit_value,
            on_violate=command.on_violate,
            condition=dict(command.condition) if command.condition else None,
            message=command.message,
            condition_note=command.condition_note,
            effective_from=command.effective_from,
            effective_to=None,
            status="draft",
            author_actor_id=actor.actor_id,
            approver_actor_id=None,
            source_mapping=mapping,
        )
        self._session.add(row)
        self._session.flush()
        event = self._audit.append(
            action="rule.version.draft",
            actor=actor,
            target_type="rule_version",
            target_id=row.id,
            after_version=row.version,
            reason=command.reason or None,
            references=[row.rule_id],
        )
        self._session.flush()
        return VersionedResult(
            value=self.get_version(row.id), version=row.version, audit_event_id=event.id
        )

    def submit_for_review(
        self, command: RuleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[RuleSetView] | ConflictResult:
        """Move a draft version into review."""
        return self._transition(command, actor, "draft", "in_review", "rule.version.draft")

    def approve(
        self, command: RuleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[RuleSetView] | ConflictResult:
        """Approve a version that is in review.

        Under the ``independent`` policy the author of a version may never
        approve it.  Under ``single`` the author may, with a confirmation and
        a reason, and the event records that basis.
        """
        row = self._load(command.rule_version_id)
        metadata = self._approval_metadata(
            command, actor, row.author_actor_id, "rule.version.approve", "rule_version", row.id,
            "rule version",
        )
        return self._transition(
            command, actor, "in_review", "approved", "rule.version.approve", metadata=metadata
        )

    def publish(
        self, command: PublishRuleCommand, actor: ActorContext
    ) -> VersionedResult[RuleSetView] | ConflictResult:
        """Publish an approved rule version.

        A published version may not overlap another published version of the
        same rule unless the command names an explicit precedence, and it may
        not reuse a citation that another rule already publishes.
        """
        row = self._load(command.rule_version_id)
        publish_metadata = self._publication_metadata(
            actor, row.author_actor_id, "rule_version", row.id, "rule version"
        )
        if command.precedence is None:
            conflict = catalog.conflicting_published_version(self._session, row)
            if conflict is not None:
                return ConflictResult(
                    code="overlapping_published_version",
                    expected_version=command.expected_version,
                    current_version=conflict.version,
                    differences=(
                        {
                            "rule_id": row.rule_id,
                            "published_version_id": conflict.id,
                            "published_effective_from": conflict.effective_from.isoformat(),
                            "published_effective_to": (
                                conflict.effective_to.isoformat() if conflict.effective_to else None
                            ),
                            "candidate_effective_from": row.effective_from.isoformat(),
                            "candidate_effective_to": (
                                row.effective_to.isoformat() if row.effective_to else None
                            ),
                        },
                    ),
                )
            duplicate = catalog.conflicting_citation(self._session, row)
            if duplicate is not None:
                return ConflictResult(
                    code="duplicate_citation",
                    expected_version=command.expected_version,
                    current_version=duplicate.version,
                    differences=(
                        {
                            "citation": row.citation,
                            "published_rule_id": duplicate.rule_id,
                            "published_version_id": duplicate.id,
                        },
                    ),
                )
            contradiction = catalog.conflicting_operator(self._session, row)
            if contradiction is not None:
                return ConflictResult(
                    code="conflicting_applicability",
                    expected_version=command.expected_version,
                    current_version=contradiction.version,
                    differences=(
                        {
                            "field_path": row.field_path,
                            "candidate_operator": row.operator,
                            "published_rule_id": contradiction.rule_id,
                            "published_operator": contradiction.operator,
                        },
                    ),
                )
        result = self._transition(
            command,
            actor,
            "approved",
            "published",
            "rule.version.publish",
            metadata=publish_metadata,
        )
        if isinstance(result, ConflictResult):
            return result
        published = self._load(command.rule_version_id)
        if command.precedence is not None:
            mapping = dict(published.source_mapping or {})
            mapping["precedence"] = command.precedence
            published.source_mapping = mapping
            self._session.flush()
            return VersionedResult(
                value=self.get_version(published.id),
                version=published.version,
                audit_event_id=result.audit_event_id,
            )
        return result

    def retire(
        self, command: RetireRuleCommand, actor: ActorContext
    ) -> VersionedResult[RuleSetView] | ConflictResult:
        """Retire a published rule version and close its effective window."""
        row = self._load(command.rule_version_id)
        if command.effective_to is not None:
            row.effective_to = command.effective_to
        return self._transition(command, actor, "published", "retired", "rule.version.publish")

    # ------------------------------------------------------- fee schedules

    def draft_fee_schedule(
        self, command: DraftFeeScheduleCommand, actor: ActorContext
    ) -> VersionedResult[FeeScheduleView]:
        """Create a new draft fee schedule version."""
        self._permissions.authorize(
            actor, "rule.version.draft", ResourceContext(domain_id=FEE_DOMAIN)
        )
        row = finance.FeeScheduleVersion(
            id=new_id("feesched"),
            fee_schedule_id=command.fee_schedule_id,
            version_label=command.version_label,
            effective_from=command.effective_from,
            effective_to=None,
            currency=command.currency.upper(),
            definition=dict(command.definition),
            status="draft",
            author_actor_id=actor.actor_id,
            approver_actor_id=None,
        )
        self._session.add(row)
        self._session.flush()
        event = self._audit.append(
            action="fee.schedule.draft",
            actor=actor,
            target_type="fee_schedule_version",
            target_id=row.id,
            after_version=row.version,
            reason=command.reason or None,
            references=[row.fee_schedule_id, row.version_label],
        )
        self._session.flush()
        return VersionedResult(
            value=catalog.fee_schedule_view(row), version=row.version, audit_event_id=event.id
        )

    def submit_fee_schedule_for_review(
        self, command: FeeScheduleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[FeeScheduleView] | ConflictResult:
        """Move a draft fee schedule version into review."""
        return self._fee_schedule_transition(
            command, actor, "draft", "in_review", "rule.version.draft"
        )

    def approve_fee_schedule(
        self, command: FeeScheduleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[FeeScheduleView] | ConflictResult:
        """Approve a fee schedule version, under the active approval policy."""
        row = self._load_fee_schedule(command.fee_schedule_version_id)
        metadata = self._approval_metadata(
            command, actor, row.author_actor_id, "rule.version.approve",
            "fee_schedule_version", row.id, "fee schedule version",
        )
        return self._fee_schedule_transition(
            command, actor, "in_review", "approved", "rule.version.approve", metadata=metadata
        )

    def publish_fee_schedule(
        self, command: FeeScheduleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[FeeScheduleView] | ConflictResult:
        """Publish an approved fee schedule version.

        Two published versions of one schedule may not be in force at the
        same time unless an explicit precedence says which one wins.
        """
        row = self._load_fee_schedule(command.fee_schedule_version_id)
        publish_metadata = self._publication_metadata(
            actor, row.author_actor_id, "fee_schedule_version", row.id, "fee schedule version"
        )
        if command.precedence is None:
            others = self._session.execute(
                select(finance.FeeScheduleVersion).where(
                    finance.FeeScheduleVersion.fee_schedule_id == row.fee_schedule_id,
                    finance.FeeScheduleVersion.status == "published",
                    finance.FeeScheduleVersion.id != row.id,
                )
            ).scalars().all()
            for other in others:
                if catalog.windows_overlap(
                    row.effective_from,
                    row.effective_to,
                    other.effective_from,
                    other.effective_to,
                ):
                    return ConflictResult(
                        code="overlapping_published_version",
                        expected_version=command.expected_version,
                        current_version=other.version,
                        differences=(
                            {
                                "fee_schedule_id": row.fee_schedule_id,
                                "published_version_id": other.id,
                                "published_version_label": other.version_label,
                                "published_effective_from": other.effective_from.isoformat(),
                                "published_effective_to": (
                                    other.effective_to.isoformat() if other.effective_to else None
                                ),
                                "candidate_version_label": row.version_label,
                                "candidate_effective_from": row.effective_from.isoformat(),
                            },
                        ),
                    )
        return self._fee_schedule_transition(
            command,
            actor,
            "approved",
            "published",
            "rule.version.publish",
            metadata=publish_metadata,
        )

    def retire_fee_schedule(
        self, command: FeeScheduleLifecycleCommand, actor: ActorContext
    ) -> VersionedResult[FeeScheduleView] | ConflictResult:
        """Retire a published fee schedule version.

        The effective window may be closed at the same time, so that the
        next version of the schedule can be published without overlapping
        it.
        """
        row = self._load_fee_schedule(command.fee_schedule_version_id)
        if command.effective_to is not None:
            row.effective_to = command.effective_to
        return self._fee_schedule_transition(
            command, actor, "published", "retired", "rule.version.publish"
        )

    def _load_fee_schedule(self, fee_schedule_version_id: str) -> finance.FeeScheduleVersion:
        """Return the stored fee schedule version or refuse."""
        row = self._session.execute(
            select(finance.FeeScheduleVersion).where(
                finance.FeeScheduleVersion.id == fee_schedule_version_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that fee schedule version does not exist")
        return row

    def _fee_schedule_transition(
        self,
        command: FeeScheduleLifecycleCommand,
        actor: ActorContext,
        expected_status: str,
        new_status: str,
        action: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> VersionedResult[FeeScheduleView] | ConflictResult:
        """Apply one guarded fee schedule lifecycle transition."""
        row = self._load_fee_schedule(command.fee_schedule_version_id)
        self._permissions.authorize(
            actor, action, ResourceContext(domain_id=FEE_DOMAIN, record_ids=(row.id,))
        )
        if row.version != command.expected_version:
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_version,
                current_version=row.version,
                differences=(
                    {"field": "version", "expected": command.expected_version, "current": row.version},
                ),
            )
        if row.status != expected_status:
            raise ValidationError(
                f"a fee schedule version in status {row.status!r} cannot move to {new_status!r}"
            )
        before = row.version
        row.status = new_status
        row.version = before + 1
        if new_status == "approved" and row.approver_actor_id is None:
            row.approver_actor_id = actor.actor_id
        self._session.flush()
        event = self._audit.append(
            action=f"fee.schedule.{new_status}",
            actor=actor,
            target_type="fee_schedule_version",
            target_id=row.id,
            before_version=before,
            after_version=row.version,
            reason=command.reason or None,
            references=[row.fee_schedule_id, row.version_label],
            metadata=metadata,
        )
        self._session.flush()
        return VersionedResult(
            value=catalog.fee_schedule_view(row), version=row.version, audit_event_id=event.id
        )

    # ------------------------------------------------------------- approval policy

    def _approval_metadata(
        self,
        command: Any,
        actor: ActorContext,
        author_actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        noun: str,
    ) -> dict[str, Any]:
        """Apply the approval policy to an approval and return the event metadata."""
        policy = approval_policy.active_policy()
        is_author = author_actor_id is not None and author_actor_id == actor.actor_id
        if not is_author:
            return {"approval_policy": policy, "approval_basis": "independent"}
        if policy != approval_policy.POLICY_SINGLE:
            raise PermissionDeniedError(
                f"an author may not approve their own {noun}",
                actor_id=actor.actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
            )
        if not (command.reason or "").strip():
            raise ValidationError(
                f"a reason is required when the author approves their own {noun}"
            )
        if not getattr(command, "confirm_author_approval", False):
            raise ValidationError(
                f"confirm that you authored this {noun} and are approving it "
                "under the single-administrator policy"
            )
        return {
            "approval_policy": policy,
            "approval_basis": approval_policy.BASIS_VALUE,
            approval_policy.BASIS_KEY: approval_policy.BASIS_APPROVAL_LABEL,
        }

    def _publication_metadata(
        self,
        actor: ActorContext,
        author_actor_id: str | None,
        target_type: str,
        target_id: str,
        noun: str,
    ) -> dict[str, Any]:
        """Apply the approval policy to a publication and return the event metadata."""
        policy = approval_policy.active_policy()
        is_author = author_actor_id is not None and author_actor_id == actor.actor_id
        if not is_author:
            return {"approval_policy": policy}
        if policy != approval_policy.POLICY_SINGLE:
            raise PermissionDeniedError(
                f"an author may not publish their own {noun}",
                actor_id=actor.actor_id,
                action="rule.version.publish",
                target_type=target_type,
                target_id=target_id,
            )
        return {
            "approval_policy": policy,
            "approval_basis": approval_policy.BASIS_VALUE,
            approval_policy.BASIS_KEY: approval_policy.BASIS_PUBLICATION_LABEL,
        }

    # ------------------------------------------------------------- transitions

    def _load(self, rule_version_id: str) -> finance.RuleVersion:
        """Return the stored rule version or refuse."""
        row = self._session.execute(
            select(finance.RuleVersion).where(finance.RuleVersion.id == rule_version_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that rule version does not exist")
        return row

    def _transition(
        self,
        command: RuleLifecycleCommand,
        actor: ActorContext,
        expected_status: str,
        new_status: str,
        action: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> VersionedResult[RuleSetView] | ConflictResult:
        """Apply one guarded lifecycle transition."""
        row = self._load(command.rule_version_id)
        self._permissions.authorize(
            actor, action, ResourceContext(domain_id=RULE_DOMAIN, record_ids=(row.id,))
        )
        if row.version != command.expected_version:
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_version,
                current_version=row.version,
                differences=(
                    {"field": "version", "expected": command.expected_version, "current": row.version},
                ),
            )
        if row.status != expected_status:
            raise ValidationError(
                f"a rule version in status {row.status!r} cannot move to {new_status!r}"
            )
        before = row.version
        row.status = new_status
        row.version = before + 1
        if new_status == "approved" and row.approver_actor_id is None:
            row.approver_actor_id = actor.actor_id
        self._session.flush()
        event = self._audit.append(
            action=action,
            actor=actor,
            target_type="rule_version",
            target_id=row.id,
            before_version=before,
            after_version=row.version,
            reason=command.reason or None,
            references=[row.rule_id],
            metadata=metadata,
        )
        self._session.flush()
        return VersionedResult(
            value=self.get_version(row.id), version=row.version, audit_event_id=event.id
        )


__all__ = ["FEE_DOMAIN", "RULE_DOMAIN", "RuleCatalogService"]

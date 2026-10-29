"""From a what-if run to draft rule and fee schedule versions.

Only the changes that the existing draft commands can represent are
converted: a rule limit or operator change (``DraftRuleCommand``) and a fee
schedule change of a fixed charge or a valuation multiplier
(``DraftFeeScheduleCommand``).  Retirement, requirements, process category,
discretion and service target changes stay simulation-only.  A scenario that
mixes the two is refused whole; nothing is ever converted in part.

The conversion:

* is **authored by the City Administrator who pressed it** (the actual actor,
  recorded as the draft author); no other identity is ever used;
* goes through :class:`~acme_city.rules.service.RuleCatalogService`, so the
  drafts are ordinary draft versions that still need the existing review,
  approval and publication, and the approval policy: under ``independent`` an
  author cannot approve or publish their own version, under ``single`` the
  author may, with a confirmation and a reason;
* is **version-bound**: it needs the expected version of the run's conversion
  state (0 before, 1 after) and it refuses when a published rule or fee it was
  made against has changed since the run;
* is **atomic**: everything is checked before the first draft is written, and
  any failure leaves no draft;
* is **idempotent**: a run converts once; a repeat of the same request finds
  the same drafts and writes nothing;
* is **audited** without free text.

Nothing published changes: a draft is not in force.
"""
# REQUIRES: REF-01, PER-02, PER-04, PER-06, SEC-01
# A run converts to draft versions only, by the existing commands, in the Administrator's name,
# once, atomically and bound to the version it was made from.

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ConflictError, NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import finance, governance
from acme_city.persistence.models import policy as models
from acme_city.policy.baseline import freeze_baseline
from acme_city.policy.changes import (
    FEE_FIXED_KEY,
    FEE_MULTIPLIER_KEY,
    FeeChange,
    RuleThresholdChange,
    UnsupportedChange,
    parse_change,
)
from acme_city.kernel.selection import published_in_force
from acme_city.policy.views import describe_change
from acme_city.rules import approval_policy
from acme_city.rules.schemas import DraftFeeScheduleCommand, DraftRuleCommand
from acme_city.rules.service import FEE_DOMAIN, RULE_DOMAIN, RuleCatalogService

PERMISSION_CONVERT: Final = "policy.draft.convert"
PERMISSION_RUN_VIEW: Final = "policy.run.view"
ACTION_CONVERT: Final = "policy.draft.convert"

#: The operators the existing draft command accepts.
DRAFT_OPERATORS: Final = ("min", "max", "equals")

#: The plain reason shown wherever the author tries to approve or publish.
OWN_VERSION_REASON: Final = "You authored this version; another administrator must approve it."

#: The status wording of a converted draft under the independent policy.
HANDOFF_STATUS: Final = "Draft: needs independent approval"

#: The status wording of a converted draft under the single-administrator policy.
HANDOFF_STATUS_SINGLE: Final = "Draft: ready for your approval"


def handoff_status() -> str:
    """Return the status wording of a converted draft under the active approval policy."""
    return HANDOFF_STATUS_SINGLE if approval_policy.is_single() else HANDOFF_STATUS


def _proposed_reason(run_id: str) -> str:
    """Return the reason recorded on a draft made from a what-if run."""
    if approval_policy.is_single():
        return f"Proposed by what-if run {run_id}; ready for approval by a City Administrator."
    return f"Proposed by what-if run {run_id}; needs independent approval."

KIND_RULE: Final = "rule"
KIND_FEE: Final = "fee"


@dataclass(frozen=True)
class PlanItem:
    """One draft the conversion will make."""

    kind: str  # "rule" or "fee"
    change_index: int
    target_id: str  # a rule id or a fee schedule id
    summary: str


@dataclass(frozen=True)
class DraftPlan:
    """What converting a run would do, or why it cannot."""

    items: tuple[PlanItem, ...]
    #: Plain descriptions of the changes that stay simulation-only.
    blockers: tuple[str, ...]

    @property
    def convertible(self) -> bool:
        return bool(self.items) and not self.blockers


def _parse_moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _in_force(entry: Mapping[str, Any], moment: datetime) -> bool:
    start = _parse_moment(entry["effective_from"])
    end = entry.get("effective_to")
    return start <= moment and (end is None or moment < _parse_moment(end))


def _find(entries: list[Mapping[str, Any]], key: str, value: str, moment: datetime) -> Mapping[str, Any] | None:
    for entry in entries:
        if entry.get(key) == value and entry.get("status") == "published" and _in_force(entry, moment):
            return entry
    return None


def plan_for_run(run: models.PolicyRun) -> DraftPlan:
    """Return the draft plan of a stored run.  Reads the run only."""
    from acme_city.policy.views import _baseline_view  # noqa: PLC0415

    baseline = _baseline_view(run)
    moment = run.analysis_at
    items: list[PlanItem] = []
    blockers: list[str] = []
    applied = list(run.result.get("applied_changes", []))
    if not applied:
        blockers.append("The run holds no change to convert.")
    for position, entry in enumerate(applied):
        raw = entry["change"]
        text = describe_change(raw, baseline)
        try:
            change = parse_change(raw)
        except Exception:  # a stored change that no longer reads stays simulation-only
            blockers.append(text)
            continue
        if isinstance(change, UnsupportedChange):
            blockers.append(text)
        elif isinstance(change, RuleThresholdChange):
            before = _find(run.baseline_config["rules"], "rule_id", change.rule_id, moment)
            after = _find(run.proposed_config["rules"], "rule_id", change.rule_id, moment)
            if before is None or after is None:
                blockers.append(f"{text} (the rule is not in the run's configuration)")
            elif (after.get("operator") or "") not in DRAFT_OPERATORS:
                blockers.append(f"{text} (a draft rule version cannot hold the operator {after.get('operator')!r})")
            else:
                items.append(PlanItem(KIND_RULE, position, change.rule_id, text))
        elif isinstance(change, FeeChange):
            before = _find(run.baseline_config["fee_schedules"], "fee_schedule_id", change.fee_schedule_id, moment)
            after = _find(run.proposed_config["fee_schedules"], "fee_schedule_id", change.fee_schedule_id, moment)
            if before is None or after is None:
                blockers.append(f"{text} (the fee schedule is not in the run's configuration)")
            else:
                items.append(PlanItem(KIND_FEE, position, change.fee_schedule_id, text))
        else:
            blockers.append(text)
    return DraftPlan(items=tuple(items), blockers=tuple(blockers))


def _replace_figure(text: str | None, old: str | None, new: str | None) -> str | None:
    """Carry a changed limit into the rule's own wording (``6 ft`` becomes ``7 ft``)."""
    if not text or not old or not new or old == new:
        return text
    return re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w.])", new, text)


def _fee_formula(definition: Mapping[str, Any], currency: str) -> str:
    fixed = int(definition.get(FEE_FIXED_KEY) or 0)
    return (
        f"{fixed // 100}.{fixed % 100:02d} {currency} fixed review charge plus "
        f"{definition.get(FEE_MULTIPLIER_KEY)} times the declared valuation; "
        "the variable component is rounded once to cents"
    )


class PolicyDraftService:
    """Convert a run into draft versions, and read the result."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------------ reads

    def can(self, actor: ActorContext, permission: str) -> bool:
        return self._permissions.allows(actor, permission, ResourceContext(domain_id=None))

    def _authorize(self, actor: ActorContext, permission: str) -> None:
        self._permissions.authorize(actor, permission, ResourceContext(domain_id=None))

    def _run(self, run_id: str) -> models.PolicyRun:
        run = self._session.get(models.PolicyRun, run_id)
        if run is None:
            raise NotFoundError("no run has that identifier")
        return run

    def plan(self, actor: ActorContext, run_id: str) -> DraftPlan:
        self._authorize(actor, PERMISSION_RUN_VIEW)
        return plan_for_run(self._run(run_id))

    def conversion_for(self, actor: ActorContext, run_id: str) -> models.PolicyDraftConversion | None:
        self._authorize(actor, PERMISSION_RUN_VIEW)
        return self._session.execute(
            select(models.PolicyDraftConversion).where(models.PolicyDraftConversion.run_id == run_id)
        ).scalar_one_or_none()

    def conversion_version(self, actor: ActorContext, run_id: str) -> int:
        """Return the version a conversion request must carry: 0 before, 1 after."""
        row = self.conversion_for(actor, run_id)
        return 0 if row is None else row.version

    def link_for_draft(self, actor: ActorContext, draft_id: str) -> str | None:
        """Return the run a draft version was made from, for a holder of the run grant."""
        if not self.can(actor, PERMISSION_RUN_VIEW):
            return None
        for row in self._session.execute(select(models.PolicyDraftConversion)).scalars():
            if any(item["id"] == draft_id for item in row.drafts):
                return row.run_id
        return None

    def links(self, actor: ActorContext) -> dict[str, str]:
        """Return ``draft id -> run id`` for every converted draft (empty without the run grant)."""
        if not self.can(actor, PERMISSION_RUN_VIEW):
            return {}
        out: dict[str, str] = {}
        for row in self._session.execute(select(models.PolicyDraftConversion)).scalars():
            for item in row.drafts:
                out[item["id"]] = row.run_id
        return out

    def approvers(self, domain_id: str, *, exclude_actor_id: str | None) -> list[dict[str, Any]]:
        """Return the active actors who hold approval in ``domain_id`` other than the author."""
        found: list[dict[str, Any]] = []
        actors = self._session.execute(
            select(governance.Actor).where(governance.Actor.active.is_(True)).order_by(governance.Actor.actor_id)
        ).scalars()
        for row in actors:
            if row.actor_id == exclude_actor_id:
                continue
            if self._permissions.allows(
                ActorContext(actor_id=row.actor_id), "rule.version.approve", ResourceContext(domain_id=domain_id)
            ):
                found.append({"actor_id": row.actor_id, "label": row.label, "selectable": bool(row.selectable)})
        return found

    def drafts_view(self, actor: ActorContext, conversion: models.PolicyDraftConversion) -> list[dict[str, Any]]:
        """Return the display data of the drafts of a conversion, as they are now."""
        self._authorize(actor, PERMISSION_RUN_VIEW)
        out: list[dict[str, Any]] = []
        for item in conversion.drafts:
            if item["kind"] == KIND_RULE:
                row: Any = self._session.get(finance.RuleVersion, item["id"])
                domain = RULE_DOMAIN
            else:
                row = self._session.get(finance.FeeScheduleVersion, item["id"])
                domain = FEE_DOMAIN
            if row is None:
                continue
            status = row.status
            out.append(
                {
                    "kind": item["kind"],
                    "id": row.id,
                    "label": item["label"],
                    "summary": item.get("summary", ""),
                    "status": status,
                    "status_label": status_label(status),
                    "author_actor_id": row.author_actor_id,
                    "you_are_author": row.author_actor_id == actor.actor_id,
                    "approver_actor_id": row.approver_actor_id,
                    "domain": domain,
                    "approvers": self.approvers(
                        domain,
                        exclude_actor_id=None if approval_policy.is_single() else row.author_actor_id,
                    ),
                    "reason_you_cannot": (
                        OWN_VERSION_REASON
                        if row.author_actor_id == actor.actor_id and not approval_policy.is_single()
                        else ""
                    ),
                    "open_href": (
                        f"/rules?tab={'rules' if item['kind'] == KIND_RULE else 'fees'}"
                        f"&view=drafts&version={row.id}"
                    ),
                }
            )
        return out

    # ----------------------------------------------------------------- the write

    def convert(
        self, actor: ActorContext, run_id: str, *, expected_version: int | None
    ) -> tuple[models.PolicyDraftConversion, bool]:
        """Save the run as drafts.  Returns ``(conversion, created)``.

        ``created`` is false when the run had already been converted and the
        request was a repeat of the same one (nothing is written then).
        """
        self._authorize(actor, PERMISSION_CONVERT)
        if expected_version is None:
            raise ValidationError("an expected version is required for this action")
        run = self._run(run_id)
        existing = self._session.execute(
            select(models.PolicyDraftConversion).where(models.PolicyDraftConversion.run_id == run.id)
        ).scalar_one_or_none()
        if existing is not None:
            if expected_version in (0, existing.version):
                return existing, False
            raise ConflictError(
                "that run was converted at another version; read it again and retry",
                current_version=existing.version,
            )
        if expected_version != 0:
            raise ConflictError(
                "that run has not been converted yet, so its version is 0; read it again and retry",
                current_version=0,
            )
        plan = plan_for_run(run)
        if plan.blockers:
            raise ValidationError(
                "This what-if cannot be saved as a draft because it holds changes that stay "
                "simulation-only: " + "; ".join(plan.blockers) + ". Nothing was converted.",
                code="unsupported_change",
            )
        if not plan.items:
            raise ValidationError("the run holds no change to convert")
        titles = self._check_still_current(run, plan)
        created: list[dict[str, Any]] = []
        service = RuleCatalogService(self._session, now=self._now)
        try:
            for item in plan.items:
                if item.kind == KIND_RULE:
                    created.append(self._draft_rule(service, actor, run, item, titles[item.target_id]))
                else:
                    created.append(self._draft_fee(service, actor, run, item))
            conversion = models.PolicyDraftConversion(
                id=new_id("poldraft"),
                correlation_id=run.correlation_id,
                created_at=self._now,
                run_id=run.id,
                scenario_id=run.scenario_id,
                run_content_hash=run.content_hash,
                converted_by_actor_id=actor.actor_id,
                drafts=created,
                version=1,
            )
            self._session.add(conversion)
            self._session.flush()
            self._audit.append(
                action=ACTION_CONVERT,
                actor=actor,
                target_type="policy_run",
                target_id=run.id,
                before_version=0,
                after_version=1,
                reason="the City Administrator saved a what-if run as draft rule changes",
                references=[item["id"] for item in created],
                correlation_id=run.correlation_id,
                metadata={
                    "run_id": run.id,
                    "run_content_hash": run.content_hash,
                    "conversion_id": conversion.id,
                    "draft_count": len(created),
                    "draft_ids": [item["id"] for item in created],
                },
            )
            self._session.flush()
        except IntegrityError as error:
            self._session.rollback()
            raise ConflictError(
                "a draft for the same rule or fee schedule already exists for this moment; "
                "read the screen again and retry",
                current_version=0,
            ) from error
        except Exception:
            self._session.rollback()
            raise
        return conversion, True

    # ------------------------------------------------------------------- helpers

    def _check_still_current(self, run: models.PolicyRun, plan: DraftPlan) -> dict[str, str]:
        """Refuse when a published rule or fee the run was made against has changed.

        Returns the title of each rule to be drafted, read from the published
        version the run was made against (a run stores no titles).
        """
        frozen = freeze_baseline(self._session, self._now)
        current = frozen.canonical()
        titles: dict[str, str] = {}
        moment = self._now
        stale: list[str] = []
        for item in plan.items:
            if item.kind == KIND_RULE:
                before = _find(run.baseline_config["rules"], "rule_id", item.target_id, run.analysis_at)
                now_ = _find(current["rules"], "rule_id", item.target_id, moment)
                keys = ("version_label", "limit_value", "operator")
                match = next(
                    (r for r in frozen.rules if r.rule_id == item.target_id and published_in_force(r, moment)),
                    None,
                )
                if match is not None:
                    titles[item.target_id] = match.title
            else:
                before = _find(run.baseline_config["fee_schedules"], "fee_schedule_id", item.target_id, run.analysis_at)
                now_ = _find(current["fee_schedules"], "fee_schedule_id", item.target_id, moment)
                keys = ("version_label", "definition")
            if before is None or now_ is None or any(before.get(k) != now_.get(k) for k in keys):
                stale.append(item.target_id)
        if stale:
            raise ConflictError(
                "The published " + ", ".join(stale) + " changed after this run was made, so a draft "
                "built from it would not match what is published. Run the what-if again.",
                current_version=0,
            )
        return titles

    def _draft_rule(
        self, service: RuleCatalogService, actor: ActorContext, run: models.PolicyRun, item: PlanItem,
        title: str,
    ) -> dict[str, Any]:
        before = _find(run.baseline_config["rules"], "rule_id", item.target_id, run.analysis_at)
        after = _find(run.proposed_config["rules"], "rule_id", item.target_id, run.analysis_at)
        assert before is not None and after is not None
        old_limit, new_limit = before.get("limit_value"), after.get("limit_value")
        command = DraftRuleCommand(
            rule_id=after["rule_id"],
            permit_type_key=after["permit_type_key"] or "",
            title=title,
            citation=after["citation"],
            field_path=after.get("field_path"),
            operator=after.get("operator"),
            limit_value=new_limit,
            on_violate=after.get("on_violate"),
            condition=dict(after["condition"]) if after.get("condition") else None,
            message=_replace_figure(after.get("message"), old_limit, new_limit),
            condition_note=_replace_figure(after.get("condition_note"), old_limit, new_limit),
            effective_from=self._now,
            reason=_proposed_reason(run.id),
        )
        result = service.draft(command, actor)
        row = self._session.get(finance.RuleVersion, result.value.row_id)
        assert row is not None
        mapping = dict(row.source_mapping or {})
        mapping.update({"policy_run_id": run.id, "policy_run_content_hash": run.content_hash})
        row.source_mapping = mapping
        self._session.flush()
        return {
            "kind": KIND_RULE,
            "id": row.id,
            "label": result.value.version_label,
            "change_index": item.change_index,
            "summary": item.summary,
        }

    def _draft_fee(
        self, service: RuleCatalogService, actor: ActorContext, run: models.PolicyRun, item: PlanItem
    ) -> dict[str, Any]:
        before = _find(run.baseline_config["fee_schedules"], "fee_schedule_id", item.target_id, run.analysis_at)
        after = _find(run.proposed_config["fee_schedules"], "fee_schedule_id", item.target_id, run.analysis_at)
        assert before is not None and after is not None
        definition = {
            key: value for key, value in dict(after["definition"]).items() if not key.startswith("example_")
        }
        definition["formula"] = _fee_formula(definition, after["currency"])
        definition["policy_run_id"] = run.id
        command = DraftFeeScheduleCommand(
            fee_schedule_id=after["fee_schedule_id"],
            version_label=f"{before['version_label']}-whatif-{run.id[-8:]}",
            effective_from=self._now,
            currency=after["currency"],
            definition=definition,
            reason=_proposed_reason(run.id),
        )
        result = service.draft_fee_schedule(command, actor)
        return {
            "kind": KIND_FEE,
            "id": result.value.row_id,
            "label": f"{result.value.fee_schedule_id} {result.value.version_label}",
            "change_index": item.change_index,
            "summary": item.summary,
        }


def status_label(status: str) -> str:
    """Return the plain status of a converted draft."""
    single = approval_policy.is_single()
    return {
        "draft": handoff_status(),
        "in_review": (
            "In review: ready for your approval"
            if single
            else "In review: needs independent approval"
        ),
        "approved": "Approved: ready for publication",
        "published": "Published",
        "retired": "Retired",
    }.get(status, status)


__all__ = [
    "ACTION_CONVERT",
    "HANDOFF_STATUS",
    "HANDOFF_STATUS_SINGLE",
    "OWN_VERSION_REASON",
    "PERMISSION_CONVERT",
    "DraftPlan",
    "PlanItem",
    "PolicyDraftService",
    "handoff_status",
    "plan_for_run",
    "status_label",
]

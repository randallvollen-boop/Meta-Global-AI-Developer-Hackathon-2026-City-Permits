"""Separate, idempotent issuance of a simulated permit.

Issuance is its own authorized action.  A reviewer approval never issues a
permit by itself, and an issuance checks the current application, evaluation,
decision, links, credentials, assessment and reconciliation inside one
transaction before it writes anything.

The permit keeps an immutable snapshot of the facts, the rules, the decision,
the assessment and the active allocations, and the artifact is rendered from
that snapshot alone.  An identical retry returns the original permit, number
and artifact.
"""
# REQUIRES: PER-05, CHG-05
# A permit is issued only from a current approved decision with current
# checks, a resolved site, valid credentials and an exact reconciliation.
# The snapshot and the artifact are immutable and an identical retry returns
# the original permit.

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult, VersionedResult
from acme_city.finance.calculator import FIXED_FEE_CODE, VARIABLE_FEE_CODE, format_cents
from acme_city.finance.service import FinanceService
from acme_city.permits.schemas import Blocker, PermitModel
from acme_city.permits.service import PERMIT_DOMAIN, PermitService, build_inputs
from acme_city.persistence.models import change, finance, permit, registry

#: The templates of the package.
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"

#: The static assets of the package.
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"

#: The stylesheet of the printable artifact.
ARTIFACT_STYLESHEET = "permit-print.css"

#: The first number of the fictional permit sequence.
PERMIT_SEQUENCE_START = 1000


class IssuePermitCommand(PermitModel):
    """Issue a simulated permit from a current approved decision.

    The command key makes the action idempotent: the same key with the same
    expected versions returns the original permit, and the same key with
    different facts is refused.
    """

    model_config = {"extra": "forbid"}

    application_id: str | None = None
    decision_id: str
    expected_application_version: int
    expected_decision_version: int
    command_key: str
    reason: str | None = None


class PermitView(PermitModel):
    """One issued simulated permit."""

    permit_id: str
    application_id: str | None = None
    decision_id: str
    permit_number: str
    issued_at: datetime
    expires_at: datetime | None = None
    status: str = "issued"
    artifact_hash: str = ""
    issuance_command_key: str = ""
    issued_by_actor_id: str | None = None
    snapshot: dict[str, Any] = {}
    fictional_demo: bool = True


def _line_order(line: finance.AssessmentLine) -> tuple[int, str]:
    """Return the display order of one assessment line."""
    if line.fee_code == FIXED_FEE_CODE:
        return (0, line.fee_code)
    if line.fee_code == VARIABLE_FEE_CODE:
        return (1, line.fee_code)
    return (2, line.fee_code)


def _environment() -> Environment:
    """Return the Jinja environment of the package templates."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def artifact_styles() -> str:
    """Return the printable stylesheet of the artifact."""
    path = STATIC_ROOT / ARTIFACT_STYLESHEET
    if not path.exists():  # pragma: no cover - packaging guard
        return ""
    return path.read_text(encoding="utf-8")


def fingerprint(command: IssuePermitCommand) -> str:
    """Return the idempotency fingerprint of an issuance command.

    The fingerprint covers the operation, the records it names and the
    expected versions it was made against.  A reused key with a different
    fingerprint is a different request and is refused.
    """
    payload = {
        "operation": "permit.issue",
        "application_id": command.application_id,
        "decision_id": command.decision_id,
        "expected_application_version": command.expected_application_version,
        "expected_decision_version": command.expected_decision_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PermitIssuanceService:
    """Issues simulated permits and renders their artifacts."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._permits = PermitService(session, now=self._now)
        self._finance = FinanceService(session, now=self._now)

    def issue(
        self, command: IssuePermitCommand, actor: ActorContext
    ) -> VersionedResult[PermitView] | ConflictResult:
        """Issue a simulated permit, or return the permit that already exists."""
        if not command.application_id:
            raise ValidationError("the issuance command names no application")
        application = self._permits.load_application(command.application_id)
        self._permissions.authorize(
            actor,
            "permit.issue",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )

        existing = self._session.execute(
            select(permit.Permit).where(
                permit.Permit.issuance_command_key == command.command_key
            )
        ).scalar_one_or_none()
        requested = fingerprint(command)
        if existing is not None:
            stored = str((existing.snapshot or {}).get("idempotency_fingerprint") or "")
            if stored == requested:
                return VersionedResult(
                    value=self.view(existing),
                    version=existing.version,
                    audit_event_id=str(
                        (existing.snapshot or {}).get("audit_event_id") or existing.id
                    ),
                )
            return ConflictResult(
                code="issuance_key_reused",
                differences=(
                    {
                        "command_key": command.command_key,
                        "stored_fingerprint": stored,
                        "requested_fingerprint": requested,
                        "permit_id": existing.id,
                    },
                ),
            )

        if application.version != command.expected_application_version:
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

        decision = self._session.execute(
            select(permit.Decision).where(permit.Decision.id == command.decision_id)
        ).scalar_one_or_none()
        if decision is None:
            raise NotFoundError("that decision does not exist")
        if decision.application_id != application.id:
            raise ValidationError("that decision belongs to another application")
        if decision.version != command.expected_decision_version:
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_decision_version,
                current_version=decision.version,
                differences=(
                    {
                        "field": "decision_version",
                        "expected": command.expected_decision_version,
                        "current": decision.version,
                    },
                ),
            )

        blockers = self.blockers(application, decision)
        if blockers:
            raise ValidationError(
                "the permit may not be issued yet",
                blockers=[blocker.model_dump(mode="json") for blocker in blockers],
            )

        snapshot = self._snapshot(application, decision)
        permit_number = self._permit_number()
        snapshot["permit_number"] = permit_number
        snapshot["idempotency_fingerprint"] = requested

        issued = permit.Permit(
            id=new_id("permit"),
            application_id=application.id,
            decision_id=decision.id,
            permit_number=permit_number,
            issued_at=self._now,
            expires_at=None,
            status="issued",
            snapshot=snapshot,
            artifact_hash="",
            issuance_command_key=command.command_key,
            issued_by_actor_id=actor.actor_id,
            fictional_demo=True,
        )
        self._session.add(issued)
        application.status = "issued"
        application.version += 1
        self._session.flush()

        artifact = self.render_artifact(issued.id)
        issued.artifact_hash = hashlib.sha256(artifact).hexdigest()
        snapshot["artifact_hash"] = issued.artifact_hash
        issued.snapshot = snapshot
        self._session.flush()

        event = self._audit.append(
            action="permit.issue",
            actor=actor,
            target_type="permit",
            target_id=issued.id,
            after_version=issued.version,
            reason=command.reason or None,
            references=[application.id, decision.id],
            correlation_id=application.correlation_id,
            metadata={"permit_number": permit_number},
        )
        snapshot["audit_event_id"] = event.id
        issued.snapshot = snapshot
        self._session.flush()
        return VersionedResult(
            value=self.view(issued), version=issued.version, audit_event_id=event.id
        )

    # ------------------------------------------------------------------ checks

    def blockers(
        self, application: permit.Application, decision: permit.Decision
    ) -> list[Blocker]:
        """Return the conditions that block an issuance.

        Every condition is checked against the current state: the decision,
        the evaluation it refers to, the site, the credentials, the identity
        links, the assessment and the reconciliation.
        """
        blockers: list[Blocker] = []
        if decision.status != "current":
            blockers.append(
                Blocker(
                    code="decision_not_current",
                    detail="the decision has been superseded",
                    subject_type="decision",
                    subject_id=decision.id,
                )
            )
        if decision.stale:
            blockers.append(
                Blocker(
                    code="decision_stale",
                    detail="the decision is stale and needs a reviewer reconfirmation",
                    subject_type="decision",
                    subject_id=decision.id,
                )
            )
        if decision.outcome != "approved":
            blockers.append(
                Blocker(
                    code="decision_not_approved",
                    detail=f"the decision outcome is {decision.outcome!r}",
                    subject_type="decision",
                    subject_id=decision.id,
                )
            )
        if application.status != "approved":
            blockers.append(
                Blocker(
                    code="application_not_approved",
                    detail=f"the application is in status {application.status!r}",
                    subject_type="application",
                    subject_id=application.id,
                )
            )

        evaluation = self._permits.current_evaluation(application.id)
        if evaluation is None:
            blockers.append(
                Blocker(
                    code="no_current_evaluation",
                    detail="the application has no current evaluation",
                    subject_type="application",
                    subject_id=application.id,
                )
            )
        else:
            if evaluation.stale:
                blockers.append(
                    Blocker(
                        code="evaluation_stale",
                        detail="the current evaluation is stale",
                        subject_type="evaluation",
                        subject_id=evaluation.id,
                    )
                )
            if decision.evaluation_id != evaluation.id:
                blockers.append(
                    Blocker(
                        code="decision_evaluation_mismatch",
                        detail="the decision does not refer to the current evaluation",
                        subject_type="decision",
                        subject_id=decision.id,
                    )
                )

        blockers.extend(self._permits.site_blockers(application))
        revision = self._permits.current_revision(application.id)
        inputs = build_inputs(dict(revision.snapshot or {}))
        blockers.extend(self._permits.credential_blockers(application, inputs, self._now))
        blockers.extend(self._permits.identity_link_blockers(application))
        blockers.extend(self._permits.finance_link_blockers(application))

        blockers.extend(self._assessment_blockers(application))
        blockers.extend(self._issue_blockers(application))
        return blockers

    def _assessment_blockers(self, application: permit.Application) -> list[Blocker]:
        """Return the financial conditions that block an issuance."""
        blockers: list[Blocker] = []
        assessment = self._finance.current_assessment(application.id)
        if assessment is None:
            return [
                Blocker(
                    code="no_current_assessment",
                    detail="the application has no payable assessment",
                    subject_type="application",
                    subject_id=application.id,
                )
            ]
        reconciliation = self._finance.compute_reconciliation(assessment, persist=False)
        if reconciliation.status != "exact":
            blockers.append(
                Blocker(
                    code=f"reconciliation_{reconciliation.status}",
                    detail=(
                        "the current reconciliation is "
                        f"{reconciliation.status!r}: assessed {reconciliation.assessed_total}, "
                        f"allocated {reconciliation.settled_allocated}, "
                        f"balance {reconciliation.balance}"
                    ),
                    subject_type="assessment",
                    subject_id=assessment.id,
                )
            )
        return blockers

    def _issue_blockers(self, application: permit.Application) -> list[Blocker]:
        """Return the open governance issues that block an issuance."""
        issues = self._session.execute(
            select(change.GovernanceIssue).where(
                change.GovernanceIssue.subject_type == "application",
                change.GovernanceIssue.subject_id == application.id,
                change.GovernanceIssue.status == "open",
                change.GovernanceIssue.blocking.is_(True),
            )
        ).scalars().all()
        return [
            Blocker(
                code="open_issue",
                detail=issue.description,
                subject_type="governance_issue",
                subject_id=issue.id,
            )
            for issue in issues
        ]

    # --------------------------------------------------------------- snapshot

    def _snapshot(
        self, application: permit.Application, decision: permit.Decision
    ) -> dict[str, Any]:
        """Return the immutable snapshot of the permit."""
        permit_type = self._permits.permit_type(application)
        revision = self._permits.current_revision(application.id)
        facts = dict(revision.snapshot or {})
        evaluation = self._permits.current_evaluation(application.id)
        assessment = self._finance.current_assessment(application.id)
        allocations = (
            []
            if assessment is None
            else list(
                self._session.execute(
                    select(finance.Allocation)
                    .where(
                        finance.Allocation.assessment_id == assessment.id,
                        finance.Allocation.status == "active",
                    )
                    .order_by(finance.Allocation.id)
                )
                .scalars()
                .all()
            )
        )
        allocation_rows = []
        for allocation in allocations:
            payment = self._session.execute(
                select(finance.Payment).where(finance.Payment.id == allocation.payment_id)
            ).scalar_one_or_none()
            allocation_rows.append(
                {
                    "allocation_id": allocation.id,
                    "payment_id": allocation.payment_id,
                    "source_transaction_id": (
                        None if payment is None else payment.source_transaction_id
                    ),
                    "amount_cents": allocation.amount_cents,
                    "currency": allocation.currency,
                }
            )

        applicant = self._session.execute(
            select(registry.Party).where(registry.Party.id == application.applicant_party_id)
        ).scalar_one_or_none()
        site = self._permits.site(application.id)
        site_text = None
        if site is not None and site.submitted_address_text:
            site_text = site.submitted_address_text
        elif site is not None and site.address_id:
            address = self._session.execute(
                select(registry.Address).where(registry.Address.id == site.address_id)
            ).scalar_one_or_none()
            site_text = None if address is None else address.source_string

        fee_lines: list[dict[str, Any]] = []
        assessed_total = 0
        assessment_block: dict[str, Any] = {}
        if assessment is not None:
            assessed_total = assessment.assessed_total_cents
            inputs = dict(assessment.input_versions or {})
            assessment_block = {
                "assessment_id": assessment.id,
                "version": assessment.version,
                "fee_schedule_id": inputs.get("fee_schedule_id"),
                "fee_schedule_version": inputs.get("fee_schedule_version"),
                "assessed_total_cents": assessment.assessed_total_cents,
                "currency": assessment.currency,
            }
            rows = self._session.execute(
                select(finance.AssessmentLine).where(
                    finance.AssessmentLine.assessment_id == assessment.id
                )
            ).scalars().all()
            rows = sorted(rows, key=_line_order)
            fee_lines = [
                {
                    "fee_code": line.fee_code,
                    "description": line.description,
                    "quantity": line.quantity,
                    "rate": format_cents(line.rate_cents),
                    "amount": format_cents(line.amount_cents),
                    "amount_cents": line.amount_cents,
                }
                for line in rows
            ]

        rules: list[dict[str, Any]] = []
        date_basis = ""
        if evaluation is not None:
            date_basis = evaluation.date_basis or ""
            for rule_id, version in dict(evaluation.rule_versions or {}).items():
                citation = ""
                for result in evaluation.results or []:
                    if result.get("rule_id") == rule_id:
                        citation = str(result.get("citation") or "")
                        break
                rules.append({"rule_id": rule_id, "version": version, "citation": citation})

        allocated_total = sum(row["amount_cents"] for row in allocation_rows)
        return {
            "permit_number": "",
            "application_number": application.source_application_number,
            "permit_type": permit_type.key,
            "issued_at": self._now.isoformat(),
            "status": "issued",
            "facts": {
                "project_description": facts.get("project_description"),
                "declared_valuation_cents": facts.get("valuation_cents"),
                "applicant_party_id": application.applicant_party_id,
                "organization_name": facts.get("organization_name"),
                "submitted_at": revision.submitted_at.isoformat(),
                "revision_number": revision.revision_number,
            },
            "applicant": None if applicant is None else applicant.display_name,
            "site": site_text,
            "decision": {
                "decision_id": decision.id,
                "outcome": decision.outcome,
                "decided_by_actor_id": decision.decided_by_actor_id,
                "decided_at": decision.decided_at.isoformat(),
                "reason": decision.reason,
                "evaluation_id": decision.evaluation_id,
            },
            "evaluation": {
                "evaluation_id": None if evaluation is None else evaluation.id,
                "rule_versions": dict(evaluation.rule_versions or {}) if evaluation else {},
                "date_basis": date_basis,
            },
            "dependencies": list(
                (dict(evaluation.source_versions or {}).get("dependencies") or [])
                if evaluation is not None
                else []
            ),
            "rules": rules,
            "assessment": assessment_block,
            "fee_lines": fee_lines,
            "assessed_total_cents": assessed_total,
            "allocated_total_cents": allocated_total,
            "allocations": allocation_rows,
            "fictional_demo": True,
        }

    def _permit_number(self) -> str:
        """Return the next fictional permit number."""
        count = self._session.execute(
            select(func.count()).select_from(permit.Permit)
        ).scalar_one()
        return f"ACME-{self._now.year}-{PERMIT_SEQUENCE_START + int(count):06d}"

    # ---------------------------------------------------------------- artifact

    def render_artifact(self, permit_id: str) -> bytes:
        """Return the printable artifact of one issued permit."""
        row = self._session.execute(
            select(permit.Permit).where(permit.Permit.id == permit_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that permit does not exist")
        return render_snapshot(row.snapshot or {})

    def view(self, row: permit.Permit) -> PermitView:
        """Return the view of one issued permit."""
        return PermitView(
            permit_id=row.id,
            application_id=row.application_id,
            decision_id=row.decision_id,
            permit_number=row.permit_number,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            status=row.status,
            artifact_hash=row.artifact_hash,
            issuance_command_key=row.issuance_command_key,
            issued_by_actor_id=row.issued_by_actor_id,
            snapshot=dict(row.snapshot or {}),
            fictional_demo=row.fictional_demo,
        )


def render_snapshot(snapshot: dict[str, Any]) -> bytes:
    """Return the artifact bytes of a permit snapshot.

    The rendering reads the snapshot alone, so the same snapshot always
    produces the same bytes.
    """
    decision = dict(snapshot.get("decision") or {})
    assessment = dict(snapshot.get("assessment") or {})
    facts = dict(snapshot.get("facts") or {})
    context = {
        "permit_number": snapshot.get("permit_number", ""),
        "issued_at": snapshot.get("issued_at", ""),
        "status": snapshot.get("status", "issued"),
        "permit_type": snapshot.get("permit_type", ""),
        "application_number": snapshot.get("application_number", ""),
        "project_description": facts.get("project_description") or "",
        "applicant": snapshot.get("applicant") or "",
        "site": snapshot.get("site") or "",
        "declared_valuation": (
            format_cents(int(facts.get("declared_valuation_cents") or 0))
        ),
        "decision_outcome": decision.get("outcome") or "",
        "decided_by": decision.get("decided_by_actor_id") or "",
        "decided_at": decision.get("decided_at") or "",
        "decision_reason": decision.get("reason") or "",
        "date_basis": (snapshot.get("evaluation") or {}).get("date_basis") or "",
        "rules": list(snapshot.get("rules") or []),
        "fee_schedule_id": assessment.get("fee_schedule_id") or "",
        "fee_schedule_version": assessment.get("fee_schedule_version") or "",
        "fee_lines": list(snapshot.get("fee_lines") or []),
        "assessed_total": format_cents(int(snapshot.get("assessed_total_cents") or 0)),
        "allocated_total": format_cents(int(snapshot.get("allocated_total_cents") or 0)),
        "artifact_hash": snapshot.get("artifact_hash", ""),
        "styles": artifact_styles(),
    }
    template = _environment().get_template("permit_artifact.html")
    return template.render(**context).encode("utf-8")


def render_permit_artifact(session: Session, permit_id: str) -> bytes:
    """Return the printable artifact of one issued permit."""
    return PermitIssuanceService(session).render_artifact(permit_id)


__all__ = [
    "ARTIFACT_STYLESHEET",
    "PERMIT_SEQUENCE_START",
    "IssuePermitCommand",
    "PermitIssuanceService",
    "PermitView",
    "artifact_styles",
    "fingerprint",
    "render_permit_artifact",
    "render_snapshot",
]

"""Fees, payments, allocations and reconciliation.

The finance service owns four separate boundaries:

* an assessment calculates a fee from approved inputs and the schedule that
  was in force on the recorded basis date,
* a reassessment creates a new version and carries the paid funds forward
  exactly once,
* a receipt keeps a stable identity while its settlement and reversal events
  are appended to its history, and
* an allocation is confirmed by Finance against an immutable assessment
  version.

Only an exact reconciliation of the current assessment version permits
issuance.
"""
# REQUIRES: FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, PER-06
# Fees are calculated deterministically with exact arithmetic, a reassessment
# is an explicit new version, receipts and allocations are idempotent and
# governed, and the reconciled position is shown with its evidence.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult
from acme_city.finance.calculator import (
    FIXED_FEE_CODE,
    VARIABLE_FEE_CODE,
    FeeAssessment,
    MoneyError,
    calculate_fee,
    format_cents,
    to_cents,
    validate_currency,
)
from acme_city.finance.schemas import (
    AllocationCommand,
    AllocationView,
    AssessmentCommand,
    AssessmentLineView,
    AssessmentView,
    PaymentEventCommand,
    PaymentEventView,
    PaymentView,
    ReassessmentCommand,
    ReconciliationCommand,
    ReconciliationView,
)
from acme_city.permits.guard import require_mutable
from acme_city.permits.service import PermitService
from acme_city.persistence.models import finance, permit, registry

#: The domain every finance action is authorized in.
FINANCE_DOMAIN = "finance"

#: The event types a source may report.
PAYMENT_EVENT_TYPES: tuple[str, ...] = ("received", "settled", "reversed", "failed")

#: The settlement status each event type produces.
EVENT_SETTLEMENT_STATUS: dict[str, str] = {
    "received": "unsettled",
    "settled": "settled",
    "reversed": "reversed",
    "failed": "failed",
}

#: The reconciled positions the demonstration reports.
RECONCILIATION_STATUSES: tuple[str, ...] = (
    "exact",
    "partial",
    "unpaid",
    "overpaid",
    "unmatched",
    "unsettled",
    "reversed",
    "currency_conflict",
    "allocation_conflict",
)


def _line_order(line: finance.AssessmentLine) -> tuple[int, str]:
    """Return the display order of one assessment line."""
    if line.fee_code == FIXED_FEE_CODE:
        return (0, line.fee_code)
    if line.fee_code == VARIABLE_FEE_CODE:
        return (1, line.fee_code)
    return (2, line.fee_code)


class FinanceService:
    """The governed financial boundary of the demonstration."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._permits = PermitService(session, now=self._now)

    # ------------------------------------------------------------- assessment

    def assess(
        self, command: AssessmentCommand, actor: ActorContext
    ) -> AssessmentView:
        """Assess the declared valuation of an application."""
        self._permissions.authorize(
            actor, "finance.assessment.create", ResourceContext(domain_id=FINANCE_DOMAIN)
        )
        application = self._permits.load_application(command.application_id)
        require_mutable(application, action="assessing the application")
        valuation_cents = self._valuation_cents(application, command.valuation)
        schedule, basis_at = self._fee_schedule(application)
        calculated = calculate_fee(
            schedule.definition or {},
            valuation_cents,
            currency=schedule.currency,
            fee_schedule_id=schedule.fee_schedule_id,
            version_label=schedule.version_label,
        )
        return self._write_assessment(
            application=application,
            schedule=schedule,
            basis_at=basis_at,
            calculated=calculated,
            valuation_cents=valuation_cents,
            actor=actor,
            action="finance.assessment.create",
            reason=command.reason,
            carry_forward=None,
        )

    def reassess(
        self, command: ReassessmentCommand, actor: ActorContext
    ) -> AssessmentView:
        """Assess the application again at a new valuation.

        The superseded assessment keeps its history, the active funds are
        carried forward exactly once, and the new version becomes the payable
        assessment.
        """
        self._permissions.authorize(
            actor, "finance.assessment.create", ResourceContext(domain_id=FINANCE_DOMAIN)
        )
        application = self._permits.load_application(command.application_id)
        require_mutable(application, action="assessing the application again")
        current = self.current_assessment(application.id)
        if current is None:
            raise ValidationError("the application has no assessment to reassess")
        valuation_cents = self._valuation_cents(application, command.valuation)
        schedule, basis_at = self._fee_schedule(application)
        calculated = calculate_fee(
            schedule.definition or {},
            valuation_cents,
            currency=schedule.currency,
            fee_schedule_id=schedule.fee_schedule_id,
            version_label=schedule.version_label,
        )
        return self._write_assessment(
            application=application,
            schedule=schedule,
            basis_at=basis_at,
            calculated=calculated,
            valuation_cents=valuation_cents,
            actor=actor,
            action="finance.assessment.reassess",
            reason=command.reason,
            carry_forward=bool(command.carry_forward),
        )

    def _write_assessment(
        self,
        *,
        application: permit.Application,
        schedule: finance.FeeScheduleVersion,
        basis_at: datetime,
        calculated: FeeAssessment,
        valuation_cents: int,
        actor: ActorContext,
        action: str,
        reason: str,
        carry_forward: bool | None,
    ) -> AssessmentView:
        """Write one assessment version and carry the funds forward."""
        previous = self.current_assessment(application.id)
        existing_versions = self._session.execute(
            select(func.count()).select_from(finance.Assessment).where(
                finance.Assessment.application_id == application.id
            )
        ).scalar_one()
        version = int(existing_versions) + 1
        billed_party_id = application.applicant_party_id
        assessment = finance.Assessment(
            id=new_id("assess"),
            application_id=application.id,
            billed_party_id=billed_party_id,
            fee_schedule_version_id=schedule.id,
            input_versions={
                "initial_submitted_at": (
                    application.initial_submitted_at.isoformat()
                    if application.initial_submitted_at
                    else None
                ),
                "declared_valuation_cents": valuation_cents,
                "fee_schedule_id": schedule.fee_schedule_id,
                "fee_schedule_version": schedule.version_label,
                "fee_schedule_version_row": schedule.id,
                "basis": "initial_submitted_at",
                "assessment_version": version,
                "supersedes": None if previous is None else previous.id,
            },
            assessed_total_cents=calculated.total_cents,
            currency=calculated.currency,
            status="current",
            version=version,
            correlation_id=application.correlation_id,
        )
        self._session.add(assessment)
        self._session.flush()
        for line in calculated.lines:
            self._session.add(
                finance.AssessmentLine(
                    id=new_id("line"),
                    assessment_id=assessment.id,
                    fee_code=line.fee_code,
                    description=line.description,
                    quantity=line.quantity,
                    rate_cents=line.rate_cents,
                    amount_cents=line.amount_cents,
                    currency=line.currency,
                    rule_version_id=line.rule_version_id,
                )
            )
        if previous is not None:
            # The superseded assessment keeps its version and its history.
            previous.status = "superseded"
            if carry_forward:
                self._carry_forward(previous, assessment, actor)
        self._session.flush()
        self._audit.append(
            action=action,
            actor=actor,
            target_type="assessment",
            target_id=assessment.id,
            after_version=assessment.version,
            reason=reason or None,
            references=[application.id],
            correlation_id=application.correlation_id,
            metadata={"assessed_total_cents": assessment.assessed_total_cents},
        )
        self._session.flush()
        return self.assessment_view(assessment)

    def _carry_forward(
        self,
        previous: finance.Assessment,
        current: finance.Assessment,
        actor: ActorContext,
    ) -> None:
        """Carry the active funds of a superseded assessment forward once.

        Each active allocation of the previous version is released and
        replaced by one allocation of the same amount against the new
        version.  The idempotency key of the carried-forward allocation
        names both versions, so a repeated reassessment never moves the same
        funds twice.
        """
        allocations = self._session.execute(
            select(finance.Allocation).where(
                finance.Allocation.assessment_id == previous.id,
                finance.Allocation.status == "active",
            )
        ).scalars().all()
        for allocation in allocations:
            key = f"{allocation.idempotency_key or allocation.id}:carry-forward:{current.id}"
            existing = self._session.execute(
                select(finance.Allocation).where(finance.Allocation.idempotency_key == key)
            ).scalar_one_or_none()
            if existing is not None:
                continue
            allocation.status = "released"
            allocation.version += 1
            self._session.add(
                finance.Allocation(
                    id=new_id("alloc"),
                    payment_id=allocation.payment_id,
                    assessment_id=current.id,
                    assessment_line_id=allocation.assessment_line_id,
                    amount_cents=allocation.amount_cents,
                    currency=allocation.currency,
                    status="active",
                    actor_id=actor.actor_id,
                    supersedes_allocation_id=allocation.id,
                    idempotency_key=key,
                )
            )

    def _valuation_cents(
        self, application: permit.Application, override: str | None
    ) -> int:
        """Return the valuation in cents, from the command or the revision."""
        if override is not None:
            try:
                return to_cents(override)
            except MoneyError as exc:
                raise ValidationError(str(exc)) from exc
        revision = self._permits.current_revision(application.id)
        snapshot = dict(revision.snapshot or {})
        if snapshot.get("valuation_cents") is not None:
            # The submitted revision already carries the valuation in cents.
            return int(snapshot["valuation_cents"])
        if snapshot.get("valuation") is not None:
            try:
                return to_cents(snapshot["valuation"])
            except MoneyError as exc:
                raise ValidationError(
                    "the declared valuation of the submitted revision is not an amount"
                ) from exc
        raise ValidationError("the application declares no valuation to assess")

    def _fee_schedule(
        self, application: permit.Application
    ) -> tuple[finance.FeeScheduleVersion, datetime]:
        """Return the fee schedule in force on the recorded basis date."""
        basis_at = application.initial_submitted_at or self._now
        schedule = self._session.execute(
            select(finance.FeeScheduleVersion)
            .where(
                finance.FeeScheduleVersion.status == "published",
                finance.FeeScheduleVersion.effective_from <= basis_at,
            )
            .order_by(finance.FeeScheduleVersion.effective_from)
        ).scalars().all()
        applicable = [
            row
            for row in schedule
            if row.effective_to is None or row.effective_to > basis_at
        ]
        if not applicable:
            raise ValidationError(
                "no published fee schedule is in force on the recorded basis date"
            )
        return applicable[-1], basis_at

    def current_assessment(self, application_id: str) -> finance.Assessment | None:
        """Return the payable assessment of an application."""
        return self._session.execute(
            select(finance.Assessment)
            .where(
                finance.Assessment.application_id == application_id,
                finance.Assessment.status == "current",
            )
            .order_by(finance.Assessment.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def assessment_view(self, assessment: finance.Assessment) -> AssessmentView:
        """Return the view of one stored assessment."""
        lines = self._session.execute(
            select(finance.AssessmentLine).where(
                finance.AssessmentLine.assessment_id == assessment.id
            )
        ).scalars().all()
        # The lines are returned in the order of the schedule: the fixed
        # charge, then the valuation charge, then any other charge.
        lines = sorted(lines, key=_line_order)
        inputs = dict(assessment.input_versions or {})
        return AssessmentView(
            assessment_id=assessment.id,
            application_id=assessment.application_id,
            version=assessment.version,
            billed_party_id=assessment.billed_party_id,
            fee_schedule_id=str(inputs.get("fee_schedule_id") or ""),
            fee_schedule_version=str(inputs.get("fee_schedule_version") or ""),
            assessed_total_cents=assessment.assessed_total_cents,
            assessed_total=format_cents(assessment.assessed_total_cents),
            currency=assessment.currency,
            status=assessment.status,
            lines=[
                AssessmentLineView(
                    line_id=line.id,
                    fee_code=line.fee_code,
                    description=line.description,
                    quantity=line.quantity,
                    rate_cents=line.rate_cents,
                    amount_cents=line.amount_cents,
                    amount=format_cents(line.amount_cents),
                    currency=line.currency,
                    rule_version_id=line.rule_version_id,
                )
                for line in lines
            ],
            input_versions=inputs,
            created_at=assessment.created_at,
        )

    # --------------------------------------------------------------- payments

    def import_payment(
        self, command: PaymentEventCommand, actor: ActorContext
    ) -> PaymentView | ConflictResult:
        """Import one simulated ERP payment event.

        The same event delivered twice returns the same receipt.  The same
        event identifier with different facts is a conflict.
        """
        self._permissions.authorize(
            actor, "finance.payment.import", ResourceContext(domain_id=FINANCE_DOMAIN)
        )
        event_type = str(command.event_type or "").strip().lower()
        if event_type not in PAYMENT_EVENT_TYPES:
            raise ValidationError(
                f"unsupported payment event type: {command.event_type!r}; use one of "
                + ", ".join(PAYMENT_EVENT_TYPES)
            )
        try:
            currency = validate_currency(command.currency)
            amount_cents = to_cents(command.amount)
        except MoneyError as exc:
            raise ValidationError(str(exc)) from exc
        occurred_at = command.occurred_at or self._now

        existing_event = self._session.execute(
            select(finance.PaymentEvent).where(
                finance.PaymentEvent.source_event_id == command.source_event_id
            )
        ).scalar_one_or_none()
        if existing_event is not None:
            if (
                existing_event.amount_cents != amount_cents
                or existing_event.currency != currency
                or existing_event.event_type != event_type
            ):
                return ConflictResult(
                    code="payment_event_conflict",
                    differences=(
                        {
                            "source_event_id": command.source_event_id,
                            "stored_amount_cents": existing_event.amount_cents,
                            "requested_amount_cents": amount_cents,
                            "stored_currency": existing_event.currency,
                            "requested_currency": currency,
                            "stored_event_type": existing_event.event_type,
                            "requested_event_type": event_type,
                        },
                    ),
                )
            payment = self._payment(existing_event.payment_id)
            assert payment is not None
            return self.payment_view(payment)

        payment = self._session.execute(
            select(finance.Payment).where(
                finance.Payment.source_transaction_id == command.source_transaction_id
            )
        ).scalar_one_or_none()
        if payment is None:
            payment = finance.Payment(
                id=new_id("payment"),
                source_transaction_id=command.source_transaction_id,
                source_system_id=command.source_system_id,
                source_event_id=command.source_event_id,
                source_event_version=command.source_event_version,
                payer_account_id=command.payer_account_id,
                party_id=command.party_id,
                paid_at=None if event_type == "received" else occurred_at,
                amount_cents=amount_cents,
                currency=currency,
                settlement_status=EVENT_SETTLEMENT_STATUS[event_type],
            )
            self._session.add(payment)
            self._session.flush()
        else:
            if payment.currency != currency:
                return ConflictResult(
                    code="payment_currency_conflict",
                    differences=(
                        {
                            "source_transaction_id": payment.source_transaction_id,
                            "stored_currency": payment.currency,
                            "requested_currency": currency,
                        },
                    ),
                )
            payment.source_event_id = command.source_event_id
            payment.source_event_version = command.source_event_version
            if command.payer_account_id:
                payment.payer_account_id = command.payer_account_id
            if command.party_id:
                payment.party_id = command.party_id
            if event_type != "received":
                payment.paid_at = occurred_at
                payment.amount_cents = amount_cents
            payment.settlement_status = EVENT_SETTLEMENT_STATUS[event_type]
            payment.version += 1

        self._session.add(
            finance.PaymentEvent(
                id=new_id("payeve"),
                payment_id=payment.id,
                source_event_id=command.source_event_id,
                source_event_version=command.source_event_version,
                event_type=event_type,
                amount_cents=amount_cents,
                currency=currency,
                occurred_at=occurred_at,
                payload={
                    "source_system_id": command.source_system_id,
                    "source_transaction_id": command.source_transaction_id,
                },
            )
        )
        self._session.flush()
        self._audit.append(
            action="finance.payment.import",
            actor=actor,
            target_type="payment",
            target_id=payment.id,
            after_version=payment.version,
            reason=command.reason or None,
            references=[payment.source_transaction_id, command.source_event_id],
            metadata={"event_type": event_type, "amount_cents": amount_cents},
        )
        if event_type == "reversed":
            self._flag_issued_permits(payment, actor)
        self._session.flush()
        return self.payment_view(payment)

    def _payment(self, payment_id: str) -> finance.Payment | None:
        """Return one stored receipt."""
        return self._session.execute(
            select(finance.Payment).where(finance.Payment.id == payment_id)
        ).scalar_one_or_none()

    def payment_view(self, payment: finance.Payment) -> PaymentView:
        """Return the view of one stored receipt."""
        events = self._session.execute(
            select(finance.PaymentEvent)
            .where(finance.PaymentEvent.payment_id == payment.id)
            .order_by(
                finance.PaymentEvent.occurred_at,
                finance.PaymentEvent.created_at,
                finance.PaymentEvent.id,
            )
        ).scalars().all()
        return PaymentView(
            payment_id=payment.id,
            source_transaction_id=payment.source_transaction_id,
            source_system_id=payment.source_system_id,
            payer_account_id=payment.payer_account_id,
            party_id=payment.party_id,
            paid_at=payment.paid_at,
            amount_cents=payment.amount_cents,
            amount=format_cents(payment.amount_cents),
            currency=payment.currency,
            settlement_status=payment.settlement_status,
            events=[
                PaymentEventView(
                    event_id=event.id,
                    source_event_id=event.source_event_id,
                    source_event_version=event.source_event_version,
                    event_type=event.event_type,
                    amount_cents=event.amount_cents,
                    amount=format_cents(event.amount_cents),
                    currency=event.currency,
                    occurred_at=event.occurred_at,
                )
                for event in events
            ],
        )

    def _flag_issued_permits(self, payment: finance.Payment, actor: ActorContext) -> None:
        """Open an impact review for every issued permit that used a receipt.

        A reversal never cancels an issued permit silently; it opens the
        impact review that the amendment route works from.
        """
        allocations = self._session.execute(
            select(finance.Allocation).where(
                finance.Allocation.payment_id == payment.id,
                finance.Allocation.status == "active",
            )
        ).scalars().all()
        for allocation in allocations:
            assessment = self._session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.id == allocation.assessment_id
                )
            ).scalar_one_or_none()
            if assessment is None:
                continue
            permit_row = self._session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == assessment.application_id
                )
            ).scalar_one_or_none()
            if permit_row is None:
                continue
            self._open_impact_review(permit_row, payment, actor)

    def _open_impact_review(
        self, permit_row: permit.Permit, payment: finance.Payment, actor: ActorContext
    ) -> None:
        """Open one impact review for a reversed receipt on an issued permit."""
        reason = (
            f"The receipt {payment.source_transaction_id} was reversed. The issued permit "
            f"{permit_row.permit_number} keeps its snapshot and needs an impact review."
        )
        existing = self._session.execute(
            select(permit.ImpactReview).where(
                permit.ImpactReview.target_type == "permit",
                permit.ImpactReview.target_id == permit_row.id,
                permit.ImpactReview.status == "open",
            )
        ).scalars().all()
        for review in existing:
            if review.reason == reason:
                return
        self._session.add(
            permit.ImpactReview(
                id=new_id("impact"),
                target_type="permit",
                target_id=permit_row.id,
                reason=reason,
                assigned_actor_id="persona_permit_reviewer",
                status="open",
            )
        )

    # ------------------------------------------------------------- allocations

    def allocate(
        self, command: AllocationCommand, actor: ActorContext
    ) -> AllocationView | ConflictResult:
        """Confirm an allocation of settled funds to an assessment version."""
        self._permissions.authorize(
            actor, "finance.allocation.confirm", ResourceContext(domain_id=FINANCE_DOMAIN)
        )
        try:
            currency = validate_currency(command.currency)
            amount_cents = to_cents(command.amount)
        except MoneyError as exc:
            raise ValidationError(str(exc)) from exc

        existing = self._session.execute(
            select(finance.Allocation).where(
                finance.Allocation.idempotency_key == command.idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.payment_id != command.payment_id
                or existing.assessment_id != command.assessment_id
                or existing.amount_cents != amount_cents
                or existing.currency != currency
            ):
                return ConflictResult(
                    code="allocation_conflict",
                    differences=(
                        {
                            "idempotency_key": command.idempotency_key,
                            "stored_payment_id": existing.payment_id,
                            "stored_assessment_id": existing.assessment_id,
                            "stored_amount_cents": existing.amount_cents,
                            "requested_amount_cents": amount_cents,
                        },
                    ),
                )
            return self.allocation_view(existing)

        payment = self._payment(command.payment_id)
        if payment is None:
            raise NotFoundError("that receipt does not exist")
        assessment = self._session.execute(
            select(finance.Assessment).where(finance.Assessment.id == command.assessment_id)
        ).scalar_one_or_none()
        if assessment is None:
            raise NotFoundError("that assessment does not exist")
        assessed = self._permits.load_application(assessment.application_id)
        require_mutable(assessed, action="allocating a payment to the assessment")
        if assessment.status != "current":
            raise ValidationError(
                "only the payable assessment version may receive an allocation"
            )
        if payment.settlement_status != "settled":
            raise ValidationError(
                f"the receipt {payment.source_transaction_id} is {payment.settlement_status} "
                "and may not be allocated"
            )
        if currency != assessment.currency or currency != payment.currency:
            raise ValidationError(
                "the allocation currency must match both the assessment and the receipt"
            )
        if not self._payer_is_linked(payment, assessment):
            raise ValidationError(
                "the payer of the receipt is not linked by an approved decision to the "
                "billed party"
            )
        available = self._available_funds(payment.id)
        if amount_cents > available:
            raise ValidationError(
                f"only {format_cents(available)} of the receipt is still available"
            )

        allocation = finance.Allocation(
            id=new_id("alloc"),
            payment_id=payment.id,
            assessment_id=assessment.id,
            amount_cents=amount_cents,
            currency=currency,
            status="active",
            actor_id=actor.actor_id,
            idempotency_key=command.idempotency_key,
        )
        self._session.add(allocation)
        self._session.flush()
        self._audit.append(
            action="finance.allocation.confirm",
            actor=actor,
            target_type="allocation",
            target_id=allocation.id,
            after_version=allocation.version,
            reason=command.reason or None,
            references=[payment.id, assessment.id],
            metadata={"amount_cents": amount_cents},
        )
        self._session.flush()
        return self.allocation_view(allocation)

    def _available_funds(self, payment_id: str) -> int:
        """Return the settled funds of a receipt that are not yet allocated."""
        payment = self._payment(payment_id)
        if payment is None:
            return 0
        allocated = self._session.execute(
            select(func.coalesce(func.sum(finance.Allocation.amount_cents), 0)).where(
                finance.Allocation.payment_id == payment_id,
                finance.Allocation.status == "active",
            )
        ).scalar_one()
        return int(payment.amount_cents) - int(allocated)

    def _payer_is_linked(
        self, payment: finance.Payment, assessment: finance.Assessment
    ) -> bool:
        """Return whether the payer of a receipt is linked to the billed party."""
        if assessment.billed_party_id is None:
            return False
        if payment.party_id == assessment.billed_party_id:
            return True
        if payment.payer_account_id is None:
            return False
        account = self._session.execute(
            select(registry.FinanceAccount).where(
                registry.FinanceAccount.account_id == payment.payer_account_id
            )
        ).scalar_one_or_none()
        if account is None:
            return False
        if account.party_id == assessment.billed_party_id and account.link_status == "approved":
            return True
        link = self._session.execute(
            select(finance.FinanceAccountLink).where(
                finance.FinanceAccountLink.account_id == account.account_id,
                finance.FinanceAccountLink.party_id == assessment.billed_party_id,
                finance.FinanceAccountLink.link_status == "approved",
            )
        ).scalar_one_or_none()
        return link is not None

    def allocation_view(self, allocation: finance.Allocation) -> AllocationView:
        """Return the view of one stored allocation."""
        return AllocationView(
            allocation_id=allocation.id,
            payment_id=allocation.payment_id,
            assessment_id=allocation.assessment_id,
            amount_cents=allocation.amount_cents,
            amount=format_cents(allocation.amount_cents),
            currency=allocation.currency,
            status=allocation.status,
            actor_id=allocation.actor_id,
            idempotency_key=allocation.idempotency_key,
            supersedes_allocation_id=allocation.supersedes_allocation_id,
        )

    # ---------------------------------------------------------- reconciliation

    def reconcile(
        self, command: ReconciliationCommand, actor: ActorContext
    ) -> ReconciliationView:
        """Reconcile one assessment version against its receipts."""
        self._permissions.authorize(
            actor, "finance.allocation.confirm", ResourceContext(domain_id=FINANCE_DOMAIN)
        )
        assessment = self._session.execute(
            select(finance.Assessment).where(finance.Assessment.id == command.assessment_id)
        ).scalar_one_or_none()
        if assessment is None:
            raise NotFoundError("that assessment does not exist")
        return self.compute_reconciliation(assessment, command.payment_ids, actor)

    def compute_reconciliation(
        self,
        assessment: finance.Assessment,
        payment_ids: list[str] | None = None,
        actor: ActorContext | None = None,
        *,
        persist: bool = True,
    ) -> ReconciliationView:
        """Return the reconciled position of an assessment version.

        The receipts that support the reconciliation are the ones that were
        allocated to the assessment and the ones the caller presents.

        Args:
            assessment: The assessment version to reconcile.
            payment_ids: Receipts the caller presents as supporting the
                reconciliation.
            actor: The actor the computation is recorded for.
            persist: Whether the result is written as a reconciliation
                record.  A check that only reads the current position passes
                ``False``.
        """
        allocations = self._session.execute(
            select(finance.Allocation)
            .where(
                finance.Allocation.assessment_id == assessment.id,
                finance.Allocation.status == "active",
            )
            .order_by(finance.Allocation.id)
        ).scalars().all()
        settled = 0
        evidence: list[str] = []
        exception: str | None = None
        status = "unpaid"

        receipts: dict[str, finance.Payment] = {}
        for allocation in allocations:
            payment = self._payment(allocation.payment_id)
            if payment is None:
                continue
            receipts[payment.id] = payment
            evidence.append(f"allocation:{allocation.id}")
            if allocation.currency != assessment.currency:
                exception = exception or "currency_conflict"
                continue
            if payment.settlement_status == "reversed":
                exception = exception or "reversed"
                continue
            if payment.settlement_status != "settled":
                exception = exception or "unsettled"
                continue
            if not self._payer_is_linked(payment, assessment):
                exception = exception or "unmatched"
                continue
            settled += allocation.amount_cents
            evidence.append(f"payment:{payment.source_transaction_id}")

        for payment_id in payment_ids or []:
            payment = self._payment(payment_id)
            if payment is None:
                raise NotFoundError("that receipt does not exist")
            receipts.setdefault(payment.id, payment)
            if payment.settlement_status == "reversed":
                exception = exception or "reversed"
            elif payment.settlement_status != "settled":
                exception = exception or "unsettled"
            elif payment.currency != assessment.currency:
                exception = exception or "currency_conflict"
            elif not self._payer_is_linked(payment, assessment):
                exception = exception or "unmatched"
            else:
                evidence.append(f"payment:{payment.source_transaction_id}")

        over_allocated = self._over_allocated(allocations)
        if over_allocated:
            exception = exception or "allocation_conflict"

        balance = assessment.assessed_total_cents - settled
        if exception is not None:
            status = exception
        elif balance == 0:
            status = "exact"
        elif balance > 0:
            status = "partial" if allocations else "unpaid"
        else:
            status = "overpaid"

        result = finance.ReconciliationResult(
            id=new_id("recon"),
            assessment_id=assessment.id,
            assessed_total_cents=assessment.assessed_total_cents,
            settled_allocated_cents=settled,
            balance_cents=balance,
            currency=assessment.currency,
            status=status,
            exception=exception,
            computed_at=self._now,
            evidence_refs=evidence,
        )
        if not persist:
            return ReconciliationView(
                assessment_id=assessment.id,
                application_id=assessment.application_id,
                assessed_total_cents=assessment.assessed_total_cents,
                assessed_total=format_cents(assessment.assessed_total_cents),
                settled_allocated_cents=settled,
                settled_allocated=format_cents(settled),
                balance_cents=balance,
                balance=format_cents(balance),
                currency=assessment.currency,
                status=status,
                exception=exception,
                evidence_refs=evidence,
                computed_at=result.computed_at,
            )
        self._session.add(result)
        self._session.flush()
        if actor is not None:
            self._audit.append(
                action="finance.reconciliation.compute",
                actor=actor,
                target_type="reconciliation",
                target_id=result.id,
                references=[assessment.id],
                metadata={"status": status, "exception": exception},
            )
            self._session.flush()
        return ReconciliationView(
            assessment_id=assessment.id,
            application_id=assessment.application_id,
            assessed_total_cents=assessment.assessed_total_cents,
            assessed_total=format_cents(assessment.assessed_total_cents),
            settled_allocated_cents=settled,
            settled_allocated=format_cents(settled),
            balance_cents=balance,
            balance=format_cents(balance),
            currency=assessment.currency,
            status=status,
            exception=exception,
            evidence_refs=evidence,
            computed_at=result.computed_at,
        )

    def _over_allocated(self, allocations: list[finance.Allocation]) -> bool:
        """Return whether a receipt has more allocated than it holds."""
        by_payment: dict[str, int] = {}
        for allocation in allocations:
            by_payment[allocation.payment_id] = (
                by_payment.get(allocation.payment_id, 0) + allocation.amount_cents
            )
        for payment_id, total in by_payment.items():
            payment = self._payment(payment_id)
            if payment is not None and total > payment.amount_cents:
                return True
        return False

    def latest_reconciliation(
        self, assessment_id: str
    ) -> finance.ReconciliationResult | None:
        """Return the most recent reconciliation of an assessment."""
        return self._session.execute(
            select(finance.ReconciliationResult)
            .where(finance.ReconciliationResult.assessment_id == assessment_id)
            .order_by(finance.ReconciliationResult.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()


__all__ = [
    "EVENT_SETTLEMENT_STATUS",
    "FINANCE_DOMAIN",
    "PAYMENT_EVENT_TYPES",
    "RECONCILIATION_STATUSES",
    "FinanceService",
]

"""Command and view models for fees, payments, allocations and reconciliation.

Amounts cross the service boundary as decimal strings and are stored as
integer cents.  A currency is always explicit: two currencies are never
added together.
"""
# REQUIRES: FIN-01, FIN-02, FIN-03, FIN-04, FIN-05
# A fee is calculated from approved inputs, a reassessment creates a new
# version, a receipt keeps a stable identity and an allocation is confirmed
# against an immutable assessment version.

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinanceModel(BaseModel):
    """A model that ignores unknown request fields."""

    model_config = ConfigDict(extra="ignore")


class AssessmentCommand(FinanceModel):
    """Assess the declared valuation of an application."""

    application_id: str
    valuation: str | None = None
    reason: str = ""
    expected_application_version: int | None = None


class ReassessmentCommand(AssessmentCommand):
    """Reassess an application at a new valuation.

    The active funds of the superseded assessment are carried forward once,
    in the same transaction as the new version.
    """

    carry_forward: bool = True


class AssessmentLineView(FinanceModel):
    """One itemized line of an assessment."""

    line_id: str
    fee_code: str
    description: str
    quantity: str
    rate_cents: int
    amount_cents: int
    amount: str
    currency: str = "USD"
    rule_version_id: str | None = None


class AssessmentView(FinanceModel):
    """A versioned fee assessment."""

    assessment_id: str
    application_id: str
    version: int = 1
    billed_party_id: str | None = None
    fee_schedule_id: str = ""
    fee_schedule_version: str = ""
    assessed_total_cents: int = 0
    assessed_total: str = "0.00"
    currency: str = "USD"
    status: str = "current"
    lines: list[AssessmentLineView] = Field(default_factory=list)
    input_versions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class PaymentEventCommand(FinanceModel):
    """Import one simulated ERP payment event."""

    source_transaction_id: str
    source_event_id: str
    event_type: str = "received"
    amount: str
    currency: str = "USD"
    source_event_version: str | None = None
    source_system_id: str = "erp_finance"
    payer_account_id: str | None = None
    party_id: str | None = None
    occurred_at: datetime | None = None
    reason: str = ""


class PaymentEventView(FinanceModel):
    """One appended source event of a receipt."""

    event_id: str
    source_event_id: str
    source_event_version: str | None = None
    event_type: str
    amount_cents: int
    amount: str
    currency: str = "USD"
    occurred_at: datetime


class PaymentView(FinanceModel):
    """A stable receipt identity with its event history."""

    payment_id: str
    source_transaction_id: str
    source_system_id: str = "erp_finance"
    payer_account_id: str | None = None
    party_id: str | None = None
    paid_at: datetime | None = None
    amount_cents: int = 0
    amount: str = "0.00"
    currency: str = "USD"
    settlement_status: str = "unsettled"
    events: list[PaymentEventView] = Field(default_factory=list)


class AllocationCommand(FinanceModel):
    """Confirm an allocation of settled funds to an assessment version."""

    payment_id: str
    assessment_id: str
    amount: str
    currency: str = "USD"
    idempotency_key: str
    reason: str = ""


class AllocationView(FinanceModel):
    """One confirmed allocation."""

    allocation_id: str
    payment_id: str
    assessment_id: str
    amount_cents: int
    amount: str
    currency: str = "USD"
    status: str = "active"
    actor_id: str | None = None
    idempotency_key: str | None = None
    supersedes_allocation_id: str | None = None


class ReconciliationCommand(FinanceModel):
    """Reconcile an assessment version against its receipts."""

    assessment_id: str
    payment_ids: list[str] = Field(default_factory=list)


class ReconciliationView(FinanceModel):
    """The reconciled position of one assessment version."""

    assessment_id: str
    application_id: str
    assessed_total_cents: int = 0
    assessed_total: str = "0.00"
    settled_allocated_cents: int = 0
    settled_allocated: str = "0.00"
    balance_cents: int = 0
    balance: str = "0.00"
    currency: str = "USD"
    status: str = "open"
    exception: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    computed_at: datetime | None = None


__all__ = [
    "AllocationCommand",
    "AllocationView",
    "AssessmentCommand",
    "AssessmentLineView",
    "AssessmentView",
    "FinanceModel",
    "PaymentEventCommand",
    "PaymentEventView",
    "PaymentView",
    "ReassessmentCommand",
    "ReconciliationCommand",
    "ReconciliationView",
]

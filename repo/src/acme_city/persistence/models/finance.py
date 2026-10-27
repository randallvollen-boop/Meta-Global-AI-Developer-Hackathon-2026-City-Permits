"""Rule, fee and financial objects.

Money is stored as integer cents with an explicit ISO currency.  Allocations
reference an immutable assessment version or line; superseded allocations stay
in history and are excluded from current balances.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class RuleVersion(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """One published definition of an executable rule.

    The same version supplies retrieval, deterministic execution and the
    citation that is displayed.
    """

    __tablename__ = "rule_versions"

    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_type_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("permit_types.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False, default="executable")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    citation: Mapped[str] = mapped_column(String(120), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(160), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(32), nullable=True)
    limit_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    on_violate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    approver_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("rule_id", "effective_from"),
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'published', 'retired')",
            name="status_allowed",
        ),
    )


class FeeScheduleVersion(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A versioned fictional fee schedule."""

    __tablename__ = "fee_schedule_versions"

    fee_schedule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    approver_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    __table_args__ = (
        UniqueConstraint("fee_schedule_id", "version_label"),
        CheckConstraint("length(currency) = 3", name="currency_is_iso"),
    )


class Assessment(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A versioned fee assessment of an application."""

    __tablename__ = "assessments"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    billed_party_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True
    )
    fee_schedule_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("fee_schedule_versions.id", ondelete="RESTRICT"), nullable=False
    )
    input_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    assessed_total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (CheckConstraint("length(currency) = 3", name="currency_is_iso"),)


class AssessmentLine(IdMixin, CreatedAtMixin, Base):
    """One itemized line of an assessment."""

    __tablename__ = "assessment_lines"

    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fee_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[str] = mapped_column(String(64), nullable=False, default="1")
    rate_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    rule_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("rule_versions.id", ondelete="SET NULL"), nullable=True
    )


class Payment(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A stable receipt identity.  Settlement and reversal append history."""

    __tablename__ = "payments"

    source_transaction_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False, default="erp_finance")
    source_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    source_event_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payer_account_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("finance_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    party_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    settlement_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unsettled"
    )
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_is_iso"),
        CheckConstraint(
            "settlement_status IN ('unsettled', 'settled', 'reversed', 'failed')",
            name="settlement_status_allowed",
        ),
    )


class PaymentEvent(IdMixin, CreatedAtMixin, Base):
    """An immutable source event for a receipt."""

    __tablename__ = "payment_events"

    payment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    source_event_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Allocation(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A confirmed allocation of settled funds to an immutable assessment."""

    __tablename__ = "allocations"

    payment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assessment_line_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("assessment_lines.id", ondelete="SET NULL"), nullable=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supersedes_allocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_is_iso"),
        CheckConstraint(
            "status IN ('active', 'released', 'superseded', 'reversed')", name="status_allowed"
        ),
    )


class ReconciliationResult(IdMixin, CreatedAtMixin, Base):
    """A derived financial result with traceable evidence."""

    __tablename__ = "reconciliation_results"

    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessed_total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_allocated_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    exception: Mapped[str | None] = mapped_column(String(64), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (CheckConstraint("length(currency) = 3", name="currency_is_iso"),)


class FinanceAccountLink(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """The recorded decision that links an ERP account to a canonical party."""

    __tablename__ = "finance_account_links"

    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("finance_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    link_status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved")
    decided_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "link_status IN ('proposed', 'approved', 'rejected', 'superseded')",
            name="link_status_allowed",
        ),
    )


__all__ = [
    "Allocation",
    "Assessment",
    "AssessmentLine",
    "FeeScheduleVersion",
    "FinanceAccountLink",
    "Payment",
    "PaymentEvent",
    "ReconciliationResult",
    "RuleVersion",
]

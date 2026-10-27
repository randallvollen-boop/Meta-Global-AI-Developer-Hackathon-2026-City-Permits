"""The simulated ERP/Finance source.

ERP/Finance owns the business licences, the finance accounts, the financial
records and the payment receipt events.  A settled or reversed receipt is
append-only: a correction is a later event, never a rewrite of the receipt.
"""
# REQUIRES: EDIT-01, CHG-02, FIN-03
# The ERP/Finance adapter keeps settled and reversed receipts append-only and
# answers with an explicit acknowledgement.

from __future__ import annotations

from acme_city.adapters.sources.base import (
    SourceAcknowledgement,
    SourceAdapter,
    SourceCommand,
    register_adapter,
)

#: The receipt events that may never be rewritten in place.
APPEND_ONLY_EVENT_TYPES: frozenset[str] = frozenset({"settled", "reversed"})


@register_adapter
class ErpFinanceAdapter(SourceAdapter):
    """The local stand-in for the fictional ERP/Finance system."""

    source_system_id = "erp_finance"
    label = "ERP/Finance (simulated)"
    dataset_keys = (
        "business_licensing_register",
        "finance_accounts",
        "financial_records",
        "payment_events",
    )

    def refuse(self, command: SourceCommand, current: object) -> SourceAcknowledgement | None:
        """Refuse a rewrite of a settled or reversed receipt."""
        if command.dataset_key != "payment_events":
            return None
        current_payload = getattr(current, "raw_payload", None) or {}
        event_type = str(current_payload.get("event_type", "")).strip().lower()
        if event_type not in APPEND_ONLY_EVENT_TYPES:
            return None
        return SourceAcknowledgement(
            source_system_id=command.source_system_id,
            dataset_key=command.dataset_key,
            record_id=command.record_id,
            status="rejected",
            source_record_version=(
                getattr(current, "source_record_version", None) if current else None
            ),
            expected_version=command.expected_version,
            message=(
                f"a {event_type} receipt is append-only; a correction is a later event"
            ),
            details={"reason": "append_only_receipt", "event_type": event_type},
        )


__all__ = ["APPEND_ONLY_EVENT_TYPES", "ErpFinanceAdapter"]

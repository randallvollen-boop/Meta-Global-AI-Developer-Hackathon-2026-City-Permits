"""The simulated GIS source.

GIS owns the official parcels, the official addresses with their unit
distinctions, and the zoning facts.  A GIS record keeps its business effective
window; a newer version never silently replaces the older one.
"""
# REQUIRES: EDIT-01, CHG-02, MDM-03
# The GIS adapter writes a new version of its own record and keeps the unit
# distinction of an address intact.

from __future__ import annotations

from acme_city.adapters.sources.base import (
    SourceAcknowledgement,
    SourceAdapter,
    SourceCommand,
    register_adapter,
)


@register_adapter
class GisAdapter(SourceAdapter):
    """The local stand-in for the fictional GIS system."""

    source_system_id = "gis"
    label = "GIS (simulated)"
    dataset_keys = ("parcel_register", "address_register", "zoning_register")

    def refuse(self, command: SourceCommand, current: object) -> SourceAcknowledgement | None:
        """Refuse a change that would drop a unit distinction.

        An official address that carries a unit keeps it.  Removing the unit
        would merge two separate places into one.
        """
        if command.dataset_key != "address_register":
            return None
        payload = dict(command.payload or {})
        current_payload = getattr(current, "raw_payload", None) or {}
        if not str(current_payload.get("unit_number", "")).strip():
            return None
        if not str(payload.get("unit_number", "")).strip():
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="rejected",
                source_record_version=(
                    getattr(current, "source_record_version", None) if current else None
                ),
                expected_version=command.expected_version,
                message="an official address keeps its unit distinction",
                details={"reason": "unit_distinction_required"},
            )
        return None


__all__ = ["GisAdapter"]

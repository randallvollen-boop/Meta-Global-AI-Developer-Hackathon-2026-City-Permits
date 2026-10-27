"""The simulated Permitting source.

Permitting owns the applicant profiles, the permit applications, the immutable
application revisions, the contractor register, the review decisions and the
issued permits.  It answers for its own records only.
"""
# REQUIRES: EDIT-01, CHG-02
# The Permitting adapter writes a new version of its own record and answers with
# an explicit acknowledgement. It never writes a canonical identity or a decision
# of the registry.

from __future__ import annotations

from acme_city.adapters.sources.base import (
    SourceAcknowledgement,
    SourceAdapter,
    SourceCommand,
    register_adapter,
)


@register_adapter
class PermittingAdapter(SourceAdapter):
    """The local stand-in for the fictional Permitting system."""

    source_system_id = "permitting"
    label = "Permitting (simulated)"
    dataset_keys = (
        "applicant_profiles",
        "applications_and_permits",
        "application_revisions",
        "contractor_register",
        "permit_decisions",
        "issued_permits",
    )

    def refuse(
        self, command: SourceCommand, current: object
    ) -> SourceAcknowledgement | None:
        """Refuse a change to an issued permit.

        An issued permit is an immutable record.  A later change opens review
        work; it never rewrites the issued record.
        """
        if command.dataset_key != "issued_permits":
            return None
        payload = current.raw_payload if getattr(current, "raw_payload", None) else {}
        if str(payload.get("status", "")) == "revoked":
            return SourceAcknowledgement(
                source_system_id=command.source_system_id,
                dataset_key=command.dataset_key,
                record_id=command.record_id,
                status="rejected",
                source_record_version=(
                    getattr(current, "source_record_version", None) if current else None
                ),
                expected_version=command.expected_version,
                message="a revoked issued permit is not changed in place",
                details={"reason": "issued_record_immutable"},
            )
        return None


__all__ = ["PermittingAdapter"]

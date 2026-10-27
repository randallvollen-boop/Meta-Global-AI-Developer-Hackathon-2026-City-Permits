"""The simulated ACME ePermit Portal source.

The portal is the fictional outside application the city uses to gather
permits before they reach this system: a web portal plus the counter/paper
and email channels staff transcribe into it.  It owns only its submitted
applications; ingestion turns each one into a Permitting application.
"""
# REQUIRES: EDIT-01, CHG-02
# The intake portal adapter writes a new version of its own record and answers
# with an explicit acknowledgement. It never writes a canonical identity, a
# permit application or a decision.

from __future__ import annotations

from acme_city.adapters.sources.base import (
    SourceAdapter,
    register_adapter,
)


@register_adapter
class IntakePortalAdapter(SourceAdapter):
    """The local stand-in for the fictional outside intake portal."""

    source_system_id = "intake_portal"
    label = "ACME ePermit Portal (simulated)"
    dataset_keys = ("submitted_applications",)


__all__ = ["IntakePortalAdapter"]

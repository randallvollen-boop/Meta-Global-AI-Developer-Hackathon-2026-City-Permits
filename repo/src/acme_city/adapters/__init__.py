"""The simulated source adapters.

An adapter is the local stand-in for one source system.  It owns the source
records of its own datasets and their versions; it never writes a canonical
identity, a decision, a fee or a permit.
"""
# REQUIRES: EDIT-01, CHG-02, ING-03
# The adapters are explicitly labeled simulated, own their own source records and
# versions, and acknowledge an accepted, rejected, timed-out or conflicting write.

from acme_city.adapters.sources.base import (
    SourceAcknowledgement,
    SourceAdapter,
    SourceCommand,
    adapter_for,
    available_adapters,
)

__all__ = [
    "SourceAcknowledgement",
    "SourceAdapter",
    "SourceCommand",
    "adapter_for",
    "available_adapters",
]

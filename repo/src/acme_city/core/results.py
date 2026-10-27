"""Result envelopes shared by every service boundary.

Services return either a :class:`VersionedResult` describing an accepted
write, or a :class:`ConflictResult` describing a rejected stale write.  Both
serialize to stable dictionaries for the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VersionedResult[T]:
    """An accepted mutation together with the version it produced."""

    value: T
    version: int
    audit_event_id: str

    def to_dict(self) -> dict[str, Any]:
        value = self.value
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        elif hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return {
            "value": value,
            "version": self.version,
            "audit_event_id": self.audit_event_id,
        }


@dataclass(frozen=True)
class ConflictResult:
    """A rejected write because the caller's expected version was stale."""

    code: str = "version_conflict"
    expected_version: int | None = None
    current_version: int | None = None
    differences: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "expected_version": self.expected_version,
            "current_version": self.current_version,
            "differences": [dict(difference) for difference in self.differences],
        }


__all__ = ["ConflictResult", "VersionedResult"]

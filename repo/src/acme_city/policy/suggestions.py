"""The suggested what-ifs on the scenario list.

The first one is the headline demonstration: raise the side and rear yard
fence height limit from 6 ft to 7 ft.  Every suggestion is a plain list of
supported change requests, read the same way as a change the administrator
types, so a suggestion has no special path through the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acme_city.policy.config import PolicyConfig

FENCE_KEY = "fence_height_7ft"
FENCE_TITLE = "Raise the side/rear fence height limit from 6 ft to 7 ft"


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    summary: str


SUGGESTIONS: tuple[Suggestion, ...] = (
    Suggestion(
        FENCE_KEY,
        FENCE_TITLE,
        "Changes the limit of ACME Code §14-306 (rule DF-2) and leaves the front yard limit alone.",
    ),
    Suggestion(
        "shed_condition_300",
        "Raise the shed size that carries a condition from 200 sq ft to 300 sq ft",
        "Changes the limit of ACME Code §15-106 (rule SH-2); the 600 sq ft limit is not touched.",
    ),
    Suggestion(
        "simple_targets_3_days",
        "Set a 3 day service target for the simple permit types",
        "Changes the configured service target only; no processing time is derived from it.",
    ),
)


def suggestion(key: str) -> Suggestion | None:
    for item in SUGGESTIONS:
        if item.key == key:
            return item
    return None


def suggestion_changes(key: str, baseline: PolicyConfig) -> list[dict[str, Any]]:
    """Return the change requests of one suggestion (empty for an unknown key)."""
    if key == FENCE_KEY:
        return [{"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}]
    if key == "shed_condition_300":
        return [{"kind": "rule_threshold", "rule_id": "SH-2", "limit_value": "300"}]
    if key == "simple_targets_3_days":
        return [
            {"kind": "service_target", "permit_type_key": item.key, "service_target_days": 3}
            for item in baseline.permit_types
            if item.process_category == "simple" and item.service_target_days != 3
        ]
    return []


__all__ = ["FENCE_KEY", "FENCE_TITLE", "SUGGESTIONS", "Suggestion", "suggestion", "suggestion_changes"]

"""The finding vocabulary and the pure value a finding producer returns.

A finding spec is a producer's result: the statement a person will read.  It
is not a stored row.  Production writes a spec as a finding row; the policy
simulation only compares specs.
"""
# REQUIRES: PER-04, AI-03
# Every finding names its type, its rule, the line the applicant must satisfy
# and whether it blocks the case.

from __future__ import annotations

from dataclasses import dataclass

#: The finding types an agent may record.
FINDING_TYPES: tuple[str, ...] = (
    "missing_field",
    "missing_document",
    "unreadable",
    "wrong_type",
    "duplicate",
    "conflict",
    "fee",
    "low_confidence_extraction",
    "judgment",
)

#: The severities a finding may carry.
SEVERITIES: tuple[str, ...] = ("block", "review")

#: The finding types that ask a person to judge the case rather than block
#: it.  They route the case to early resolution for verification.
HUMAN_JUDGMENT_TYPES: frozenset[str] = frozenset(
    {"duplicate", "conflict", "low_confidence_extraction", "judgment"}
)


@dataclass(frozen=True)
class FindingSpec:
    """One finding as a producer states it."""

    finding_type: str
    message: str
    rule: str | None = None
    applicant_must: str | None = None
    severity: str = "review"
    related_application_id: str | None = None
    source_node: str | None = None

    def __post_init__(self) -> None:
        if self.finding_type not in FINDING_TYPES:
            raise ValueError(f"unknown finding type: {self.finding_type!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown finding severity: {self.severity!r}")


def is_blocking(severity: str) -> bool:
    """Return whether a finding of this severity blocks the case."""
    return severity == "block"


def is_judging(severity: str, finding_type: str) -> bool:
    """Return whether a finding asks a person to judge the case."""
    return severity == "review" and finding_type in HUMAN_JUDGMENT_TYPES


__all__ = [
    "FINDING_TYPES",
    "HUMAN_JUDGMENT_TYPES",
    "SEVERITIES",
    "FindingSpec",
    "is_blocking",
    "is_judging",
]

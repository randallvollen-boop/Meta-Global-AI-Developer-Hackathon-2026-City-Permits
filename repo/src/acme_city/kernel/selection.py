"""Pure selection of the catalogue versions in force on a basis date.

The stored catalogue queries rows from the database; the choice of which row
applies is made here, so a frozen copy of the catalogue is selected exactly the
way the stored one is.  A row only needs ``status``, ``effective_from`` and
``effective_to`` (and ``definition`` for a fee schedule).
"""
# REQUIRES: REF-01, PER-06
# One published version is selected for a basis date, whether the rows come
# from the stored catalogue or from a frozen copy of it.

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, TypeVar


class _Dated(Protocol):
    status: str
    effective_from: datetime
    effective_to: datetime | None


class _Schedule(_Dated, Protocol):
    definition: Mapping[str, Any] | None


S = TypeVar("S", bound=_Schedule)


def effective_at(
    effective_from: datetime, effective_to: datetime | None, basis_at: datetime
) -> bool:
    """Return whether a version is in force at ``basis_at``."""
    if effective_from > basis_at:
        return False
    return effective_to is None or effective_to > basis_at


def published_in_force(row: _Dated, basis_at: datetime) -> bool:
    """Return whether a published version is in force at ``basis_at``."""
    return row.status == "published" and effective_at(
        row.effective_from, row.effective_to, basis_at
    )


def schedule_applies(definition: Mapping[str, Any] | None, permit_type_key: str | None) -> bool:
    """Return whether a fee schedule definition applies to a permit type."""
    declared = (definition or {}).get("permit_types")
    if not declared:
        return True
    if permit_type_key is None:
        return False
    return permit_type_key in declared


def select_schedule_for_type(
    rows: Iterable[S], basis_at: datetime, permit_type_key: str | None = None
) -> S | None:
    """Return the published schedule in force at ``basis_at`` for a type.

    When more than one would apply, the latest effective date is selected.
    """
    applicable = [
        row
        for row in sorted(rows, key=lambda item: item.effective_from)
        if published_in_force(row, basis_at)
        and schedule_applies(row.definition, permit_type_key)
    ]
    return applicable[-1] if applicable else None


def select_assessment_schedule(rows: Iterable[S], basis_at: datetime) -> S | None:
    """Return the schedule the finance assessment prices a case with.

    The finance service selects by the recorded basis date only: the latest
    published schedule in force.  It does not filter by permit type, so a
    simulation that prices a case must use this same selection.
    """
    applicable = [
        row
        for row in sorted(rows, key=lambda item: item.effective_from)
        if published_in_force(row, basis_at)
    ]
    return applicable[-1] if applicable else None


__all__ = [
    "effective_at",
    "published_in_force",
    "schedule_applies",
    "select_assessment_schedule",
    "select_schedule_for_type",
]

"""Access to the stored rule and fee catalogue.

The catalogue holds one row per rule version.  This module reads those rows,
turns them into views and reports the conditions that must hold before a
version may be published.  It performs no transition of its own.
"""
# REQUIRES: REF-01, REF-02, PER-06
# The catalogue keeps stable rule identifiers, versions, citations, parameters
# and effective dates, and it prevents overlapping published versions for the
# same applicability.

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.kernel.selection import effective_at, schedule_applies, select_schedule_for_type
from acme_city.persistence.models import finance, permit
from acme_city.rules.schemas import FeeScheduleView, RuleVersionView

#: The stored identifier of a seeded rule version ends with its business
#: version, for example ``rulever_CT-2_v2``.  A version created through the
#: service records the same number in its source mapping.
_BUSINESS_VERSION_SUFFIX = re.compile(r"_v(?P<version>\d+)$")

#: The condition key that carries a numeric threshold instead of a category.
CONDITION_THRESHOLD_KEY = "field_above"


def business_version(row: finance.RuleVersion) -> int:
    """Return the business version number of a stored rule version."""
    mapping = row.source_mapping or {}
    recorded = mapping.get("business_version")
    if recorded is not None:
        try:
            return int(recorded)
        except (TypeError, ValueError):
            pass
    match = _BUSINESS_VERSION_SUFFIX.search(row.id or "")
    if match is not None:
        return int(match.group("version"))
    return 1


def version_label(row: finance.RuleVersion) -> str:
    """Return the stable label of a rule version, for example ``CT-2@2``."""
    return f"{row.rule_id}@{business_version(row)}"


def rule_view(row: finance.RuleVersion, permit_type_key: str | None = None) -> RuleVersionView:
    """Return the view of one stored rule version."""
    mapping = dict(row.source_mapping or {})
    return RuleVersionView(
        rule_id=row.rule_id,
        version_label=version_label(row),
        row_id=row.id,
        version=row.version,
        permit_type_key=permit_type_key,
        kind=row.kind,
        title=row.title,
        citation=row.citation,
        field_path=row.field_path,
        operator=row.operator,
        limit_value=row.limit_value,
        on_violate=row.on_violate,
        condition=dict(row.condition) if row.condition else None,
        message=row.message,
        condition_note=row.condition_note,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        status=row.status,
        author_actor_id=row.author_actor_id,
        approver_actor_id=row.approver_actor_id,
        source_mapping=mapping or None,
        precedence=mapping.get("precedence"),
        unit=mapping.get("unit"),
    )


def fee_schedule_view(row: finance.FeeScheduleVersion) -> FeeScheduleView:
    """Return the view of one stored fee schedule version."""
    return FeeScheduleView(
        row_id=row.id,
        fee_schedule_id=row.fee_schedule_id,
        version_label=row.version_label,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        currency=row.currency,
        definition=dict(row.definition) if row.definition else None,
        status=row.status,
        author_actor_id=row.author_actor_id,
        approver_actor_id=row.approver_actor_id,
    )


def permit_type_key(session: Session, permit_type_id: str | None) -> str | None:
    """Return the catalogue key of a stored permit type."""
    if not permit_type_id:
        return None
    row = session.execute(
        select(permit.PermitType).where(permit.PermitType.id == permit_type_id)
    ).scalar_one_or_none()
    return None if row is None else row.key


def permit_type_id_for_key(session: Session, key: str) -> str | None:
    """Return the stored identifier of a permit type key."""
    row = session.execute(
        select(permit.PermitType).where(permit.PermitType.key == key)
    ).scalar_one_or_none()
    return None if row is None else row.id


def select_rule_versions(
    session: Session, permit_type_id: str | None, basis_at: datetime
) -> list[finance.RuleVersion]:
    """Return the published rule versions in force at ``basis_at``."""
    rows = session.execute(
        select(finance.RuleVersion)
        .where(
            finance.RuleVersion.status == "published",
            finance.RuleVersion.effective_from <= basis_at,
        )
        .order_by(finance.RuleVersion.permit_type_id, finance.RuleVersion.rule_id)
    ).scalars().all()
    selected = [
        row
        for row in rows
        if (row.permit_type_id or None) == (permit_type_id or None)
        and effective_at(row.effective_from, row.effective_to, basis_at)
    ]
    return selected


def select_fee_schedule(
    session: Session, basis_at: datetime, permit_type_key: str | None = None
) -> finance.FeeScheduleVersion | None:
    """Return the published fee schedule in force at ``basis_at``.

    When more than one published schedule would apply, the one with the
    latest effective date is selected; the caller records which one it used.
    """
    rows = session.execute(
        select(finance.FeeScheduleVersion)
        .where(
            finance.FeeScheduleVersion.status == "published",
            finance.FeeScheduleVersion.effective_from <= basis_at,
        )
        .order_by(finance.FeeScheduleVersion.effective_from)
    ).scalars().all()
    return select_schedule_for_type(rows, basis_at, permit_type_key)


def _schedule_applies(row: finance.FeeScheduleVersion, permit_type_key: str | None) -> bool:
    """Return whether a fee schedule applies to a permit type."""
    return schedule_applies(row.definition, permit_type_key)


def windows_overlap(
    first_from: datetime,
    first_to: datetime | None,
    second_from: datetime,
    second_to: datetime | None,
) -> bool:
    """Return whether two effective windows overlap."""
    first_end = first_to
    second_end = second_to
    if first_end is None or second_end is None:
        return True
    return first_from < second_end and second_from < first_end


def conflicting_published_version(
    session: Session, candidate: finance.RuleVersion
) -> finance.RuleVersion | None:
    """Return a published version of the same rule whose window overlaps.

    Two published versions of one rule may not be in force at the same time
    unless an explicit precedence policy says which one wins.
    """
    rows = session.execute(
        select(finance.RuleVersion).where(
            finance.RuleVersion.rule_id == candidate.rule_id,
            finance.RuleVersion.status == "published",
            finance.RuleVersion.id != candidate.id,
        )
    ).scalars().all()
    for row in rows:
        if windows_overlap(
            candidate.effective_from,
            candidate.effective_to,
            row.effective_from,
            row.effective_to,
        ):
            return row
    return None


def conflicting_citation(
    session: Session, candidate: finance.RuleVersion
) -> finance.RuleVersion | None:
    """Return a published rule that already carries the same citation.

    One executable rule carries one citation, so a second rule may not
    publish a citation that is already in force.
    """
    rows = session.execute(
        select(finance.RuleVersion).where(
            finance.RuleVersion.status == "published",
            finance.RuleVersion.citation == candidate.citation,
            finance.RuleVersion.rule_id != candidate.rule_id,
            finance.RuleVersion.id != candidate.id,
        )
    ).scalars().all()
    return rows[0] if rows else None


def conflicting_operator(
    session: Session, candidate: finance.RuleVersion
) -> finance.RuleVersion | None:
    """Return a published rule that checks the same field the other way round.

    A minimum and a maximum on the same field of the same permit type
    contradict each other unless one of them declares a precedence.
    """
    if not candidate.field_path or not candidate.operator:
        return None
    rows = session.execute(
        select(finance.RuleVersion).where(
            finance.RuleVersion.status == "published",
            finance.RuleVersion.permit_type_id == candidate.permit_type_id,
            finance.RuleVersion.field_path == candidate.field_path,
            finance.RuleVersion.id != candidate.id,
        )
    ).scalars().all()
    for row in rows:
        if (row.operator or "").lower() == (candidate.operator or "").lower():
            continue
        if not row.field_path or not row.operator:
            continue
        if _conditions_disjoint(row.condition, candidate.condition):
            continue
        return row
    return None


def _conditions_disjoint(
    first: Mapping[str, Any] | None, second: Mapping[str, Any] | None
) -> bool:
    """Return whether two applicability conditions cannot both hold."""
    first = first or {}
    second = second or {}
    for field in set(first) | set(second):
        if field == CONDITION_THRESHOLD_KEY:
            continue
        if field not in first or field not in second:
            continue
        if str(first[field]).strip().lower() != str(second[field]).strip().lower():
            return True
    return False


def citations_of(rules: Iterable[RuleVersionView]) -> list[str]:
    """Return the distinct citations of a rule set, in catalogue order."""
    seen: list[str] = []
    for rule in rules:
        if rule.citation not in seen:
            seen.append(rule.citation)
    return seen


__all__ = [
    "business_version",
    "citations_of",
    "conflicting_citation",
    "conflicting_operator",
    "conflicting_published_version",
    "effective_at",
    "fee_schedule_view",
    "permit_type_id_for_key",
    "permit_type_key",
    "rule_view",
    "select_fee_schedule",
    "select_rule_versions",
    "version_label",
    "windows_overlap",
]

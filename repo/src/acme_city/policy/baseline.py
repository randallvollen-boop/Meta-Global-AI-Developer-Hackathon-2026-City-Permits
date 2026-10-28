"""Read-only freezing of the stored catalogue into a :class:`PolicyConfig`.

This is one of two modules in the package that touch a session, and it only
reads.  It selects nothing by case: it copies the permit types, every
published rule version and every published fee schedule version, so the
frozen configuration can be selected and hashed without the database.
"""
# REQUIRES: REF-01, PER-06
# The baseline is a copy of the published catalogue at a recorded moment.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import finance, permit
from acme_city.policy.config import (
    FeeScheduleConfig,
    PolicyConfig,
    RuleConfig,
    TypeConfig,
)
from acme_city.rules import catalog


def freeze_baseline(session: Session, analysis_at: datetime) -> PolicyConfig:
    """Return the published configuration, frozen at ``analysis_at``.

    The read never writes: no row is added, flushed or changed.
    """
    with session.no_autoflush:
        types = session.execute(
            select(permit.PermitType).order_by(permit.PermitType.key)
        ).scalars().all()
        key_by_id = {row.id: row.key for row in types}
        rules = session.execute(
            select(finance.RuleVersion)
            .where(finance.RuleVersion.status == "published")
            .order_by(finance.RuleVersion.rule_id, finance.RuleVersion.effective_from)
        ).scalars().all()
        schedules = session.execute(
            select(finance.FeeScheduleVersion)
            .where(finance.FeeScheduleVersion.status == "published")
            .order_by(
                finance.FeeScheduleVersion.fee_schedule_id,
                finance.FeeScheduleVersion.effective_from,
            )
        ).scalars().all()
        type_configs = tuple(
            TypeConfig(
                key=row.key,
                label=row.label,
                active=bool(row.active),
                review_area=row.review_area,
                review_route=row.review_route,
                process_category=row.process_category,
                discretionary=bool(row.discretionary),
                required_fields=tuple(row.required_fields or ()),
                required_documents=tuple(row.required_documents or ()),
                fee_schedule_key=row.fee_schedule_key,
                service_target_days=int(row.service_target_days or 0),
            )
            for row in types
        )
        rule_configs = tuple(
            RuleConfig.from_view(catalog.rule_view(row, key_by_id.get(row.permit_type_id or "")))
            for row in rules
        )
        fee_configs = tuple(
            FeeScheduleConfig(
                fee_schedule_id=row.fee_schedule_id,
                version_label=row.version_label,
                row_id=row.id,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                currency=row.currency,
                definition=dict(row.definition or {}),
            )
            for row in schedules
        )
    return PolicyConfig(
        analysis_at=analysis_at,
        permit_types=type_configs,
        rules=rule_configs,
        fee_schedules=fee_configs,
    )


__all__ = ["freeze_baseline"]

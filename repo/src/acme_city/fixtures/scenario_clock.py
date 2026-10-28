"""The demo scenario clock.

In the fictional demo, ages, service targets, overdue flags and dashboards are
read against one fixed demo date instead of the real clock.  Stored data never
changes: this module only chooses the date.  The date is chosen once, when the
application starts, from the ``ACME_SCENARIO_CLOCK`` setting:

* empty (the default): the real clock.  Production, tests and acceptance runs
  use this.
* an ISO date such as ``2026-10-14``: that day, at 17:00 UTC.
* ``auto``: the latest submission among the seeded scenario cases (the
  fixture cases the queues show, not the synthetic year) plus
  ``AUTO_LEAD_DAYS`` days, but never later than the real clock, so the demo
  date is never in the future.  Cases created live in the demo carry no
  scenario id and do not move the date.

A database that is not marked as the fictional demo ignores the setting.
The rule and fee version of a case is chosen from its stored submission time
and the stored effective dates; the scenario clock is not an input to it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.core.clock import set_scenario_clock, utc_now
from acme_city.fixtures.reset import ENVIRONMENT_ID
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment

#: Days after the latest seeded submission that ``auto`` places the demo date.
AUTO_LEAD_DAYS = 3

#: The hour (UTC) of an explicit demo date.
EXPLICIT_HOUR = 17

LABEL_HELP = "Ages and due dates are calculated against the demo date, not against today."


def resolve_scenario_moment(session: Session, setting: str, *, real_now: datetime | None = None) -> datetime | None:
    """Return the demo moment the setting asks for, or ``None`` for the real clock."""
    value = (setting or "").strip().lower()
    if not value or value in {"off", "real", "none"}:
        return None
    marker = session.execute(
        select(DemoEnvironment).where(DemoEnvironment.environment_id == ENVIRONMENT_ID)
    ).scalar_one_or_none()
    if marker is None or not marker.fictional_demo:
        return None
    now = real_now or utc_now()
    if value == "auto":
        latest = session.execute(
            select(func.max(permit.Application.initial_submitted_at)).where(
                permit.Application.scenario_id.is_not(None),
                permit.Application.synthetic.is_(False),
            )
        ).scalar_one()
        if latest is None:
            return None
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)
        return min(latest + timedelta(days=AUTO_LEAD_DAYS), now)
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"ACME_SCENARIO_CLOCK must be empty, 'auto' or an ISO date, not {setting!r}") from error
    return datetime.combine(day, time(EXPLICIT_HOUR), tzinfo=UTC)


def install_scenario_clock(session: Session, setting: str) -> datetime | None:
    """Resolve the setting and make it the process scenario clock (or clear it)."""
    moment = resolve_scenario_moment(session, setting)
    set_scenario_clock(moment)
    return moment


def demo_date_label(moment: datetime | None) -> str:
    """Return the top bar label, for example ``Demo date: 14 Oct 2026``; blank on the real clock."""
    if moment is None:
        return ""
    return f"Demo date: {moment.day} {moment.strftime('%b %Y')}"


__all__ = [
    "AUTO_LEAD_DAYS",
    "LABEL_HELP",
    "demo_date_label",
    "install_scenario_clock",
    "resolve_scenario_moment",
]

"""Time primitives.

Every timestamp stored by the application is timezone-aware UTC.  Unknown
source, effective or receipt times remain ``None``; the arrival time is never
substituted for a business time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UTC = UTC


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(_UTC)


#: The demo scenario moment, or ``None`` for the real clock.  Set once per
#: application instance by :func:`set_scenario_clock`; nothing else writes it.
_scenario_moment: datetime | None = None


def set_scenario_clock(moment: datetime | None) -> None:
    """Set (or clear, with ``None``) the demo scenario moment."""
    global _scenario_moment
    _scenario_moment = None if moment is None else moment.astimezone(_UTC)


def scenario_moment() -> datetime | None:
    """Return the active demo scenario moment, or ``None`` on the real clock."""
    return _scenario_moment


def app_now() -> datetime:
    """Return "today" for ages, service targets, overdue flags and dashboards.

    This is the scenario moment in the demo when one is active, otherwise the
    real clock.  It never stamps a stored row: audit, creation and decision
    times keep using :func:`utc_now`, so stored data is the same either way.
    """
    return _scenario_moment if _scenario_moment is not None else utc_now()


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC.

    Naive datetimes are rejected: the application never persists a timestamp
    without a timezone.
    """
    if value.tzinfo is None:
        raise ValueError("naive datetimes are not accepted; supply a timezone-aware value")
    return value.astimezone(_UTC)


def isoformat(value: datetime | None) -> str | None:
    """Return an ISO-8601 UTC representation, or ``None`` for an unknown time."""
    if value is None:
        return None
    return ensure_utc(value).isoformat()


def demo_timezone(name: str) -> ZoneInfo:
    """Return the configured display timezone."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - configuration error
        raise ValueError(f"unknown demo timezone: {name!r}") from exc


def to_demo_time(value: datetime | None, timezone_name: str) -> datetime | None:
    """Return ``value`` expressed in the configured display timezone."""
    if value is None:
        return None
    return ensure_utc(value).astimezone(demo_timezone(timezone_name))


__all__ = [
    "app_now",
    "demo_timezone",
    "ensure_utc",
    "isoformat",
    "scenario_moment",
    "set_scenario_clock",
    "to_demo_time",
    "utc_now",
]

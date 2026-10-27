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


__all__ = ["demo_timezone", "ensure_utc", "isoformat", "to_demo_time", "utc_now"]

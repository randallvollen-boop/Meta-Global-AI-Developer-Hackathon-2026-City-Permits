"""Column types used across the schema.

The application stores timezone-aware UTC timestamps, canonical JSON documents
and money as integer minor units (cents).  Unknown source, effective or
receipt times stay ``NULL``; arrival time is never substituted for them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

#: Canonical JSON serialization used for every JSON column, so that two runs
#: with the same logical content produce the same stored bytes.
def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC timestamp.

    SQLite has no native timestamp type; values are stored as text and always
    read back as timezone-aware UTC.  Naive datetimes are rejected on write.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; store timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = ["UTCDateTime", "canonical_json"]

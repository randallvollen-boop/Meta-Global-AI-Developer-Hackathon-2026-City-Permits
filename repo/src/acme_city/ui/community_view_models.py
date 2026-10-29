"""The presentation helpers of the two public community pages.

The helpers are pure.  Each one turns one public value into the words a
resident reads or into a local link.  There is no database access, no write,
no model call and no widening of the public record: a helper never sees
anything but the fields the public read model already allows.

No helper accepts a destination from the caller.  The return links are
rebuilt from the bounded search text and the permit type the catalog holds,
so a link can only ever point at this site's own community pages.
"""
# REQUIRES: UX-01

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

from acme_city.fixtures.loader import REPO_ROOT

#: The longest search the page accepts, in characters.
MAX_QUERY_LENGTH = 80

#: The words a date the record does not carry are shown with.
NOT_RECORDED = "Not recorded"

#: The words a public status without an explanation is shown with.
UNKNOWN_STATUS = "The status of this application is not recorded here."

#: The fixed explanation of each public status.  These are plain sentences
#: written for a resident.  They are not model output and not a replay.
STATUS_EXPLANATIONS: dict[str, str] = {
    "Received": "The application has been received.",
    "In review": "The application is in review.",
    "Approved": "The application is approved. A permit has not necessarily been issued.",
    "Denied": "The application was denied.",
    "Permit issued": "A permit has been issued.",
}

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

_RULES_PATH = REPO_ROOT / "config" / "rules_and_fees.json"


@lru_cache(maxsize=1)
def _type_keys() -> frozenset[str]:
    """Return the permit type keys the fictional catalog holds."""
    payload = json.loads(Path(_RULES_PATH).read_text(encoding="utf-8"))
    return frozenset(str(item["key"]) for item in payload.get("permit_types", []))


def permit_type_keys() -> frozenset[str]:
    """Return the permit type keys the overview filter accepts."""
    return _type_keys()


def display_date(value: str) -> str:
    """Return the date as a resident reads it, or "Not recorded"."""
    text = (value or "").strip()
    if not text:
        return NOT_RECORDED
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return NOT_RECORDED
    return f"{_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"


def status_explanation(status: str) -> str:
    """Return the fixed explanation of a public status."""
    return STATUS_EXPLANATIONS.get((status or "").strip(), UNKNOWN_STATUS)


def normalize_query(query: str) -> str:
    """Return the search text the page accepts: collapsed and clipped."""
    return " ".join((query or "").split())[:MAX_QUERY_LENGTH]


def normalize_type(value: str) -> str:
    """Return the permit type key when the catalog holds it, else an empty string."""
    text = (value or "").strip()
    return text if text in _type_keys() else ""


def _query_string(q: str, type: str) -> str:
    """Return the encoded query string of a search and an overview type."""
    parts: list[tuple[str, str]] = []
    query = normalize_query(q)
    key = normalize_type(type)
    if query:
        parts.append(("q", query))
    if key:
        parts.append(("type", key))
    return urlencode(parts)


def community_url(q: str = "", type: str = "") -> str:
    """Return the local community page URL for a search and an overview type."""
    query_string = _query_string(q, type)
    return f"/city/community?{query_string}" if query_string else "/city/community"


def public_record_url(reference: str, q: str = "", type: str = "") -> str:
    """Return the local URL of one public permit record."""
    path = quote((reference or "").strip(), safe="")
    query_string = _query_string(q, type)
    url = f"/city/community/permit/{path}"
    return f"{url}?{query_string}" if query_string else url


__all__ = [
    "MAX_QUERY_LENGTH",
    "NOT_RECORDED",
    "STATUS_EXPLANATIONS",
    "UNKNOWN_STATUS",
    "community_url",
    "display_date",
    "normalize_query",
    "normalize_type",
    "permit_type_keys",
    "public_record_url",
    "status_explanation",
]

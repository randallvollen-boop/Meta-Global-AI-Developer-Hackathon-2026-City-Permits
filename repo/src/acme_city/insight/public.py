"""The public read model of "Permits in my community".

This is a dedicated, read-only model with an **allowlist** of fields.  It is
not a filtered copy of any staff view: a public record is built field by field
from :class:`PublicPermit`, and nothing else leaves this module.

Never in the public model: any homeowner or applicant name, any document,
note or comment, any contact detail, any fee, finding or draft, any archived,
withdrawn or returned case, anything before submission, and any internal
identifier.  A total under three is suppressed.  A case that is not public
gets the same answer as a case that does not exist.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from acme_city.gis import svg
from acme_city.gis.catalog import PropertyCatalog
from acme_city.insight.city_view import _shade_levels
from acme_city.insight.queries import PermitRow, load_rows

#: A total below this shows as "fewer than 3".
SUPPRESSION_THRESHOLD = 3
SUPPRESSED_TEXT = "fewer than 3"

#: The public statuses of an application.  A status that is missing here
#: (draft, withdrawn, returned, archived) makes the case non-public.
PUBLIC_STATUS: dict[str, str] = {
    "submitted": "Received",
    "needs_information": "Received",
    "revisions_requested": "Received",
    "ready_for_review": "In review",
    "under_review": "In review",
    "approved": "Approved",
    "denied": "Denied",
    "issued": "Permit issued",
}
DECIDED_STATUSES = frozenset({"approved", "denied", "issued"})
PUBLIC_EXCEPTIONS: dict[str, str] = {
    "variance": "Variance",
    "waiver": "Waiver",
    "conditions": "Approved with conditions",
}

#: The public record, field by field.  A test pins this tuple.
PUBLIC_FIELDS: tuple[str, ...] = (
    "reference",
    "permit_number",
    "permit_type",
    "parcel",
    "address",
    "district",
    "work_description",
    "status",
    "submitted_on",
    "decided_on",
    "issued_on",
    "outcome",
    "conditions",
    "exception",
    "exception_kinds",
    "contractor_business",
    "synthetic",
)


@dataclass(frozen=True)
class PublicPermit:
    """One public permit record: the allowlist, and nothing else."""

    reference: str
    permit_number: str
    permit_type: str
    parcel: str
    address: str
    district: str
    work_description: str
    status: str
    submitted_on: str
    decided_on: str
    issued_on: str
    outcome: str
    conditions: tuple[str, ...]
    exception: bool
    exception_kinds: tuple[str, ...]
    contractor_business: str
    synthetic: bool = field(default=False)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["conditions"] = list(self.conditions)
        data["exception_kinds"] = list(self.exception_kinds)
        return data


def is_public(row: PermitRow) -> bool:
    """Return whether a case may appear in the community view at all."""
    return (
        row.status in PUBLIC_STATUS
        and not row.archived
        and row.submitted_at is not None
    )


def _date(value: datetime | None) -> str:
    return value.date().isoformat() if value is not None else ""


def to_public(row: PermitRow) -> PublicPermit:
    """Build the public record of one case from the allowlist."""
    decided = row.status in DECIDED_STATUSES
    outcome = ""
    if decided:
        outcome = {"approved": "Approved", "conditions": "Approved with conditions", "denied": "Denied"}.get(
            row.outcome_key, ""
        )
    kinds = tuple(PUBLIC_EXCEPTIONS[k] for k in row.exception_kinds if k in PUBLIC_EXCEPTIONS)
    return PublicPermit(
        reference=row.permit_number or row.number,
        permit_number=row.permit_number or "",
        permit_type=row.type_label,
        parcel=row.parcel_number,
        address=row.address,
        district=row.district,
        work_description=row.description,
        status=PUBLIC_STATUS[row.status],
        submitted_on=_date(row.submitted_at),
        decided_on=_date(row.decided_at) if decided else "",
        issued_on=_date(row.issued_at) if row.status == "issued" else "",
        outcome=outcome,
        conditions=tuple(row.conditions) if decided and row.outcome_key == "conditions" else (),
        exception=bool(kinds),
        exception_kinds=kinds,
        contractor_business=row.contractor,
        synthetic=row.synthetic,
    )


def public_permits(session: Session) -> list[PublicPermit]:
    """Return every public permit record, newest first."""
    rows = [row for row in load_rows(session) if is_public(row)]
    rows.sort(key=lambda r: (r.submitted_at, r.number), reverse=True)
    return [to_public(row) for row in rows]


def public_record(session: Session, reference: str) -> PublicPermit | None:
    """Return one public record, or ``None``.

    ``None`` is the answer for a reference that does not exist and for one
    that exists but is not public: the two are indistinguishable.
    """
    wanted = reference.strip().lower()
    if not wanted or len(wanted) > 96:
        return None
    for record in public_permits(session):
        if record.reference.lower() == wanted:
            return record
    return None


def suppress(total: int) -> dict[str, Any]:
    """Return a total as the public screen shows it."""
    if total < SUPPRESSION_THRESHOLD:
        return {"value": None, "display": SUPPRESSED_TEXT, "suppressed": True}
    return {"value": total, "display": str(total), "suppressed": False}


def _normal(text: str) -> str:
    return " ".join(text.lower().replace(",", " ").split())


def lookup(session: Session, query: str, *, limit: int = 40) -> dict[str, Any]:
    """Look public permits up by address, street or permit number."""
    text = " ".join(query.split())[:80]
    result: dict[str, Any] = {"query": text, "records": [], "total": suppress(0), "too_short": False}
    if not text:
        return result
    if len(text) < 3:
        result["too_short"] = True
        return result
    wanted = _normal(text)
    matches = [
        record
        for record in public_permits(session)
        if wanted in _normal(record.reference)
        or wanted in _normal(record.address)
        or wanted in _normal(record.parcel)
    ]
    result["total"] = suppress(len(matches))
    result["records"] = matches[:limit]
    result["truncated"] = len(matches) > limit
    return result


def community_summary(session: Session, *, type: str = "") -> dict[str, Any]:
    """Return the public map and district totals (public figures only)."""
    records = [row for row in load_rows(session) if is_public(row)]
    types = {row.type_key: row.type_label for row in records}
    chosen = type if type in types else ""
    if chosen:
        records = [row for row in records if row.type_key == chosen]
    catalog = PropertyCatalog(session)
    districts = sorted({p.zoning_code or "" for p in catalog.parcels() if p.zoning_code})
    counts = Counter(row.district for row in records)
    shown = {code: suppress(counts.get(code, 0)) for code in districts}
    levels = _shade_levels({code: counts.get(code, 0) for code in districts})
    shade: dict[str, int | None] = {
        code: (None if shown[code]["suppressed"] else levels[code]) for code in districts
    }
    parcels = [
        svg.MapParcel(
            number=p.source_parcel_number,
            site_address=catalog.site_address(p),
            zoning=p.zoning_code or "",
            rings=p.geometry,
        )
        for p in catalog.parcels()
    ]
    streets = [
        {"street_key": s.street_key, "name": s.name, "path": s.path} for s in catalog.streets()
    ]
    drawing = svg.district_map_svg(
        parcels,
        streets,
        shade,
        {code: shown[code]["display"] for code in districts},
        [],
        caption=(
            "Map of ACME City shaded by zoning district: the darker the district, the more "
            "public permits. A hatched district has fewer than 3."
        ),
    )
    total = suppress(len(records))
    return {
        "type": chosen,
        "type_options": [{"key": k, "label": types[k]} for k in sorted(types)],
        "map_svg": drawing,
        "districts": [
            {"code": code, "total": shown[code]} for code in districts
        ],
        "total": total,
        "synthetic_present": any(row.synthetic for row in records),
        "legend": ["fewer than 3 (hatched)", "fewest", "fewer", "more", "most"],
        "recent": [to_public(row) for row in sorted(
            records, key=lambda r: (r.submitted_at, r.number), reverse=True
        )[:8]],
    }


class RateLimiter:
    """A small in-process sliding-window limiter, keyed by client address."""

    def __init__(
        self, limit: int = 60, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 5000:
            for stale in [k for k, v in self._hits.items() if not v]:
                self._hits.pop(stale, None)
        return True


#: The limiter every public community route shares.
COMMUNITY_LIMITER = RateLimiter()


__all__ = [
    "COMMUNITY_LIMITER",
    "PUBLIC_FIELDS",
    "PUBLIC_STATUS",
    "PublicPermit",
    "RateLimiter",
    "SUPPRESSED_TEXT",
    "SUPPRESSION_THRESHOLD",
    "community_summary",
    "is_public",
    "lookup",
    "public_permits",
    "public_record",
    "suppress",
    "to_public",
]

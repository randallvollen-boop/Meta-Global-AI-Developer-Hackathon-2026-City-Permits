"""The City view: permit activity across the city, for the City Administrator.

Every figure is a server count over the stored applications, and the screen
prints the definition next to it.  Synthetic rows are labelled and can be
included or excluded.  Nothing here changes a record.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.gis import svg
from acme_city.gis.catalog import PropertyCatalog
from acme_city.insight.queries import ACTIVITY_EXCLUDED_STATUSES, PermitRow, load_rows

CATEGORY_LABELS: dict[str, str] = {
    "restaurant": "Restaurant",
    "bar": "Bar",
    "retail": "Retail",
    "office": "Office",
    "other": "Other",
}
OUTCOME_LABELS: dict[str, str] = {
    "approved": "Approved",
    "conditions": "Approved with conditions",
    "denied": "Denied",
    "undecided": "Not decided",
}
PERIODS: dict[str, tuple[str, int | None]] = {
    "all": ("The whole year", None),
    "30d": ("Last 30 days", 30),
    "90d": ("Last 90 days", 90),
    "6m": ("Last 6 months", 182),
    "12m": ("Last 12 months", 365),
}
EXCEPTION_LABELS: dict[str, str] = {
    "variance": "Variance",
    "waiver": "Waiver",
    "denial": "Denial",
    "conditions": "Approved with conditions",
}
RESTAURANTS_AND_BARS = "restaurant,bar"

DEFINITIONS: dict[str, str] = {
    "permits": (
        "Permits: applications that have been submitted and are not drafts or archived, "
        "counted once each, by the month they were submitted."
    ),
    "district": "District: the zoning district of the parcel the permit is sited on.",
    "outcome": (
        "Outcome: the current recorded decision. Approved with conditions is an approval "
        "that has at least one condition. Not decided means no decision is recorded yet "
        "(or the case was withdrawn or returned)."
    ),
    "exceptions": (
        "Exceptions: a variance request, a decision with a waiver, a denial, or an approval "
        "with conditions. One permit can have more than one."
    ),
    "category": (
        "Business category: the category on the business license of the business the permit "
        "is linked to. Only permits linked to a business have one."
    ),
    "trend": "Monthly trend: permits by the calendar month of submission.",
}


def parse_filters(
    *,
    type: str = "",
    outcome: str = "",
    period: str = "",
    category: str = "",
    exceptions: str = "",
    synthetic: str = "",
) -> dict[str, Any]:
    """Return the cleaned query-string filters; an unknown value is ignored."""
    categories = [
        item for item in (part.strip() for part in category.split(",")) if item in CATEGORY_LABELS
    ]
    return {
        "type": type.strip(),
        "outcome": outcome if outcome in OUTCOME_LABELS else "",
        "period": period if period in PERIODS else "all",
        "category": categories,
        "exceptions": exceptions in {"1", "true", "on", "yes"},
        "synthetic": "exclude" if synthetic == "exclude" else "include",
    }


def _month_key(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _shade_levels(counts: dict[str, int]) -> dict[str, int]:
    top = max(counts.values(), default=0)
    if top <= 0:
        return {key: 0 for key in counts}
    return {key: (0 if value == 0 else max(1, -(-value * 4 // top))) for key, value in counts.items()}


def _query(filters: dict[str, Any]) -> str:
    parts = []
    if filters["type"]:
        parts.append(f"type={filters['type']}")
    if filters["outcome"]:
        parts.append(f"outcome={filters['outcome']}")
    if filters["period"] != "all":
        parts.append(f"period={filters['period']}")
    if filters["category"]:
        parts.append("category=" + ",".join(filters["category"]))
    if filters["exceptions"]:
        parts.append("exceptions=1")
    if filters["synthetic"] == "exclude":
        parts.append("synthetic=exclude")
    return "&".join(parts)


def city_view(
    session: Session,
    *,
    type: str = "",
    outcome: str = "",
    period: str = "",
    category: str = "",
    exceptions: str = "",
    synthetic: str = "",
    now: datetime | None = None,
    row_limit: int = 60,
) -> dict[str, Any]:
    """Return the view model of ``/insight/city``."""
    filters = parse_filters(
        type=type, outcome=outcome, period=period, category=category,
        exceptions=exceptions, synthetic=synthetic,
    )
    moment = now or utc_now()
    all_rows = [
        row for row in load_rows(session)
        if row.status not in ACTIVITY_EXCLUDED_STATUSES and row.submitted_at is not None
    ]
    synthetic_total = sum(1 for row in all_rows if row.synthetic)
    pool = [row for row in all_rows if not (filters["synthetic"] == "exclude" and row.synthetic)]
    days = PERIODS[filters["period"]][1]
    cutoff = moment - timedelta(days=days) if days else None

    def keep(row: PermitRow) -> bool:
        if filters["type"] and row.type_key != filters["type"]:
            return False
        if filters["outcome"] and row.outcome_key != filters["outcome"]:
            return False
        if filters["category"] and row.category not in filters["category"]:
            return False
        if filters["exceptions"] and not row.exception_kinds:
            return False
        return not (cutoff is not None and row.submitted_at < cutoff)

    rows = [row for row in pool if keep(row)]
    included_synthetic = sum(1 for row in rows if row.synthetic)

    catalog = PropertyCatalog(session)
    districts = sorted({p.zoning_code or "" for p in catalog.parcels() if p.zoning_code})
    by_district = Counter(row.district for row in rows)
    exceptions_by_district = Counter(row.district for row in rows if row.exception_kinds)
    district_counts = {code: by_district.get(code, 0) for code in districts}
    levels = _shade_levels(district_counts)

    parcel_exceptions: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.exception_kinds and row.parcel_number:
            for kind in row.exception_kinds:
                parcel_exceptions[row.parcel_number][kind] += 1
    dots = []
    for number, kinds in sorted(parcel_exceptions.items()):
        total = sum(1 for row in rows if row.parcel_number == number and row.exception_kinds)
        dots.append(
            {
                "parcel": number,
                "count": total,
                "title": f"Parcel {number}: {total} permit(s) with exceptions ("
                + ", ".join(f"{EXCEPTION_LABELS[k]} {v}" for k, v in sorted(kinds.items()))
                + ")",
            }
        )
    map_parcels = [
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
        map_parcels,
        streets,
        {code: levels[code] for code in districts},
        {code: f"{district_counts[code]} permits" for code in districts},
        dots,
        caption=(
            "Map of ACME City shaded by zoning district: the darker the district, the more "
            "permits match the filters. Orange dots mark parcels with exceptions; a larger "
            "dot is more exceptions."
        ),
    )

    district_table = [
        {
            "code": code,
            "permits": district_counts[code],
            "exceptions": exceptions_by_district.get(code, 0),
            "variances": sum(1 for r in rows if r.district == code and "variance" in r.exception_kinds),
            "shade": levels[code],
        }
        for code in districts
    ]
    top_exception_parcels = sorted(
        (
            {
                "parcel": d["parcel"],
                "count": d["count"],
                "district": next((r.district for r in rows if r.parcel_number == d["parcel"]), ""),
                "address": next((r.address for r in rows if r.parcel_number == d["parcel"]), ""),
            }
            for d in dots
        ),
        key=lambda item: (-item["count"], item["parcel"]),
    )[:8]

    by_month = Counter(_month_key(row.submitted_at) for row in rows if row.submitted_at)
    keys: list[str] = []
    if by_month:
        year, month = (int(part) for part in min(by_month).split("-"))
        last_year, last_month = (int(part) for part in max(by_month).split("-"))
        while (year, month) <= (last_year, last_month):
            keys.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    trend = [{"month": key, "permits": by_month.get(key, 0)} for key in keys]
    peak = max((item["permits"] for item in trend), default=0)
    bar_width = 34
    bars = []
    for position, item in enumerate(trend):
        height = 0 if not peak else round(110 * item["permits"] / peak)
        x = 10 + position * (bar_width + 6)
        bars.append(
            f'<g><title>{item["month"]}: {item["permits"]} permits</title>'
            f'<rect x="{x}" y="{130 - height}" width="{bar_width}" height="{height}"/>'
            f'<text x="{x + bar_width / 2}" y="{125 - height}" text-anchor="middle">{item["permits"]}</text>'
            f'<text x="{x + bar_width / 2}" y="148" text-anchor="middle">{item["month"][2:]}</text></g>'
        )
    trend_svg = (
        f'<svg class="insight-bars" role="img" viewBox="0 0 {max(len(trend), 1) * (bar_width + 6) + 20} 156" '
        'aria-label="Permits submitted per month" data-testid="insight-trend-chart">'
        f"<title>Permits submitted per month</title>{''.join(bars)}</svg>"
    )

    category_rows = []
    for key in CATEGORY_LABELS:
        members = [row for row in rows if row.category == key]
        category_rows.append(
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "permits": len(members),
                "approved_or_issued": sum(1 for r in members if r.outcome_key in {"approved", "conditions"}),
                "by_district": dict(sorted(Counter(r.district for r in members).items())),
            }
        )
    linked_to_business = sum(1 for row in rows if row.category)
    dining = [row for row in rows if row.category in {"restaurant", "bar"}]
    dining_sites = Counter((r.address, r.district) for r in dining)
    where_opening = [
        {"address": address, "district": district, "permits": count}
        for (address, district), count in sorted(dining_sites.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    ]

    type_labels = {row.type_key: row.type_label for row in all_rows}
    type_counts = Counter(row.type_key for row in rows)
    outcome_counts = Counter(row.outcome_key for row in rows)
    exception_counts = Counter(kind for row in rows for kind in row.exception_kinds)

    table_rows = sorted(rows, key=lambda r: (r.submitted_at, r.number), reverse=True)[:row_limit]
    active_filters = []
    if filters["type"]:
        active_filters.append(f"Type: {type_labels.get(filters['type'], filters['type'])}")
    if filters["outcome"]:
        active_filters.append(f"Outcome: {OUTCOME_LABELS[filters['outcome']]}")
    if filters["period"] != "all":
        active_filters.append(f"Period: {PERIODS[filters['period']][0]}")
    if filters["category"]:
        active_filters.append("Category: " + ", ".join(CATEGORY_LABELS[item] for item in filters["category"]))
    if filters["exceptions"]:
        active_filters.append("Exceptions only")
    if filters["synthetic"] == "exclude":
        active_filters.append("Generated sample excluded")
    uncopied_filters = []
    if filters["outcome"]:
        uncopied_filters.append("outcome")
    if filters["period"] != "all":
        uncopied_filters.append("period")
    if filters["exceptions"]:
        uncopied_filters.append("exceptions")
    if filters["synthetic"] == "exclude":
        uncopied_filters.append("generated sample")
    if uncopied_filters:
        whatif_scope_note = (
            "Copies permit type and business category only. "
            + ", ".join(uncopied_filters).capitalize()
            + " filters are not copied."
        )
    else:
        whatif_scope_note = "Copies permit type and business category only. No other active filter needs to be omitted."
    return {
        "filters": filters,
        "active_filters": active_filters,
        "filter_summary": "; ".join(active_filters) if active_filters else "All permit activity",
        "whatif_scope_note": whatif_scope_note,
        "query": _query(filters),
        "period_options": [{"key": k, "label": v[0]} for k, v in PERIODS.items()],
        "type_options": [{"key": k, "label": type_labels[k]} for k in sorted(type_labels)],
        "outcome_options": [{"key": k, "label": v} for k, v in OUTCOME_LABELS.items()],
        "category_options": [{"key": k, "label": v} for k, v in CATEGORY_LABELS.items()],
        "restaurants_and_bars": RESTAURANTS_AND_BARS,
        "total": len(rows),
        "total_before_filters": len(pool),
        "synthetic": {
            "available": synthetic_total,
            "included": included_synthetic,
            "mode": filters["synthetic"],
            "badge": "synthetic data",
            "note": (
                "Synthetic data is loaded: generated, flagged rows that are not real permits."
                if synthetic_total
                else "No synthetic data is loaded. The default reset holds the fixtures only."
            ),
        },
        "map": {
            "svg": drawing,
            "legend": [
                {"cls": f"s{level}", "label": label}
                for level, label in enumerate(["none", "fewest", "fewer", "more", "most"])
            ],
            "district_table": district_table,
            "unmapped": len(rows) - sum(district_counts.values()),
            "top_exception_parcels": top_exception_parcels,
        },
        "trend": {"svg": trend_svg, "rows": trend},
        "categories": {
            "rows": category_rows,
            "linked_to_business": linked_to_business,
            "dining_total": len(dining),
            "where_opening": where_opening,
        },
        "by_type": [
            {"key": k, "label": type_labels[k], "permits": c}
            for k, c in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "outcomes": [
            {"key": k, "label": OUTCOME_LABELS[k], "permits": outcome_counts.get(k, 0)}
            for k in OUTCOME_LABELS
        ],
        "exception_counts": [
            {"key": k, "label": EXCEPTION_LABELS[k], "permits": exception_counts.get(k, 0)}
            for k in EXCEPTION_LABELS
        ],
        "exception_permits": sum(1 for row in rows if row.exception_kinds),
        "rows": [
            {
                "number": r.number,
                "reference": r.permit_number or r.number,
                "type": r.type_label,
                "district": r.district,
                "parcel": r.parcel_number,
                "address": r.address,
                "submitted": r.submitted_at.date().isoformat() if r.submitted_at else "",
                "outcome": OUTCOME_LABELS[r.outcome_key],
                "category": CATEGORY_LABELS.get(r.category or "", ""),
                "exceptions": [EXCEPTION_LABELS[k] for k in r.exception_kinds],
                "synthetic": r.synthetic,
            }
            for r in table_rows
        ],
        "rows_shown": len(table_rows),
        "definitions": DEFINITIONS,
        "what_if": None,
    }


__all__ = ["CATEGORY_LABELS", "DEFINITIONS", "city_view", "parse_filters"]

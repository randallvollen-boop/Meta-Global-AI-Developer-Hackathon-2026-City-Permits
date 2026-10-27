"""Server-rendered SVG for the parcel inset and the town map.

No tiles, no CDN, no mapping library.  Every parcel, street, address point and
marker carries a ``<title>`` (the text label a screen reader reads), parcels are
links to the property record, and the pan and zoom script is progressive
enhancement: without it the map is a static picture with links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any

#: The marker letter and the plain-text label of every application status.
STATUS_MARKS: dict[str, tuple[str, str]] = {
    "draft": ("D", "Draft"),
    "submitted": ("S", "Submitted"),
    "needs_information": ("N", "Needs information"),
    "ready_for_review": ("R", "Ready for review"),
    "under_review": ("U", "Under review"),
    "approved": ("A", "Approved"),
    "denied": ("X", "Denied"),
    "withdrawn": ("W", "Withdrawn"),
    "issued": ("I", "Issued"),
}

#: The extent of the town grid.
EXTENT = (0.0, 0.0, 960.0, 700.0)


@dataclass
class MapParcel:
    """One parcel as the map draws it."""

    number: str
    site_address: str
    zoning: str
    rings: list[Any]
    href: str = ""
    applications: list[dict[str, Any]] = field(default_factory=list)
    role: str = ""  # subject | candidate | ""


@dataclass
class MapPoint:
    """A point to draw: an address point, a submitted point or a candidate."""

    x: float
    y: float
    label: str
    kind: str  # address | submitted | candidate


def _bounds(rings: list[Any]) -> tuple[float, float, float, float]:
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _path(rings: list[Any], flip: float) -> str:
    parts = []
    for ring in rings:
        coords = [f"{x:.1f},{flip - y:.1f}" for x, y in ring]
        parts.append("M" + " L".join(coords) + " Z")
    return " ".join(parts)


def _mark(status: str) -> tuple[str, str]:
    return STATUS_MARKS.get(status, ("?", status.replace("_", " ").capitalize()))


def _parcel_title(parcel: MapParcel) -> str:
    text = f"Parcel {parcel.number}, {parcel.site_address or 'no site address'}, zoning {parcel.zoning or 'unknown'}"
    if parcel.role == "subject":
        text += " (subject parcel)"
    elif parcel.role == "candidate":
        text += " (candidate parcel)"
    if parcel.applications:
        text += "; " + "; ".join(
            f"{item['number']} {_mark(item['status'])[1]}" for item in parcel.applications
        )
    return text


def _point_svg(point: MapPoint, flip: float, scale: float) -> str:
    cx, cy = point.x, flip - point.y
    r = 3.2 * scale
    title = f"<title>{escape(point.label)}</title>"
    if point.kind == "submitted":
        size = 5 * scale
        return (
            f'<g class="gis-point gis-submitted">{title}'
            f'<path d="M{cx - size:.1f},{cy:.1f} L{cx + size:.1f},{cy:.1f} M{cx:.1f},{cy - size:.1f} '
            f'L{cx:.1f},{cy + size:.1f}"/></g>'
        )
    if point.kind == "candidate":
        size = 4.5 * scale
        return (
            f'<g class="gis-point gis-candidate">{title}'
            f'<path d="M{cx:.1f},{cy - size:.1f} L{cx + size:.1f},{cy:.1f} L{cx:.1f},{cy + size:.1f} '
            f'L{cx - size:.1f},{cy:.1f} Z"/></g>'
        )
    return f'<g class="gis-point gis-address">{title}<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/></g>'


def _markers(parcels: list[MapParcel], flip: float, scale: float) -> str:
    out = []
    for parcel in parcels:
        if not parcel.applications:
            continue
        x0, y0, x1, y1 = _bounds(parcel.rings)
        for index, item in enumerate(parcel.applications[:3]):
            letter, label = _mark(item["status"])
            cx = x1 - 8 * scale - index * 15 * scale
            cy = flip - (y1 - 8 * scale)
            out.append(
                f'<g class="gis-marker st-{escape(item["status"])}" data-application="{escape(item["number"])}">'
                f"<title>{escape(item['number'])}: {escape(label)} on parcel {escape(parcel.number)}</title>"
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{6.5 * scale:.1f}"/>'
                f'<text x="{cx:.1f}" y="{cy + 2.6 * scale:.1f}" text-anchor="middle" '
                f'font-size="{8 * scale:.1f}">{escape(letter)}</text></g>'
            )
    return "".join(out)


def _parcel_group(parcel: MapParcel, flip: float, linked: bool) -> str:
    classes = f"gis-parcel zoning-{escape(parcel.zoning or 'none')}"
    if parcel.role:
        classes += f" is-{parcel.role}"
    attributes = (
        f'class="{classes}" data-parcel="{escape(parcel.number)}" '
        f'data-address="{escape(parcel.site_address)}"'
    )
    shape = (
        f"<title>{escape(_parcel_title(parcel))}</title>"
        f'<path d="{_path(parcel.rings, flip)}"/>'
    )
    if linked and parcel.href:
        return (
            f'<a href="{escape(parcel.href)}" aria-label="{escape(_parcel_title(parcel))}">'
            f"<g {attributes}>{shape}</g></a>"
        )
    return f"<g {attributes}>{shape}</g>"


def parcel_inset_svg(
    parcels: list[MapParcel],
    subject_number: str,
    points: list[MapPoint],
    *,
    caption: str,
    linked: bool,
    margin: float = 70.0,
) -> str:
    """Return a small SVG of the subject parcel, its neighbours and the points."""
    subject = next((p for p in parcels if p.number == subject_number), None)
    if subject is None:
        return ""
    x0, y0, x1, y1 = _bounds(subject.rings)
    xmin, xmax = x0 - margin, x1 + margin
    ymin, ymax = y0 - margin, y1 + margin
    flip = EXTENT[3]
    width, height = xmax - xmin, ymax - ymin
    drawn = []
    for parcel in parcels:
        bx0, by0, bx1, by1 = _bounds(parcel.rings)
        if bx1 < xmin or bx0 > xmax or by1 < ymin or by0 > ymax:
            continue
        drawn.append(parcel)
    scale = width / 260.0
    body = "".join(_parcel_group(p, flip, linked) for p in drawn)
    body += _markers(drawn, flip, scale)
    body += "".join(
        _point_svg(point, flip, scale)
        for point in points
        if xmin <= point.x <= xmax and ymin <= point.y <= ymax
    )
    return (
        f'<svg class="gis-svg gis-inset" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{xmin:.1f} {flip - ymax:.1f} {width:.1f} {height:.1f}" '
        f'aria-label="{escape(caption)}" data-testid="parcel-inset">'
        f"<title>{escape(caption)}</title>{body}</svg>"
    )


def town_map_svg(
    parcels: list[MapParcel],
    streets: list[dict[str, Any]],
    points: list[MapPoint],
    *,
    caption: str,
    linked: bool = True,
    focus: str = "",
) -> str:
    """Return the SVG of the whole fictional town."""
    xmin, ymin, xmax, ymax = EXTENT
    flip = ymax
    width, height = xmax - xmin, ymax - ymin
    street_svg = []
    for street in streets:
        path = street["path"]
        d = "M" + " L".join(f"{x:.1f},{flip - y:.1f}" for x, y in path)
        key = escape(str(street["street_key"]))
        street_svg.append(
            f'<g class="gis-street"><title>{escape(street["name"])}</title>'
            f'<path id="street-{key}" d="{d}"/></g>'
        )
        street_svg.append(
            f'<text class="gis-street-name" dy="-5"><textPath href="#street-{key}" startOffset="3%">'
            f"{escape(street['name'])}</textPath></text>"
        )
    parcel_svg = "".join(_parcel_group(p, flip, linked) for p in parcels)
    scale = 1.4
    body = (
        f'<g class="gis-layer-streets">{"".join(street_svg)}</g>'
        f'<g class="gis-layer-parcels">{parcel_svg}</g>'
        f'<g class="gis-layer-markers">{_markers(parcels, flip, scale)}</g>'
        f'<g class="gis-layer-points">{"".join(_point_svg(p, flip, scale) for p in points)}</g>'
    )
    return (
        f'<svg class="gis-svg gis-town" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{xmin:.0f} {0} {width:.0f} {height:.0f}" data-extent="{xmin:.0f} 0 {width:.0f} {height:.0f}" '
        f'data-focus="{escape(focus)}" aria-label="{escape(caption)}" data-testid="town-map">'
        f"<title>{escape(caption)}</title>{body}</svg>"
    )


def legend_html() -> str:
    """Return the text legend: colour is never the only signal."""
    items = "".join(
        f'<li><span class="gis-key st-{escape(status)}" aria-hidden="true">{escape(letter)}</span> '
        f"{escape(label)}</li>"
        for status, (letter, label) in STATUS_MARKS.items()
        if status not in {"draft", "withdrawn"}
    )
    return (
        '<ul class="gis-legend" data-testid="map-legend">'
        f"{items}"
        '<li><span class="gis-key gis-key-point" aria-hidden="true">&#9679;</span> Official address point</li>'
        '<li><span class="gis-key gis-key-point" aria-hidden="true">+</span> Point as submitted</li>'
        '<li><span class="gis-key gis-key-point" aria-hidden="true">&#9670;</span> Locator candidate</li>'
        "</ul>"
    )


__all__ = [
    "STATUS_MARKS",
    "MapParcel",
    "MapPoint",
    "legend_html",
    "parcel_inset_svg",
    "town_map_svg",
]

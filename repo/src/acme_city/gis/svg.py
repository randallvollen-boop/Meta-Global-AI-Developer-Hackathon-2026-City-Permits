"""Server-rendered SVG for the parcel inset and the town map.

No tiles, no CDN, no mapping library.  Every parcel, street, address point and
marker carries a ``<title>`` (the text label a screen reader reads), parcels are
links to the property record, and the pan and zoom script is progressive
enhancement: without it the map is a static picture with links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
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

#: The folder of the top down building pictures.  A file named after its
#: zoning district and a variant letter (``r1a.webp``, ``c2b.webp``) is one
#: picture for that district; dropping in another file adds a variant.
TILE_DIR = Path(__file__).resolve().parent.parent / "static" / "map-tiles"

#: The URL prefix of the building pictures.
TILE_URL = "/ui/static/map-tiles/"

#: The margin between the lot line and the building picture, in map units.
TILE_INSET = 2.0


def _zoning_tiles() -> dict[str, tuple[str, ...]]:
    """Return the building pictures of every zoning district, in a fixed order."""
    tiles: dict[str, tuple[str, ...]] = {}
    for code in ("R-1", "R-2", "C-1", "C-2", "PF"):
        stem = code.replace("-", "").lower()
        names = sorted(path.name for path in TILE_DIR.glob(f"{stem}*.webp"))
        if names:
            tiles[code] = tuple(TILE_URL + name for name in names)
    return tiles


#: The building pictures by zoning district.  Every picture shares one camera
#: height, a noon sun, the front at the bottom edge and the same lawn at the
#: other edges, so lots read as one neighbourhood once each faces its street.
ZONING_TILES: dict[str, tuple[str, ...]] = _zoning_tiles()


def _facing(parcel: MapParcel, streets: list[dict[str, Any]]) -> int:
    """Return the turn, in degrees, that points the front of a lot at its street.

    A picture has its front at the bottom edge.  The nearest street decides
    the turn: 0 when the street is below the lot on screen, 180 above, -90 to
    the right and 90 to the left.
    """
    x0, y0, x1, y1 = _bounds(parcel.rings)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best: tuple[float, int] | None = None
    for street in streets:
        path = street["path"]
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = 0.0 if length == 0 else max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / length))
            px, py = ax + t * dx, ay + t * dy
            distance = (px - cx) ** 2 + (py - cy) ** 2
            if abs(px - cx) >= abs(py - cy):
                turn = -90 if px > cx else 90
            else:
                turn = 0 if py < cy else 180  # map y grows upward; screen y grows down
            if best is None or distance < best[0]:
                best = (distance, turn)
    return best[1] if best else 0


def _parcel_seed(parcel: MapParcel) -> int:
    digits = "".join(ch for ch in parcel.number if ch.isdigit())
    return int(digits) if digits else sum(map(ord, parcel.number))


def _building_svg(parcel: MapParcel, flip: float, streets: list[dict[str, Any]]) -> str:
    """Return the building picture of one lot, turned to face its street."""
    tiles = ZONING_TILES.get(parcel.zoning)
    if not tiles:
        return ""
    seed = _parcel_seed(parcel)
    tile = tiles[seed % len(tiles)]
    mirror = (seed // len(tiles)) % 2 == 1
    x0, y0, x1, y1 = _bounds(parcel.rings)
    size = min(x1 - x0, y1 - y0) - 2 * TILE_INSET
    cx, cy = (x0 + x1) / 2, flip - (y0 + y1) / 2
    turn = _facing(parcel, streets) if streets else 0
    transform = f"rotate({turn} {cx:.1f} {cy:.1f})" if turn else ""
    if mirror:
        transform += f" translate({2 * cx:.1f} 0) scale(-1 1)"
    attribute = f' transform="{transform.strip()}"' if transform else ""
    return (
        f'<image class="gis-building" href="{tile}" '
        f'x="{cx - size / 2:.1f}" y="{cy - size / 2:.1f}" '
        f'width="{size:.1f}" height="{size:.1f}" preserveAspectRatio="xMidYMid slice"{attribute}/>'
    )


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


def _parcel_group(
    parcel: MapParcel, flip: float, linked: bool, streets: list[dict[str, Any]] | None = None
) -> str:
    classes = f"gis-parcel zoning-{escape(parcel.zoning or 'none')}"
    if parcel.role:
        classes += f" is-{parcel.role}"
    attributes = (
        f'class="{classes}" data-parcel="{escape(parcel.number)}" '
        f'data-address="{escape(parcel.site_address)}"'
    )
    d = _path(parcel.rings, flip)
    shape = (
        f"<title>{escape(_parcel_title(parcel))}</title>"
        f'<path d="{d}"/>'
    )
    building = _building_svg(parcel, flip, streets or [])
    if building:
        shape += building + f'<path class="gis-lot" d="{d}"/>'
    if linked and parcel.href:
        return (
            f'<a href="{escape(parcel.href)}" aria-label="{escape(_parcel_title(parcel))}">'
            f"<g {attributes}>{shape}</g></a>"
        )
    return f"<g {attributes}>{shape}</g>"


def _street_svg(street: dict[str, Any], flip: float, *, named: bool) -> str:
    """Return one street: a sidewalk band, the asphalt and, on the town map, its name."""
    d = "M" + " L".join(f"{x:.1f},{flip - y:.1f}" for x, y in street["path"])
    key = escape(str(street["street_key"]))
    path_id = f' id="street-{key}"' if named else ""
    out = (
        f'<g class="gis-street"><title>{escape(street["name"])}</title>'
        f'<path class="gis-sidewalk" d="{d}"/><path class="gis-asphalt"{path_id} d="{d}"/></g>'
    )
    if named:
        out += (
            f'<text class="gis-street-name" dy="3"><textPath href="#street-{key}" startOffset="3%">'
            f"{escape(street['name'])}</textPath></text>"
        )
    return out


def parcel_inset_svg(
    parcels: list[MapParcel],
    subject_number: str,
    points: list[MapPoint],
    *,
    caption: str,
    linked: bool,
    margin: float = 70.0,
    streets: list[dict[str, Any]] | None = None,
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
    body = f'<rect class="gis-ground" x="{xmin:.1f}" y="{flip - ymax:.1f}" width="{width:.1f}" height="{height:.1f}"/>'
    body += "".join(_street_svg(street, flip, named=False) for street in streets or [])
    body += "".join(_parcel_group(p, flip, linked, streets) for p in drawn)
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
    street_svg = [_street_svg(street, flip, named=True) for street in streets]
    parcel_svg = "".join(_parcel_group(p, flip, linked, streets) for p in parcels)
    scale = 1.4
    body = (
        f'<rect class="gis-ground" x="{xmin:.0f}" y="0" width="{width:.0f}" height="{height:.0f}"/>'
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


def district_map_svg(
    parcels: list[MapParcel],
    streets: list[dict[str, Any]],
    shade: dict[str, int | None],
    labels: dict[str, str],
    dots: list[dict[str, Any]],
    *,
    caption: str,
) -> str:
    """Return the district-shaded map of permit activity.

    Every parcel takes the shade of its zoning district (``None`` means the
    figure is suppressed and the district is hatched, not shaded).  A district
    label prints the district code and its figure on the map, so colour is
    never the only signal.  ``dots`` mark parcels with exceptions: each has a
    ``parcel`` number, a ``count`` and a ``title``; the dot grows with the
    count, which makes a cluster visible.
    """
    xmin, ymin, xmax, ymax = EXTENT
    flip = ymax
    width, height = xmax - xmin, ymax - ymin
    street_svg = []
    for street in streets:
        d = "M" + " L".join(f"{x:.1f},{flip - y:.1f}" for x, y in street["path"])
        street_svg.append(
            f'<g class="gis-street"><title>{escape(street["name"])}</title><path d="{d}"/></g>'
        )
    parcel_svg = []
    boxes: dict[str, list[float]] = {}
    centres: dict[str, tuple[float, float]] = {}
    for parcel in parcels:
        level = shade.get(parcel.zoning)
        css = "insight-hatch" if level is None else f"insight-shade-{level}"
        x0, y0, x1, y1 = _bounds(parcel.rings)
        centres[parcel.number] = ((x0 + x1) / 2, flip - (y0 + y1) / 2)
        box = boxes.setdefault(parcel.zoning, [x0, y0, x1, y1])
        box[0], box[1] = min(box[0], x0), min(box[1], y0)
        box[2], box[3] = max(box[2], x1), max(box[3], y1)
        title = f"Parcel {parcel.number}, {parcel.site_address or 'no site address'}, district {parcel.zoning or 'unknown'}"
        parcel_svg.append(
            f'<g class="insight-parcel {css}" data-parcel="{escape(parcel.number)}" '
            f'data-district="{escape(parcel.zoning)}"><title>{escape(title)}</title>'
            f'<path d="{_path(parcel.rings, flip)}"/></g>'
        )
    label_svg = []
    for code, box in sorted(boxes.items()):
        cx, cy = (box[0] + box[2]) / 2, flip - (box[1] + box[3]) / 2
        text = labels.get(code, "")
        label_svg.append(
            f'<g class="insight-district-label" data-district="{escape(code)}">'
            f'<text x="{cx:.1f}" y="{cy - 6:.1f}" text-anchor="middle" class="insight-district-code">{escape(code)}</text>'
            f'<text x="{cx:.1f}" y="{cy + 18:.1f}" text-anchor="middle" class="insight-district-figure">{escape(text)}</text>'
            "</g>"
        )
    dot_svg = []
    for dot in dots:
        centre = centres.get(str(dot["parcel"]))
        if centre is None:
            continue
        radius = min(5.0 + 2.2 * (float(dot["count"]) ** 0.5), 18.0)
        dot_svg.append(
            f'<g class="insight-dot" data-parcel="{escape(str(dot["parcel"]))}" data-count="{int(dot["count"])}">'
            f'<title>{escape(str(dot["title"]))}</title>'
            f'<circle cx="{centre[0]:.1f}" cy="{centre[1]:.1f}" r="{radius:.1f}"/>'
            f'<text x="{centre[0]:.1f}" y="{centre[1] + 3.2:.1f}" text-anchor="middle">{int(dot["count"])}</text></g>'
        )
    defs = (
        '<defs><pattern id="insight-hatch" width="8" height="8" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="8" height="8" class="insight-hatch-bg"/>'
        '<path d="M0 0 L0 8" class="insight-hatch-line"/></pattern></defs>'
    )
    body = (
        f'<g class="gis-layer-streets">{"".join(street_svg)}</g>'
        f'<g class="insight-layer-parcels">{"".join(parcel_svg)}</g>'
        f'<g class="insight-layer-labels">{"".join(label_svg)}</g>'
        f'<g class="insight-layer-dots">{"".join(dot_svg)}</g>'
    )
    return (
        f'<svg class="gis-svg gis-town insight-map" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{xmin:.0f} 0 {width:.0f} {height:.0f}" aria-label="{escape(caption)}" '
        f'data-testid="insight-map"><title>{escape(caption)}</title>{defs}{body}</svg>'
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
    "ZONING_TILES",
    "district_map_svg",
    "MapParcel",
    "MapPoint",
    "legend_html",
    "parcel_inset_svg",
    "town_map_svg",
]

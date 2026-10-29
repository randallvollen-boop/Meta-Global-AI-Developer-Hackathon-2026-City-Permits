"""Building pictures on the town map face their street and vary along it."""

from __future__ import annotations

from acme_city.gis import svg

STREETS = [
    {"street_key": "marrow", "name": "Marrow Creek Road", "path": [[40, 150], [940, 150]]},
    {"street_key": "heron", "name": "Heron Street", "path": [[250, 40], [250, 660]]},
]


def _lot(number: str, x0: float, y0: float, zoning: str = "R-1") -> svg.MapParcel:
    ring = [[x0, y0], [x0 + 54, y0], [x0 + 54, y0 + 54], [x0, y0 + 54], [x0, y0]]
    return svg.MapParcel(number=number, site_address="", zoning=zoning, rings=[ring])


def test_each_lot_turns_its_front_to_the_nearest_street() -> None:
    # Map y grows upward: a lot north of Marrow Creek Road sits above it on screen.
    assert svg._facing(_lot("1", 60, 162), STREETS) == 0  # street below on screen
    assert svg._facing(_lot("2", 60, 82), STREETS) == 180  # street above on screen
    assert svg._facing(_lot("3", 268, 223), STREETS) == 90  # street to the left
    assert svg._facing(_lot("4", 176, 223), STREETS) == -90  # street to the right


def test_neighbouring_lots_do_not_repeat_the_same_picture() -> None:
    if len(svg.ZONING_TILES.get("R-1", ())) < 2:
        return
    first = svg._building_svg(_lot("ACME-P-1014", 60, 82), 700.0, STREETS)
    second = svg._building_svg(_lot("ACME-P-1015", 118, 82), 700.0, STREETS)
    assert first and second and first.split('href="')[1] != second.split('href="')[1]


def test_a_zoning_without_pictures_keeps_the_plain_lot() -> None:
    assert svg._building_svg(_lot("9", 60, 82, zoning="X-9"), 700.0, STREETS) == ""


def test_the_city_view_map_draws_the_same_town_as_the_town_map() -> None:
    lots = [_lot("ACME-P-1014", 60, 82), _lot("ACME-P-1015", 118, 82, zoning="C-2")]
    town = svg.town_map_svg(lots, STREETS, [], caption="Town")
    city = svg.district_map_svg(lots, STREETS, {"R-1": 2, "C-2": None}, {}, [], caption="City")
    view = lambda drawing: drawing.split('viewBox="')[1].split('"')[0]
    assert view(city) == view(town)
    for part in ('class="gis-ground"', 'class="gis-asphalt"', ">Heron Street</textPath>"):
        assert part in city
    assert city.count('class="gis-building"') == town.count('class="gis-building"') > 0
    # The shade is a tint over the building, so the picture shows through it.
    tint = city.split('data-parcel="ACME-P-1014"')[1].split("</g>")[0]
    assert tint.index('class="gis-building"') < tint.index('class="insight-tint"')
    assert f'fill-opacity="{svg.TINT_OPACITY}"' in tint and 0 < svg.TINT_OPACITY < 1
    assert 'class="insight-parcel insight-hatch"' in city

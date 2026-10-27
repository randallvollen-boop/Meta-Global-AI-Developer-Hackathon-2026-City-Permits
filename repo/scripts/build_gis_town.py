#!/usr/bin/env python3
"""Build ``fixtures/gis_town.json``: the synthetic town the simulated GIS serves.

The town is a small fictional grid (metres, east and north).  Every parcel is
a rectangle, every official address point falls inside its parcel, and every
name, owner and value is invented.  The output is deterministic, so running
this script twice writes the same bytes.

The two parcels and the addresses already in ``base_population.json`` keep
their identifiers; this file only adds attributes to them and adds the rest of
the town.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "fixtures" / "gis_town.json"

#: street key -> (name, road type, centreline, postcode)
STREETS: dict[str, tuple[str, str, list[list[int]], str]] = {
    "marrow": ("Marrow Creek Road", "Road", [[40, 150], [940, 150]], "ACM-01402"),
    "lantern": ("Lantern Row", "Row", [[40, 350], [940, 350]], "ACM-01401"),
    "kestrel": ("Kestrel Way", "Way", [[40, 550], [940, 550]], "ACM-01403"),
    "heron": ("Heron Street", "Street", [[250, 40], [250, 660]], "ACM-01405"),
    "maple": ("Maple Ridge Drive", "Drive", [[880, 20], [880, 690]], "ACM-01404"),
    "kestrelct": ("Kestrel Court", "Court", [[740, 550], [740, 690]], "ACM-01403"),
}

ZONING = [
    ("R-1", "Low-density residential", "Detached homes on larger lots."),
    ("R-2", "Medium-density residential", "Smaller lots, duplexes and townhouses."),
    ("C-1", "Neighbourhood commercial", "Small shops and offices that serve nearby homes."),
    ("C-2", "General commercial", "Retail, restaurants and services on main streets."),
    ("PF", "Public facility", "Municipal and civic land."),
]

OWNERS = [
    "Brindle Household", "Ostrander Family Trust", "Calloway Holdings LLC", "Vesper Household",
    "Harrow Street Properties LLC", "Pennick Household", "Lorimer Family Trust", "Dunmore Household",
    "Thistle & Moss Partners", "Quill Household", "Ashgrove Holdings LLC", "Fenwick Household",
    "Marlowe Family Trust", "Sedgewick Household", "Wren Hollow Properties LLC", "Tarrant Household",
    "Elmstead Family Trust", "Birchfield Household", "Cobalt Row Holdings LLC", "Alder Household",
]

# (street key, side, x ranges as (start, count)) -> parcels run left to right.
E_W_BLOCKS = [(60, 3), (268, 3), (518, 3)]
PARCEL_W = 54
STEP = 58
DEPTH = 56
OFFSET = 12


def rect(x0: float, y0: float, x1: float, y1: float) -> list[list[list[float]]]:
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]


def build() -> dict:
    parcels: list[dict] = []
    addresses: list[dict] = []
    relations: list[dict] = []
    sequence = {"next": 1006}
    fixed_ids = {
        ("lantern", 400): 1001,
        ("marrow", 12): 1002,
        ("kestrel", 88): 1003,
        ("maple", 412): 1004,
        ("kestrelct", 88): 1005,
    }
    fixed_address = {
        ("lantern", 400): "address_400_lantern",
        ("marrow", 12): "address_12_marrow",
    }

    def add_parcel(street: str, number: int, x0: float, y0: float, x1: float, y1: float) -> None:
        name, _road_type, _path, postcode = STREETS[street]
        pid = fixed_ids.get((street, number))
        if pid is None:
            pid = sequence["next"]
            sequence["next"] += 1
        index = len(parcels)
        zoning = {"marrow": "R-1", "lantern": "C-2", "kestrel": "R-2", "heron": "R-1",
                  "maple": "R-1", "kestrelct": "R-2"}[street]
        use = {"R-1": ("111", "Single-family dwelling"), "R-2": ("113", "Two-family dwelling"),
               "C-2": ("401", "Retail with upper units"), "C-1": ("403", "Neighbourhood office")}[zoning]
        acres = round(((x1 - x0) * (y1 - y0)) / 4046.86 * 6, 2)  # the grid is a stylised 1:6 map
        flood = "AE" if (street == "marrow" and y1 <= 150) else "X"
        land = 3_200_000 + (index % 7) * 410_000
        building = 9_800_000 + (index % 5) * 1_350_000 if zoning != "C-2" else 21_500_000 + (index % 3) * 2_800_000
        parcel = {
            "parcel_id": f"parcel_{pid}",
            "source_parcel_number": f"ACME-P-{pid}",
            "owner_name": OWNERS[index % len(OWNERS)],
            "use_code": use[0],
            "use_description": use[1],
            "zoning_code": zoning,
            "subdivision": {"marrow": "Marrow Creek Terrace", "lantern": "Lantern Row Commons",
                            "kestrel": "Kestrel Heights", "heron": "Heron Park",
                            "maple": "Maple Ridge Estates", "kestrelct": "Kestrel Heights"}[street],
            "area_acres": acres,
            "land_value_cents": land,
            "improvement_value_cents": building,
            "tax_district": "TD-01" if x0 < 480 else "TD-02",
            "school_district": "ACME City School District",
            "flood_zone": flood,
            "geometry": rect(x0, y0, x1, y1),
            "department_signals": {
                "fire_last_inspection": f"2025-{1 + index % 12:02d}-{1 + (index * 3) % 27:02d}",
                "code_open_cases": 0,
                "utility_account_active": True,
            },
        }
        parcels.append(parcel)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        aid = fixed_address.get((street, number), f"address_{number}_{street}")
        full = f"{number} {name}"
        address = {
            "address_id": aid,
            "street_number": str(number),
            "street_name": name,
            "street_type": name.split()[-1],
            "unit_type": None,
            "unit_number": None,
            "municipality": "ACME City",
            "region": "AC",
            "postcode": postcode,
            "source_string": full,
            "status": "active",
            "x": cx,
            "y": cy,
        }
        addresses.append(address)
        relations.append(
            {
                "relationship_id": f"pa_{pid}_building" if pid > 1002 else None,
                "parcel_id": parcel["parcel_id"],
                "address_id": aid,
                "relationship_type": "official_address",
            }
        )

    # East-west streets: a north side (even numbers) and a south side (odd).
    starts = {"marrow": 10, "lantern": 400, "kestrel": 86}
    counts = {
        "marrow": {"north": [3, 3, 3], "south": [3, 3, 3]},
        "lantern": {"north": [3, 3, 3], "south": [3, 3, 3]},
        "kestrel": {"north": [3, 3, 2], "south": [3, 3, 3]},
    }
    for street, first in starts.items():
        sy = STREETS[street][2][0][1]
        for side in ("north", "south"):
            number = first if side == "north" else first + 1
            for (x_start, _), count in zip(E_W_BLOCKS, counts[street][side], strict=True):
                for slot in range(count):
                    x0 = x_start + slot * STEP
                    if side == "north":
                        y0, y1 = sy + OFFSET, sy + OFFSET + DEPTH
                    else:
                        y0, y1 = sy - OFFSET - DEPTH, sy - OFFSET
                    add_parcel(street, number, x0, y0, x0 + PARCEL_W, y1)
                    number += 2

    # Kestrel Court and Maple Ridge Drive run north-south.
    for number, slot in ((86, 0), (88, 1)):
        y0 = 566 + slot * (DEPTH + 4)
        add_parcel("kestrelct", number, 752, y0, 752 + PARCEL_W, y0 + DEPTH)
    for number, slot in ((85, 0), (87, 1)):
        y0 = 566 + slot * (DEPTH + 4)
        add_parcel("kestrelct", number, 740 - OFFSET - PARCEL_W, y0, 740 - OFFSET, y0 + DEPTH)
    slots = [(24, 78), (224, 278), (424, 478), (624, 678)]
    for index, (y0, y1) in enumerate(slots):
        add_parcel("maple", 410 + 2 * index, 892, y0, 892 + PARCEL_W, y1)
        add_parcel("maple", 411 + 2 * index, 880 - OFFSET - PARCEL_W, y0, 880 - OFFSET, y1)
    # Heron Street: one parcel in each gap between the east-west rows.
    for number, (y0, y1) in zip((20, 22, 24, 26), [(20, 76), (224, 276), (424, 476), (626, 682)], strict=True):
        add_parcel("heron", number, 250 + OFFSET, y0, 250 + OFFSET + PARCEL_W, y1)

    # Units: 400 Lantern Row keeps the two official units of the base population.
    units = [
        ("address_400_lantern_unit_2", "2", "gis:GIS-AD-0400-U2", "pa_1001_unit_2", -9, -4),
        ("address_400_lantern_unit_5", "5", "gis:GIS-AD-0400-U5", "pa_1001_unit_5", 9, 4),
    ]
    base = next(a for a in addresses if a["address_id"] == "address_400_lantern")
    for aid, unit, _ref, rid, dx, dy in units:
        addresses.append(
            {
                "address_id": aid,
                "street_number": "400",
                "street_name": "Lantern Row",
                "street_type": "Row",
                "unit_type": "unit",
                "unit_number": unit,
                "municipality": "ACME City",
                "region": "AC",
                "postcode": "ACM-01401",
                "source_string": f"400 Lantern Row Unit {unit}",
                "status": "active",
                "x": base["x"] + dx,
                "y": base["y"] + dy,
            }
        )
        relations.append(
            {
                "relationship_id": rid,
                "parcel_id": "parcel_1001",
                "address_id": aid,
                "relationship_type": "official_unit",
            }
        )
    for relation in relations:
        if relation["relationship_id"] is None:
            relation["relationship_id"] = f"pa_{relation['parcel_id'].split('_')[1]}_building"
        if relation["relationship_id"] == "pa_1001_building" or relation["relationship_id"] == "pa_1002_building":
            relation["base"] = True

    return {
        "fixture_version": "gis-town-1",
        "fictional_demo": True,
        "note": (
            "The synthetic town the simulated ArcGIS services serve. Every name, owner, value and "
            "coordinate is invented. Parcels 1001 and 1002 and their addresses extend "
            "base_population.json; everything else is added."
        ),
        "spatial_reference": {"name": "ACME City local grid (simulated)", "unit": "metre"},
        "extent": {"xmin": 0, "ymin": 0, "xmax": 960, "ymax": 700},
        "zoning_districts": [
            {"code": code, "name": name, "description": description} for code, name, description in ZONING
        ],
        "streets": [
            {"street_key": key, "name": name, "road_type": road_type, "path": path}
            for key, (name, road_type, path, _postcode) in STREETS.items()
        ],
        "parcels": parcels,
        "addresses": addresses,
        "parcel_addresses": relations,
    }


def main() -> int:
    document = build()
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: {len(document['parcels'])} parcels, "
        f"{len(document['addresses'])} addresses"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

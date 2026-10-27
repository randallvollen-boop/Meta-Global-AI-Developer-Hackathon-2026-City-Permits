"""Read access to the property master, in ArcGIS-shaped records.

The simulated services and the map read the same registry tables; this module
turns rows into the LGIM-style attribute dictionaries and the geometry the
services return.  Nothing here writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.gis import scoring
from acme_city.persistence.models import gis, registry

SPATIAL_REFERENCE: dict[str, Any] = {
    "wkt": 'LOCAL_CS["ACME City local grid (simulated)", UNIT["metre", 1]]',
}

MUNICIPALITY = "ACME City"
REGION = "AC"

#: The labelling every simulated response and page carries.
SIMULATED_LABEL = (
    "Simulated ArcGIS REST service of ACME City. Every parcel, address, owner and value "
    "is synthetic. This is not a real GIS."
)

PARCEL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("OBJECTID", "esriFieldTypeOID", "Object ID"),
    ("PARCELID", "esriFieldTypeString", "Parcel number"),
    ("SITEADDRESS", "esriFieldTypeString", "Site address"),
    ("OWNERNME1", "esriFieldTypeString", "Owner (synthetic)"),
    ("USECD", "esriFieldTypeString", "Land use code"),
    ("USEDSCRP", "esriFieldTypeString", "Land use description"),
    ("ZONING", "esriFieldTypeString", "Zoning district"),
    ("CNVYNAME", "esriFieldTypeString", "Subdivision"),
    ("STATEAREA", "esriFieldTypeDouble", "Area (acres)"),
    ("LNDVALUE", "esriFieldTypeDouble", "Land value"),
    ("IMPVALUE", "esriFieldTypeDouble", "Improvement value"),
    ("CNTASSDVAL", "esriFieldTypeDouble", "Total assessed value"),
    ("TAXDIST", "esriFieldTypeString", "Tax district"),
    ("SCHLDSCRP", "esriFieldTypeString", "School district"),
    ("FLOODZONE", "esriFieldTypeString", "Flood zone"),
)

ADDRESS_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("OBJECTID", "esriFieldTypeOID", "Object ID"),
    ("ADDRESSID", "esriFieldTypeString", "Address identifier"),
    ("FULLADDR", "esriFieldTypeString", "Full address"),
    ("ADDNUM", "esriFieldTypeString", "Address number"),
    ("ROADNAME", "esriFieldTypeString", "Road name"),
    ("UNITID", "esriFieldTypeString", "Unit"),
    ("PARCELID", "esriFieldTypeString", "Parcel number"),
)


def full_address(address: registry.Address) -> str:
    """Return the official one-line address, with its municipality and postcode."""
    return (
        f"{address.source_string}, {address.municipality or MUNICIPALITY}, "
        f"{address.region or REGION} {address.postcode or ''}"
    ).strip()


@dataclass(frozen=True)
class AddressRecord:
    """One official address with its parcel."""

    address: registry.Address
    parcel_number: str | None
    parcel_row_id: str | None


class PropertyCatalog:
    """The shared property master as the simulated GIS sees it."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._parcels: list[registry.Parcel] | None = None
        self._addresses: list[AddressRecord] | None = None
        self._by_address_parcel: dict[str, list[str]] = {}

    # ----------------------------------------------------------------- parcels

    def parcels(self) -> list[registry.Parcel]:
        if self._parcels is None:
            self._parcels = sorted(
                self._session.execute(
                    select(registry.Parcel).where(registry.Parcel.geometry.is_not(None))
                ).scalars().all(),
                key=lambda row: row.source_parcel_number,
            )
        return self._parcels

    def parcel_by_number(self, number: str) -> registry.Parcel | None:
        wanted = number.strip().upper()
        for row in self.parcels():
            if row.source_parcel_number.upper() == wanted:
                return row
        return None

    def parcel_by_id(self, parcel_id: str) -> registry.Parcel | None:
        for row in self.parcels():
            if row.parcel_id == parcel_id:
                return row
        return None

    def object_id(self, parcel: registry.Parcel) -> int:
        return self.parcels().index(parcel) + 1

    def site_address(self, parcel: registry.Parcel) -> str:
        rows = [
            record
            for record in self.addresses()
            if record.parcel_row_id == parcel.id and not record.address.unit_number
        ]
        if rows:
            return rows[0].address.source_string or ""
        rows = [record for record in self.addresses() if record.parcel_row_id == parcel.id]
        return rows[0].address.source_string or "" if rows else ""

    def parcel_attributes(self, parcel: registry.Parcel) -> dict[str, Any]:
        land = (parcel.land_value_cents or 0) / 100
        improvements = (parcel.improvement_value_cents or 0) / 100
        return {
            "OBJECTID": self.object_id(parcel),
            "PARCELID": parcel.source_parcel_number,
            "SITEADDRESS": self.site_address(parcel),
            "OWNERNME1": parcel.owner_name,
            "USECD": parcel.use_code,
            "USEDSCRP": parcel.use_description,
            "ZONING": parcel.zoning_code,
            "CNVYNAME": parcel.subdivision,
            "STATEAREA": parcel.area_acres,
            "LNDVALUE": land,
            "IMPVALUE": improvements,
            "CNTASSDVAL": land + improvements,
            "TAXDIST": parcel.tax_district,
            "SCHLDSCRP": parcel.school_district,
            "FLOODZONE": parcel.flood_zone,
        }

    @staticmethod
    def parcel_geometry(parcel: registry.Parcel) -> dict[str, Any]:
        return {"rings": parcel.geometry, "spatialReference": SPATIAL_REFERENCE}

    def parcel_at(self, x: float, y: float) -> registry.Parcel | None:
        for row in self.parcels():
            if _ring_contains(row.geometry[0], x, y):
                return row
        return None

    # -------------------------------------------------------------- addresses

    def addresses(self) -> list[AddressRecord]:
        if self._addresses is None:
            relations = self._session.execute(select(registry.ParcelAddress)).scalars().all()
            parcel_of = {
                relation.address_id: relation.parcel_id
                for relation in relations
                if relation.effective_to is None
            }
            parcel_numbers = {
                row.id: row.source_parcel_number
                for row in self._session.execute(select(registry.Parcel)).scalars().all()
            }
            rows = self._session.execute(
                select(registry.Address).where(registry.Address.status == "active")
            ).scalars().all()
            records = [
                AddressRecord(
                    address=row,
                    parcel_number=parcel_numbers.get(parcel_of.get(row.id, "")),
                    parcel_row_id=parcel_of.get(row.id),
                )
                for row in rows
                if row.x is not None and row.y is not None
            ]
            records.sort(key=lambda record: record.address.source_string or "")
            self._addresses = records
        return self._addresses

    def address_by_id(self, address_id: str) -> AddressRecord | None:
        for record in self.addresses():
            if record.address.address_id == address_id or record.address.id == address_id:
                return record
        return None

    def address_attributes(self, record: AddressRecord, index: int) -> dict[str, Any]:
        address = record.address
        return {
            "OBJECTID": index + 1,
            "ADDRESSID": address.address_id,
            "FULLADDR": address.source_string,
            "ADDNUM": address.street_number,
            "ROADNAME": address.street_name,
            "UNITID": address.unit_number,
            "PARCELID": record.parcel_number,
        }

    # ------------------------------------------------------------------- geocode

    def candidates(
        self,
        text: str,
        *,
        max_locations: int = 5,
        min_score: int = scoring.DEFAULT_MIN_SCORE,
    ) -> list[dict[str, Any]]:
        """Return ArcGIS-style candidates for one line of address text."""
        query = scoring.parse_address(text)
        if not query.street:
            return []
        scored: list[tuple[int, str, AddressRecord, list[str]]] = []
        for record in self.addresses():
            address = record.address
            official = scoring.parse_components(
                number=address.street_number,
                street_name=address.street_name,
                unit=address.unit_number,
                postcode=address.postcode,
            )
            score, reasons = scoring.score_candidate(query, official)
            if score >= min_score:
                scored.append((score, address.source_string or "", record, reasons))
        scored.sort(key=lambda item: (-item[0], item[1]))
        top_scores = [item[0] for item in scored[:2]]
        tied_top = len(top_scores) == 2 and top_scores[0] == top_scores[1]
        result: list[dict[str, Any]] = []
        for rank, (score, _label, record, reasons) in enumerate(scored[:max_locations]):
            tied = tied_top and score == scored[0][0]
            result.append(
                self._candidate(record, score, "T" if tied else "M", reasons)
            )
        return result

    def candidate_for(self, address_id: str, *, score: int = 100) -> dict[str, Any] | None:
        record = self.address_by_id(address_id)
        if record is None:
            return None
        return self._candidate(record, score, "M", ["selected from the suggestions"])

    def _candidate(
        self, record: AddressRecord, score: int, status: str, reasons: list[str]
    ) -> dict[str, Any]:
        address = record.address
        label = full_address(address)
        return {
            "address": label,
            "location": {"x": address.x, "y": address.y},
            "score": score,
            "attributes": {
                "Match_addr": label,
                "LongLabel": label,
                "Addr_type": "SubAddress" if address.unit_number else "PointAddress",
                "Status": status,
                "Score": score,
                "StAddr": address.source_string,
                "City": address.municipality or MUNICIPALITY,
                "Region": address.region or REGION,
                "Postal": address.postcode,
                "ADDRESSID": address.address_id,
                "PARCELID": record.parcel_number,
                "ScoreNotes": "; ".join(reasons),
            },
        }

    def suggestions(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in self.addresses():
            if scoring.prefix_match(text, record.address.source_string or ""):
                results.append(
                    {
                        "text": full_address(record.address),
                        "magicKey": record.address.address_id,
                        "isCollection": False,
                    }
                )
            if len(results) >= limit:
                break
        return results

    def nearest_address(self, x: float, y: float, within: float = 60.0) -> AddressRecord | None:
        best: tuple[float, str, AddressRecord] | None = None
        for record in self.addresses():
            distance = ((record.address.x - x) ** 2 + (record.address.y - y) ** 2) ** 0.5
            key = (distance, record.address.source_string or "")
            if best is None or key < best[:2]:
                best = (distance, record.address.source_string or "", record)
        if best is None or best[0] > within:
            return None
        return best[2]

    # ------------------------------------------------------------ town overview

    def streets(self) -> list[gis.GisStreet]:
        return list(
            self._session.execute(select(gis.GisStreet).order_by(gis.GisStreet.street_key))
            .scalars()
            .all()
        )

    def zoning_districts(self) -> dict[str, gis.ZoningDistrict]:
        return {
            row.code: row
            for row in self._session.execute(select(gis.ZoningDistrict)).scalars().all()
        }


def _ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    """Return whether a point is inside a ring (ray casting; the edge counts)."""
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    if len(ring) == 5 and len(set(xs)) == 2 and len(set(ys)) == 2:
        return min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys)
    inside = False
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        if (y1 > y) != (y2 > y):
            cross = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < cross:
                inside = not inside
    return inside


_CLAUSE = re.compile(
    r"^\s*(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?:(?P<op>=|<>|!=|LIKE|IN)\s*(?P<value>.+?))\s*$",
    re.IGNORECASE,
)


class WhereError(ValueError):
    """The ``where`` clause is outside what the simulator supports."""


def parse_where(where: str, allowed: set[str]) -> list[tuple[str, str, Any]]:
    """Parse a conjunction of simple clauses into ``(field, operator, value)``."""
    text = (where or "").strip()
    if not text or text in {"1=1", "1 = 1"}:
        return []
    clauses: list[tuple[str, str, Any]] = []
    for part in re.split(r"\s+AND\s+", text, flags=re.IGNORECASE):
        if part.strip() in {"1=1", "1 = 1"}:
            continue
        match = _CLAUSE.match(part)
        if match is None:
            raise WhereError(f"cannot parse {part!r}")
        field = match.group("field").upper()
        if field not in allowed:
            raise WhereError(f"unknown field {field!r}")
        operator = match.group("op").upper()
        raw = match.group("value").strip()
        if operator == "IN":
            if not (raw.startswith("(") and raw.endswith(")")):
                raise WhereError("IN needs a parenthesised list")
            values = [_literal(item) for item in _split_list(raw[1:-1])]
            clauses.append((field, "IN", values))
        else:
            clauses.append((field, operator, _literal(raw)))
    return clauses


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _literal(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def matches(attributes: dict[str, Any], clauses: list[tuple[str, str, Any]]) -> bool:
    """Return whether a record satisfies every clause."""
    for field, operator, value in clauses:
        actual = attributes.get(field)
        actual_text = "" if actual is None else str(actual)
        if operator == "=":
            if actual_text.upper() != str(value).upper():
                return False
        elif operator in {"<>", "!="}:
            if actual_text.upper() == str(value).upper():
                return False
        elif operator == "LIKE":
            pattern = "^" + ".*".join(re.escape(part) for part in str(value).upper().split("%")) + "$"
            if not re.match(pattern, actual_text.upper()):
                return False
        elif operator == "IN":
            if actual_text.upper() not in {str(item).upper() for item in value}:
                return False
    return True


__all__ = [
    "ADDRESS_FIELDS",
    "MUNICIPALITY",
    "PARCEL_FIELDS",
    "SIMULATED_LABEL",
    "SPATIAL_REFERENCE",
    "AddressRecord",
    "PropertyCatalog",
    "WhereError",
    "full_address",
    "matches",
    "parse_where",
]

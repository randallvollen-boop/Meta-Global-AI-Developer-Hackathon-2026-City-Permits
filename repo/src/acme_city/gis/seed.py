"""Seed the synthetic town onto the registry tables.

``fixtures/gis_town.json`` extends the two parcels and the addresses of the base
population with synthetic attributes and adds the rest of the town.  There is
one parcel table and one address table: the simulated ArcGIS services read the
very rows the registry holds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import gis, registry

TOWN_FILE = "gis_town.json"
SUBSCRIBERS_FILE = "property_subscribers.json"


def load_town(root: Path) -> dict[str, Any]:
    """Return the committed town document."""
    return json.loads((root / "fixtures" / TOWN_FILE).read_text(encoding="utf-8"))


def load_subscribers(root: Path) -> dict[str, Any]:
    """Return the committed subscriber departments."""
    return json.loads((root / "config" / SUBSCRIBERS_FILE).read_text(encoding="utf-8"))


def seed_gis(session: Session, root: Path, valid_from: Any) -> dict[str, int]:
    """Write the town and the subscriber departments; return what was written."""
    town = load_town(root)
    counts = {"gis_parcels_added": 0, "gis_addresses_added": 0}

    existing_parcels = {
        row.parcel_id: row for row in session.execute(select(registry.Parcel)).scalars().all()
    }
    for entry in town["parcels"]:
        row = existing_parcels.get(entry["parcel_id"])
        if row is None:
            row = registry.Parcel(
                id=entry["parcel_id"],
                parcel_id=entry["parcel_id"],
                jurisdiction_id="acme_city",
                source_parcel_number=entry["source_parcel_number"],
                status="active",
                valid_from=valid_from,
                valid_to=None,
                source_snapshot_id=None,
            )
            session.add(row)
            counts["gis_parcels_added"] += 1
        row.owner_name = entry["owner_name"]
        row.use_code = entry["use_code"]
        row.use_description = entry["use_description"]
        row.zoning_code = entry["zoning_code"]
        row.subdivision = entry["subdivision"]
        row.area_acres = entry["area_acres"]
        row.land_value_cents = entry["land_value_cents"]
        row.improvement_value_cents = entry["improvement_value_cents"]
        row.tax_district = entry["tax_district"]
        row.school_district = entry["school_district"]
        row.flood_zone = entry["flood_zone"]
        row.geometry = entry["geometry"]
        row.department_signals = entry["department_signals"]
    session.flush()

    existing_addresses = {
        row.address_id: row for row in session.execute(select(registry.Address)).scalars().all()
    }
    for entry in town["addresses"]:
        row = existing_addresses.get(entry["address_id"])
        if row is None:
            row = registry.Address(
                id=entry["address_id"],
                address_id=entry["address_id"],
                street_number=entry["street_number"],
                street_name=entry["street_name"],
                street_type=entry["street_type"],
                unit_type=entry["unit_type"],
                unit_number=entry["unit_number"],
                municipality=entry["municipality"],
                region=entry["region"],
                postcode=entry["postcode"],
                source_string=entry["source_string"],
                status=entry["status"],
                source_snapshot_id=None,
            )
            session.add(row)
            counts["gis_addresses_added"] += 1
        row.x = entry["x"]
        row.y = entry["y"]
    session.flush()

    existing_relations = {
        row.id for row in session.execute(select(registry.ParcelAddress)).scalars().all()
    }
    for entry in town["parcel_addresses"]:
        if entry["relationship_id"] in existing_relations:
            continue
        session.add(
            registry.ParcelAddress(
                id=entry["relationship_id"],
                parcel_id=entry["parcel_id"],
                address_id=entry["address_id"],
                relationship_type=entry["relationship_type"],
                effective_from=valid_from,
                effective_to=None,
                evidence_ref=f"gis:{entry['address_id']}",
            )
        )

    for entry in town["streets"]:
        session.add(
            gis.GisStreet(
                id=f"street_{entry['street_key']}",
                street_key=entry["street_key"],
                name=entry["name"],
                road_type=entry["road_type"],
                path=entry["path"],
            )
        )
    for entry in town["zoning_districts"]:
        session.add(
            gis.ZoningDistrict(
                id=f"zoning_{entry['code'].lower()}",
                code=entry["code"],
                name=entry["name"],
                description=entry["description"],
            )
        )

    subscribers = load_subscribers(root)
    for position, entry in enumerate(subscribers["subscribers"]):
        session.add(
            gis.DatasetSubscriber(
                id=f"subscriber_{entry['department_key']}",
                dataset_key=subscribers["dataset_key"],
                department_key=entry["department_key"],
                department_label=entry["department_label"],
                consumed_fields=list(entry["consumed_fields"]),
                contract_text=entry["contract_text"],
                signal_key=entry["signal_key"],
                signal_label=entry["signal_label"],
                position=position,
            )
        )
    session.flush()
    counts["gis_streets"] = len(town["streets"])
    counts["dataset_subscribers"] = len(subscribers["subscribers"])
    return counts


__all__ = ["load_subscribers", "load_town", "seed_gis"]

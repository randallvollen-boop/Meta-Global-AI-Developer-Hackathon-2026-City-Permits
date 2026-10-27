"""The ``GisLocator`` adapter: the application's own code calls the GIS over HTTP.

The default target is the in-app simulator.  Setting ``ACME_GIS_BASE_URL`` to
the ``ACME`` folder of a real ArcGIS REST server, and editing
``config/gis_field_map.json`` to that server's field names, swaps the real
system in without touching a caller.

The adapter speaks the ArcGIS REST shapes only:

* ``AddressLocator/GeocodeServer/findAddressCandidates`` (``SingleLine``,
  ``outFields``, ``maxLocations``, ``f=json``), ``suggest`` and ``reverseGeocode``;
* ``Parcels/FeatureServer/0/query`` (``where`` or ``geometry``);
* ``AddressPoints/FeatureServer/0/query``.
"""
# REQUIRES: GIS-02
# The adapter reaches the GIS over HTTP with ArcGIS REST requests and reads the
# responses through a configurable field map.

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from acme_city.gis.simulator import SERVICE_ROOT, build_simulator_app

REPO_ROOT = Path(__file__).resolve().parents[3]
FIELD_MAP_PATH = REPO_ROOT / "config" / "gis_field_map.json"

#: A fetcher turns a service path and its query into the decoded JSON body.
Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


class GisServiceError(RuntimeError):
    """The GIS answered with an error, or could not be reached."""


@dataclass(frozen=True)
class LocatorCandidate:
    """One address candidate, in the application's own field names."""

    address: str
    x: float
    y: float
    score: float
    status: str
    address_type: str = ""
    address_id: str = ""
    parcel_number: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "x": self.x,
            "y": self.y,
            "score": self.score,
            "status": self.status,
            "address_type": self.address_type,
            "address_id": self.address_id,
            "parcel_number": self.parcel_number,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ParcelRecord:
    """One parcel feature, in the application's own field names."""

    parcel_number: str
    site_address: str = ""
    owner: str = ""
    use_code: str = ""
    use_description: str = ""
    zoning: str = ""
    subdivision: str = ""
    area_acres: float | None = None
    land_value: float | None = None
    improvement_value: float | None = None
    assessed_value: float | None = None
    tax_district: str = ""
    school_district: str = ""
    flood_zone: str = ""
    rings: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class AddressPointRecord:
    """One official address point."""

    address_id: str
    full_address: str
    number: str = ""
    road_name: str = ""
    unit: str = ""
    parcel_number: str = ""
    x: float | None = None
    y: float | None = None


class GisLocator(Protocol):
    """What the application needs from an enterprise GIS."""

    @property
    def source_label(self) -> str: ...

    def find_candidates(self, text: str, max_locations: int = 5) -> list[LocatorCandidate]: ...

    def suggest(self, text: str, limit: int = 5) -> list[dict[str, Any]]: ...

    def candidate_for_key(self, magic_key: str) -> LocatorCandidate | None: ...

    def reverse_geocode(self, x: float, y: float) -> LocatorCandidate | None: ...

    def parcel_at(self, x: float, y: float) -> ParcelRecord | None: ...

    def parcel_by_number(self, parcel_number: str) -> ParcelRecord | None: ...

    def addresses_on_parcel(self, parcel_number: str) -> list[AddressPointRecord]: ...


def load_field_map(path: Path | None = None) -> dict[str, Any]:
    """Read the field map that translates a server's field names."""
    return json.loads((path or FIELD_MAP_PATH).read_text(encoding="utf-8"))


def _dig(source: Any, dotted: str) -> Any:
    current = source
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ArcGisRestLocator:
    """A ``GisLocator`` that speaks ArcGIS REST through a fetcher and a field map."""

    def __init__(
        self,
        fetch: Fetcher,
        *,
        field_map: dict[str, Any] | None = None,
        label: str = "ArcGIS REST",
    ) -> None:
        self._fetch = fetch
        self._map = field_map or load_field_map()
        self._label = label

    @property
    def source_label(self) -> str:
        return self._label

    # -------------------------------------------------------------------- calls

    def _call(self, service_key: str, operation: str, params: dict[str, str]) -> dict[str, Any]:
        path = f"{self._map['services'][service_key]}/{operation}".rstrip("/")
        body = self._fetch(path, {"f": "json", **params})
        if isinstance(body, dict) and "error" in body:
            error = body["error"] or {}
            raise GisServiceError(
                f"{error.get('message', 'the GIS reported an error')} "
                + "; ".join(str(item) for item in error.get("details") or [])
            )
        return body

    # ------------------------------------------------------------------ locator

    def _candidate(self, raw: dict[str, Any]) -> LocatorCandidate:
        mapping = self._map["locator_candidate"]
        return LocatorCandidate(
            address=str(_dig(raw, mapping["matched_address"]) or _dig(raw, mapping["address"]) or ""),
            x=float(_dig(raw, mapping["x"])),
            y=float(_dig(raw, mapping["y"])),
            score=float(_dig(raw, mapping["score"]) or 0),
            status=str(_dig(raw, mapping["status"]) or "U"),
            address_type=str(_dig(raw, mapping["address_type"]) or ""),
            address_id=str(_dig(raw, mapping["address_id"]) or ""),
            parcel_number=str(_dig(raw, mapping["parcel_id"]) or ""),
            notes=str(_dig(raw, "attributes.ScoreNotes") or ""),
        )

    def find_candidates(self, text: str, max_locations: int = 5) -> list[LocatorCandidate]:
        body = self._call(
            "locator",
            "findAddressCandidates",
            {"SingleLine": text, "outFields": "*", "maxLocations": str(max_locations)},
        )
        return [self._candidate(raw) for raw in body.get("candidates", [])]

    def suggest(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        body = self._call("locator", "suggest", {"text": text, "maxSuggestions": str(limit)})
        return list(body.get("suggestions", []))

    def candidate_for_key(self, magic_key: str) -> LocatorCandidate | None:
        body = self._call(
            "locator",
            "findAddressCandidates",
            {"magicKey": magic_key, "outFields": "*", "maxLocations": "1"},
        )
        rows = body.get("candidates", [])
        return self._candidate(rows[0]) if rows else None

    def reverse_geocode(self, x: float, y: float) -> LocatorCandidate | None:
        try:
            body = self._call("locator", "reverseGeocode", {"location": f"{x},{y}"})
        except GisServiceError:
            return None
        address = body.get("address") or {}
        location = body.get("location") or {}
        if not address:
            return None
        return LocatorCandidate(
            address=str(address.get("Match_addr", "")),
            x=float(location.get("x", x)),
            y=float(location.get("y", y)),
            score=100.0,
            status="M",
            address_id=str(address.get("ADDRESSID", "")),
            parcel_number=str(address.get("PARCELID", "") or ""),
        )

    # ------------------------------------------------------------------ parcels

    def _parcel(self, feature: dict[str, Any]) -> ParcelRecord:
        mapping = self._map["parcel"]
        attributes = feature.get("attributes", {})

        def text(key: str) -> str:
            value = attributes.get(mapping[key])
            return "" if value is None else str(value)

        def number(key: str) -> float | None:
            value = attributes.get(mapping[key])
            return None if value is None else float(value)

        return ParcelRecord(
            parcel_number=text("parcel_id"),
            site_address=text("site_address"),
            owner=text("owner"),
            use_code=text("use_code"),
            use_description=text("use_description"),
            zoning=text("zoning"),
            subdivision=text("subdivision"),
            area_acres=number("area_acres"),
            land_value=number("land_value"),
            improvement_value=number("improvement_value"),
            assessed_value=number("assessed_value"),
            tax_district=text("tax_district"),
            school_district=text("school_district"),
            flood_zone=text("flood_zone"),
            rings=list((feature.get("geometry") or {}).get("rings") or []),
        )

    def parcel_at(self, x: float, y: float) -> ParcelRecord | None:
        body = self._call(
            "parcels",
            "query",
            {
                "geometry": f"{x},{y}",
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "true",
            },
        )
        features = body.get("features", [])
        return self._parcel(features[0]) if features else None

    def parcel_by_number(self, parcel_number: str) -> ParcelRecord | None:
        key = self._map["parcel"]["parcel_id"]
        body = self._call(
            "parcels",
            "query",
            {
                "where": f"{key}={_quote(parcel_number.strip())}",
                "outFields": "*",
                "returnGeometry": "true",
            },
        )
        features = body.get("features", [])
        return self._parcel(features[0]) if features else None

    def addresses_on_parcel(self, parcel_number: str) -> list[AddressPointRecord]:
        mapping = self._map["address_point"]
        body = self._call(
            "address_points",
            "query",
            {
                "where": f"{mapping['parcel_id']}={_quote(parcel_number.strip())}",
                "outFields": "*",
                "returnGeometry": "true",
            },
        )
        records = []
        for feature in body.get("features", []):
            attributes = feature.get("attributes", {})
            geometry = feature.get("geometry") or {}
            records.append(
                AddressPointRecord(
                    address_id=str(attributes.get(mapping["address_id"]) or ""),
                    full_address=str(attributes.get(mapping["full_address"]) or ""),
                    number=str(attributes.get(mapping["number"]) or ""),
                    road_name=str(attributes.get(mapping["road_name"]) or ""),
                    unit=str(attributes.get(mapping["unit"]) or ""),
                    parcel_number=str(attributes.get(mapping["parcel_id"]) or ""),
                    x=geometry.get("x"),
                    y=geometry.get("y"),
                )
            )
        return records


# ------------------------------------------------------------------- fetchers


def http_fetcher(base_url: str, *, timeout: float = 10.0) -> Fetcher:
    """Return a fetcher that calls a real ArcGIS REST server over HTTP."""
    root = base_url.rstrip("/")

    def fetch(path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = httpx.get(f"{root}/{path}", params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise GisServiceError(f"the GIS could not be reached: {error}") from error

    return fetch


def loopback_fetcher(session_factory: Any) -> Fetcher:
    """Return a fetcher that calls the in-app simulator over in-process HTTP.

    The request goes through the ASGI stack of the simulator app (routing,
    query parsing, JSON encoding) exactly as a network request would; only the
    socket is skipped.
    """
    app = build_simulator_app(session_factory)

    def fetch(path: str, params: dict[str, str]) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://acme-gis-simulator"
            ) as client:
                response = await client.get(f"{SERVICE_ROOT}/{path}", params=params)
                response.raise_for_status()
                return response.json()

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(call())).result()
        except httpx.HTTPError as error:
            raise GisServiceError(f"the simulated GIS could not be reached: {error}") from error

    return fetch


def get_locator(settings: Any = None, session_factory: Any = None) -> GisLocator:
    """Return the configured ``GisLocator``.

    An empty ``ACME_GIS_BASE_URL`` means the in-app simulator.
    """
    base_url = str(getattr(settings, "gis_base_url", "") or "")
    if base_url:
        return ArcGisRestLocator(http_fetcher(base_url), label=f"ArcGIS REST at {base_url}")
    if session_factory is None:
        from acme_city.persistence.session import get_session_factory

        session_factory = get_session_factory(getattr(settings, "database_url", None))
    return ArcGisRestLocator(
        loopback_fetcher(session_factory), label="ACME GIS (simulated ArcGIS REST)"
    )


__all__ = [
    "AddressPointRecord",
    "ArcGisRestLocator",
    "Fetcher",
    "GisLocator",
    "GisServiceError",
    "LocatorCandidate",
    "ParcelRecord",
    "get_locator",
    "http_fetcher",
    "load_field_map",
    "loopback_fetcher",
]

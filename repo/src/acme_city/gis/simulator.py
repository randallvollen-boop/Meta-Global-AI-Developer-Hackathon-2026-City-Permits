"""The simulated enterprise GIS: ArcGIS REST shaped services served in-app.

Mounted under ``/sim/arcgis/rest/services/ACME``.  The services read the same
registry tables as the rest of the application, so there is one truth.  Every
response and every HTML page says it is simulated.  Nothing here calls an
outside network, and nothing here writes.

Services:

* ``AddressLocator/GeocodeServer``: ``findAddressCandidates``, ``suggest``,
  ``reverseGeocode``;
* ``Parcels/FeatureServer/0/query``;
* ``AddressPoints/FeatureServer/0/query``.
"""
# REQUIRES: GIS-01
# The simulated services speak the ArcGIS REST shapes and read the one parcel and
# address truth of the registry.

from __future__ import annotations

import html
import json
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from acme_city.auth.router import get_session
from acme_city.gis.catalog import (
    ADDRESS_FIELDS,
    PARCEL_FIELDS,
    SIMULATED_LABEL,
    SPATIAL_REFERENCE,
    PropertyCatalog,
    WhereError,
    matches,
    parse_where,
)

SERVICE_ROOT = "/sim/arcgis/rest/services/ACME"

router = APIRouter(prefix=SERVICE_ROOT, tags=["simulated-gis"])

_PARCEL_FIELD_NAMES = {name for name, _type, _alias in PARCEL_FIELDS}
_ADDRESS_FIELD_NAMES = {name for name, _type, _alias in ADDRESS_FIELDS}


def _error(code: int, message: str, details: list[str] | None = None) -> JSONResponse:
    """Return an ArcGIS style error body (ArcGIS answers 200 with an error object)."""
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "details": details or []},
        "simulated": True,
    }
    return JSONResponse(status_code=200, content=body)


def _respond(request: Request, title: str, body: dict[str, Any]) -> Any:
    """Return JSON, or a small labelled page when ``f=html`` is asked for."""
    body = {"simulated": True, "serviceDescription": SIMULATED_LABEL, **body}
    if request.query_params.get("f", "json").lower() == "html":
        pretty = html.escape(json.dumps(body, indent=2, default=str))
        return HTMLResponse(
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)} (simulated)</title></head><body>"
            f"<h1>{html.escape(title)}</h1>"
            f"<p><strong>Simulated.</strong> {html.escape(SIMULATED_LABEL)}</p>"
            f"<pre>{pretty}</pre></body></html>"
        )
    return JSONResponse(content=body)


def _point(raw: str | None) -> tuple[float, float] | None:
    """Parse ``x,y`` or ``{"x":..,"y":..}`` into a point."""
    if not raw:
        return None
    text = raw.strip()
    try:
        if text.startswith("{"):
            value = json.loads(text)
            return float(value["x"]), float(value["y"])
        left, right = text.split(",")[:2]
        return float(left), float(right)
    except (ValueError, KeyError, TypeError):
        return None


def _out_fields(raw: str | None, allowed: tuple[tuple[str, str, str], ...]) -> list[str]:
    names = [name for name, _type, _alias in allowed]
    if not raw or raw.strip() == "*":
        return names
    wanted = [part.strip().upper() for part in raw.split(",") if part.strip()]
    return [name for name in names if name in wanted]


# --------------------------------------------------------------------- catalog


@router.get("", name="gis_catalog")
def catalog_root(request: Request) -> Any:
    """List the services of the simulated ACME folder."""
    return _respond(
        request,
        "ACME services",
        {
            "currentVersion": "11.3",
            "folders": [],
            "services": [
                {"name": "ACME/AddressLocator", "type": "GeocodeServer"},
                {"name": "ACME/Parcels", "type": "FeatureServer"},
                {"name": "ACME/AddressPoints", "type": "FeatureServer"},
            ],
        },
    )


@router.get("/AddressLocator/GeocodeServer", name="gis_locator_info")
def locator_info(request: Request) -> Any:
    return _respond(
        request,
        "AddressLocator GeocodeServer",
        {
            "currentVersion": "11.3",
            "serviceDescription": SIMULATED_LABEL,
            "addressFields": [
                {"name": "SingleLine", "type": "esriFieldTypeString", "alias": "Single Line Input"}
            ],
            "singleLineAddressField": {"name": "SingleLine"},
            "capabilities": "Geocode,ReverseGeocode,Suggest",
            "spatialReference": SPATIAL_REFERENCE,
            "locatorProperties": {"MinimumCandidateScore": "60", "SuggestedBatchSize": "1"},
        },
    )


@router.get("/Parcels/FeatureServer", name="gis_parcels_info")
@router.get("/Parcels/FeatureServer/0", name="gis_parcels_layer")
def parcels_info(request: Request) -> Any:
    return _respond(
        request,
        "Parcels FeatureServer layer 0",
        {
            "currentVersion": "11.3",
            "name": "Parcels",
            "geometryType": "esriGeometryPolygon",
            "objectIdField": "OBJECTID",
            "spatialReference": SPATIAL_REFERENCE,
            "fields": [
                {"name": name, "type": kind, "alias": alias} for name, kind, alias in PARCEL_FIELDS
            ],
        },
    )


@router.get("/AddressPoints/FeatureServer", name="gis_address_points_info")
@router.get("/AddressPoints/FeatureServer/0", name="gis_address_points_layer")
def address_points_info(request: Request) -> Any:
    return _respond(
        request,
        "AddressPoints FeatureServer layer 0",
        {
            "currentVersion": "11.3",
            "name": "Address points",
            "geometryType": "esriGeometryPoint",
            "objectIdField": "OBJECTID",
            "spatialReference": SPATIAL_REFERENCE,
            "fields": [
                {"name": name, "type": kind, "alias": alias} for name, kind, alias in ADDRESS_FIELDS
            ],
        },
    )


# ---------------------------------------------------------------------- locator


@router.get("/AddressLocator/GeocodeServer/findAddressCandidates", name="gis_find_candidates")
def find_address_candidates(
    request: Request,
    session: Session = Depends(get_session),
) -> Any:
    """Return candidates for one line of address text, scored deterministically."""
    params = request.query_params
    text = (params.get("SingleLine") or params.get("singleLine") or "").strip()
    magic_key = params.get("magicKey")
    catalog = PropertyCatalog(session)
    try:
        maximum = max(1, min(int(params.get("maxLocations", "5")), 20))
    except ValueError:
        return _error(400, "Invalid maxLocations")
    if magic_key:
        chosen = catalog.candidate_for(magic_key)
        candidates = [chosen] if chosen else []
    elif not text:
        return _error(400, "Unable to complete operation.", ["SingleLine is required"])
    else:
        candidates = catalog.candidates(text, max_locations=maximum)
    wanted = params.get("outFields", "*")
    if wanted.strip() != "*":
        keep = {"Match_addr", "Addr_type", "Status", "Score"} | {
            part.strip() for part in wanted.split(",") if part.strip()
        }
        for candidate in candidates:
            candidate["attributes"] = {
                key: value for key, value in candidate["attributes"].items() if key in keep
            }
    return _respond(
        request,
        "findAddressCandidates",
        {"spatialReference": SPATIAL_REFERENCE, "candidates": candidates},
    )


@router.get("/AddressLocator/GeocodeServer/suggest", name="gis_suggest")
def suggest(request: Request, session: Session = Depends(get_session)) -> Any:
    """Return suggestions for a partly typed address."""
    text = (request.query_params.get("text") or "").strip()
    try:
        limit = max(1, min(int(request.query_params.get("maxSuggestions", "5")), 10))
    except ValueError:
        return _error(400, "Invalid maxSuggestions")
    suggestions = PropertyCatalog(session).suggestions(text, limit) if text else []
    return _respond(request, "suggest", {"suggestions": suggestions})


@router.get("/AddressLocator/GeocodeServer/reverseGeocode", name="gis_reverse")
def reverse_geocode(request: Request, session: Session = Depends(get_session)) -> Any:
    """Return the nearest official address to a point."""
    point = _point(request.query_params.get("location"))
    if point is None:
        return _error(400, "Unable to complete operation.", ["location must be x,y"])
    record = PropertyCatalog(session).nearest_address(*point)
    if record is None:
        return _error(400, "Unable to find address for the specified location.")
    address = record.address
    from acme_city.gis.catalog import full_address

    return _respond(
        request,
        "reverseGeocode",
        {
            "address": {
                "Match_addr": full_address(address),
                "LongLabel": full_address(address),
                "Address": address.source_string,
                "City": address.municipality,
                "Region": address.region,
                "Postal": address.postcode,
                "ADDRESSID": address.address_id,
                "PARCELID": record.parcel_number,
            },
            "location": {"x": address.x, "y": address.y},
        },
    )


# ---------------------------------------------------------------- feature layers


@router.get("/Parcels/FeatureServer/0/query", name="gis_parcels_query")
def query_parcels(request: Request, session: Session = Depends(get_session)) -> Any:
    """Query the parcel layer by ``where`` or by a point or envelope."""
    params = request.query_params
    catalog = PropertyCatalog(session)
    try:
        clauses = parse_where(params.get("where", ""), _PARCEL_FIELD_NAMES)
    except WhereError as error:
        return _error(400, "Unable to complete operation.", [f"Invalid query parameters: {error}"])
    fields = _out_fields(params.get("outFields"), PARCEL_FIELDS)
    with_geometry = params.get("returnGeometry", "true").lower() != "false"
    geometry_param = params.get("geometry")
    geometry_type = params.get("geometryType", "esriGeometryPoint")
    selected = catalog.parcels()
    if geometry_param:
        if geometry_type == "esriGeometryPoint":
            point = _point(geometry_param)
            if point is None:
                return _error(400, "Unable to complete operation.", ["geometry must be x,y"])
            hit = catalog.parcel_at(*point)
            selected = [hit] if hit else []
        elif geometry_type == "esriGeometryEnvelope":
            try:
                xmin, ymin, xmax, ymax = (float(part) for part in geometry_param.split(","))
            except ValueError:
                return _error(400, "Unable to complete operation.", ["envelope must be 4 numbers"])
            selected = [
                row
                for row in selected
                if _overlaps(row.geometry[0], xmin, ymin, xmax, ymax)
            ]
        else:
            return _error(400, "Unsupported geometryType")
    features = []
    for row in selected:
        attributes = catalog.parcel_attributes(row)
        if not matches(attributes, clauses):
            continue
        feature: dict[str, Any] = {
            "attributes": {name: attributes[name] for name in fields}
        }
        if with_geometry:
            feature["geometry"] = catalog.parcel_geometry(row)
        features.append(feature)
    try:
        limit = int(params.get("resultRecordCount", "1000"))
    except ValueError:
        limit = 1000
    exceeded = len(features) > limit
    features = features[:limit]
    if params.get("returnCountOnly", "false").lower() == "true":
        return _respond(request, "Parcels query", {"count": len(features)})
    return _respond(
        request,
        "Parcels query",
        {
            "objectIdFieldName": "OBJECTID",
            "geometryType": "esriGeometryPolygon",
            "spatialReference": SPATIAL_REFERENCE,
            "fields": [
                {"name": name, "type": kind, "alias": alias}
                for name, kind, alias in PARCEL_FIELDS
                if name in fields
            ],
            "features": features,
            "exceededTransferLimit": exceeded,
        },
    )


@router.get("/AddressPoints/FeatureServer/0/query", name="gis_address_points_query")
def query_address_points(request: Request, session: Session = Depends(get_session)) -> Any:
    """Query the address-point layer by ``where`` or by a point."""
    params = request.query_params
    catalog = PropertyCatalog(session)
    try:
        clauses = parse_where(params.get("where", ""), _ADDRESS_FIELD_NAMES)
    except WhereError as error:
        return _error(400, "Unable to complete operation.", [f"Invalid query parameters: {error}"])
    fields = _out_fields(params.get("outFields"), ADDRESS_FIELDS)
    with_geometry = params.get("returnGeometry", "true").lower() != "false"
    records = catalog.addresses()
    geometry_param = params.get("geometry")
    if geometry_param:
        point = _point(geometry_param)
        if point is None:
            return _error(400, "Unable to complete operation.", ["geometry must be x,y"])
        parcel = catalog.parcel_at(*point)
        records = [
            record for record in records if parcel is not None and record.parcel_row_id == parcel.id
        ]
    features = []
    for index, record in enumerate(catalog.addresses()):
        if record not in records:
            continue
        attributes = catalog.address_attributes(record, index)
        if not matches(attributes, clauses):
            continue
        feature: dict[str, Any] = {"attributes": {name: attributes[name] for name in fields}}
        if with_geometry:
            feature["geometry"] = {
                "x": record.address.x,
                "y": record.address.y,
                "spatialReference": SPATIAL_REFERENCE,
            }
        features.append(feature)
    return _respond(
        request,
        "AddressPoints query",
        {
            "objectIdFieldName": "OBJECTID",
            "geometryType": "esriGeometryPoint",
            "spatialReference": SPATIAL_REFERENCE,
            "fields": [
                {"name": name, "type": kind, "alias": alias}
                for name, kind, alias in ADDRESS_FIELDS
                if name in fields
            ],
            "features": features,
        },
    )


def _overlaps(ring: list[list[float]], xmin: float, ymin: float, xmax: float, ymax: float) -> bool:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs) <= xmax and max(xs) >= xmin and min(ys) <= ymax and max(ys) >= ymin


def build_simulator_app(session_factory: Any) -> FastAPI:
    """Return an app that serves only the simulated services.

    The adapter calls this app in process when ``ACME_GIS_BASE_URL`` is empty,
    so the application's own code still speaks HTTP to the services.
    """
    app = FastAPI(title="ACME simulated ArcGIS REST services", description=SIMULATED_LABEL)
    app.state.session_factory = session_factory
    app.include_router(router)
    return app


__all__ = ["SERVICE_ROOT", "build_simulator_app", "router"]

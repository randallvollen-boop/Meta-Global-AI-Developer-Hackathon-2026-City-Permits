"""The simulated ArcGIS REST services and the GisLocator adapter.

The services must speak the ArcGIS REST shapes, read the one parcel and address
truth of the registry, and be labelled simulated.  The adapter must reach them
over HTTP and read them through the field map, so a real server is a setting.
"""
# REQUIRES: GIS-01, GIS-02

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.gis import adapter
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

ROOT = "/sim/arcgis/rest/services/ACME"


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'gis.db'}",
            "ACME_SECRET_KEY": "gis-services-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment):
    with TestClient(create_app(environment)) as test_client:
        yield test_client


def candidates(client: TestClient, text: str, **extra: str) -> dict:
    response = client.get(
        f"{ROOT}/AddressLocator/GeocodeServer/findAddressCandidates",
        params={"SingleLine": text, "outFields": "*", "maxLocations": "5", "f": "json", **extra},
    )
    assert response.status_code == 200
    return response.json()


def test_find_address_candidates_has_the_arcgis_shape_and_is_labelled(client) -> None:
    body = candidates(client, "412 Maple Ridge Drive")
    assert body["simulated"] is True
    assert "spatialReference" in body
    top = body["candidates"][0]
    assert set(top) >= {"address", "location", "score", "attributes"}
    assert set(top["location"]) == {"x", "y"}
    assert top["attributes"]["Status"] == "M"
    assert top["attributes"]["Addr_type"] == "PointAddress"
    assert top["attributes"]["Match_addr"].startswith("412 Maple Ridge Drive")
    assert top["score"] == 100


def test_typo_and_abbreviations_correct_to_the_official_address(client) -> None:
    body = candidates(client, "412 Mapel Rdg Dr")
    top = body["candidates"][0]
    assert top["attributes"]["Match_addr"].startswith("412 Maple Ridge Drive")
    assert top["score"] >= 90
    assert len([row for row in body["candidates"] if row["score"] >= 90]) == 1
    # Unit designators, a typo and a missing ZIP normalise the same way.
    assert candidates(client, "400 Lanturn Row, ACME City")["candidates"][0]["score"] >= 90
    suite = candidates(client, "400 Lantern Row Ste 2")["candidates"][0]
    assert suite["attributes"]["Match_addr"].startswith("400 Lantern Row Unit 2")
    assert suite["attributes"]["Addr_type"] == "SubAddress"
    assert suite["score"] == 100


def test_a_tied_score_is_reported_as_tied_and_nothing_is_invented(client) -> None:
    body = candidates(client, "88 Kestrel")
    tied = [row for row in body["candidates"] if row["attributes"]["Status"] == "T"]
    assert len(tied) == 2
    assert tied[0]["score"] == tied[1]["score"] >= 90
    unknown = candidates(client, "1234 Kestrel Pass, ACME City")
    assert unknown["candidates"] == []


def test_scoring_is_deterministic(client) -> None:
    first = candidates(client, "Sunset Blvd 5")
    second = candidates(client, "Sunset Blvd 5")
    assert first == second
    assert candidates(client, "412 Mapel Rdg Dr") == candidates(client, "412 Mapel Rdg Dr")


def test_suggest_and_magic_key(client) -> None:
    response = client.get(
        f"{ROOT}/AddressLocator/GeocodeServer/suggest", params={"text": "412 Map", "f": "json"}
    )
    body = response.json()
    assert body["suggestions"], body
    first = body["suggestions"][0]
    assert set(first) == {"text", "magicKey", "isCollection"}
    assert first["isCollection"] is False
    chosen = candidates(client, "", magicKey=first["magicKey"])
    assert chosen["candidates"][0]["score"] == 100


def test_reverse_geocode_returns_the_nearest_address(client) -> None:
    point = candidates(client, "412 Maple Ridge Drive")["candidates"][0]["location"]
    response = client.get(
        f"{ROOT}/AddressLocator/GeocodeServer/reverseGeocode",
        params={"location": f"{point['x'] + 2},{point['y'] - 2}", "f": "json"},
    )
    body = response.json()
    assert body["address"]["Match_addr"].startswith("412 Maple Ridge Drive")
    far = client.get(
        f"{ROOT}/AddressLocator/GeocodeServer/reverseGeocode",
        params={"location": "5000,5000"},
    ).json()
    assert far["error"]["code"] == 400


def test_parcel_query_by_id_and_by_point_use_lgim_fields(client) -> None:
    by_id = client.get(
        f"{ROOT}/Parcels/FeatureServer/0/query",
        params={"where": "PARCELID='ACME-P-1004'", "outFields": "*", "returnGeometry": "true", "f": "json"},
    ).json()
    (feature,) = by_id["features"]
    attributes = feature["attributes"]
    assert set(attributes) >= {
        "PARCELID", "SITEADDRESS", "OWNERNME1", "USECD", "USEDSCRP", "ZONING", "CNVYNAME",
        "STATEAREA", "LNDVALUE", "IMPVALUE", "CNTASSDVAL", "TAXDIST", "SCHLDSCRP", "FLOODZONE",
    }
    assert attributes["SITEADDRESS"] == "412 Maple Ridge Drive"
    assert attributes["CNTASSDVAL"] == attributes["LNDVALUE"] + attributes["IMPVALUE"]
    assert feature["geometry"]["rings"]
    point = candidates(client, "412 Maple Ridge Drive")["candidates"][0]["location"]
    by_point = client.get(
        f"{ROOT}/Parcels/FeatureServer/0/query",
        params={
            "geometry": f"{point['x']},{point['y']}",
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "PARCELID",
            "returnGeometry": "false",
            "f": "json",
        },
    ).json()
    assert [row["attributes"] for row in by_point["features"]] == [{"PARCELID": "ACME-P-1004"}]
    assert "geometry" not in by_point["features"][0]


def test_every_official_address_point_falls_inside_its_parcel(client) -> None:
    points = client.get(
        f"{ROOT}/AddressPoints/FeatureServer/0/query",
        params={"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "json"},
    ).json()["features"]
    assert len(points) > 60
    for feature in points:
        attributes = feature["attributes"]
        assert set(attributes) >= {"ADDRESSID", "FULLADDR", "ADDNUM", "ROADNAME", "UNITID", "PARCELID"}
        hit = client.get(
            f"{ROOT}/Parcels/FeatureServer/0/query",
            params={
                "geometry": f"{feature['geometry']['x']},{feature['geometry']['y']}",
                "geometryType": "esriGeometryPoint",
                "outFields": "PARCELID",
                "returnGeometry": "false",
            },
        ).json()["features"]
        assert hit[0]["attributes"]["PARCELID"] == attributes["PARCELID"], attributes


def test_a_bad_where_clause_is_an_arcgis_error_not_a_crash(client) -> None:
    body = client.get(
        f"{ROOT}/Parcels/FeatureServer/0/query", params={"where": "DROP TABLE x", "f": "json"}
    ).json()
    assert body["error"]["code"] == 400
    html = client.get(f"{ROOT}/Parcels/FeatureServer/0", params={"f": "html"})
    assert "Simulated" in html.text


def test_the_adapter_speaks_rest_over_http_and_reads_the_field_map(environment) -> None:
    locator = adapter.get_locator(environment)
    found = locator.find_candidates("412 Mapel Rdg Dr")
    assert found[0].address.startswith("412 Maple Ridge Drive")
    assert found[0].score >= 90 and found[0].status == "M"
    parcel = locator.parcel_at(found[0].x, found[0].y)
    assert parcel is not None and parcel.parcel_number == "ACME-P-1004"
    assert parcel.zoning and parcel.rings
    assert locator.parcel_by_number("ACME-P-1004").site_address == "412 Maple Ridge Drive"
    assert locator.parcel_by_number("ACME-P-0000") is None
    assert {row.parcel_number for row in locator.addresses_on_parcel("ACME-P-1001")} == {"ACME-P-1001"}
    assert len(locator.addresses_on_parcel("ACME-P-1001")) == 3


def test_the_adapter_records_the_exact_arcgis_requests(monkeypatch) -> None:
    """Against a stand-in server, the requests are plain ArcGIS REST GETs."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("findAddressCandidates"):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "address": "1 Test St",
                            "location": {"x": 1.5, "y": 2.5},
                            "score": 97.5,
                            "attributes": {"Match_addr": "1 Test St", "Status": "M", "Addr_type": "PointAddress"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"features": []})

    real_get = httpx.get

    def fake_get(url, params=None, timeout=None, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.get(url, params=params)

    monkeypatch.setattr(httpx, "get", fake_get)
    settings = Settings.load(
        environ={
            "ACME_SECRET_KEY": "gis-services-secret-value",
            "ACME_GIS_BASE_URL": "https://gis.example.invalid/arcgis/rest/services/ACME/",
        },
        key_file=Path("/nonexistent-key-file"),
    )
    assert settings.gis_base_url == "https://gis.example.invalid/arcgis/rest/services/ACME"
    locator = adapter.get_locator(settings)
    (candidate,) = locator.find_candidates("1 Test Street", max_locations=3)
    assert (candidate.x, candidate.y, candidate.score) == (1.5, 2.5, 97.5)
    assert locator.parcel_by_number("ACME-P-1") is None
    first, second = seen
    assert first.url.path == "/arcgis/rest/services/ACME/AddressLocator/GeocodeServer/findAddressCandidates"
    assert dict(first.url.params) == {
        "f": "json", "SingleLine": "1 Test Street", "outFields": "*", "maxLocations": "3",
    }
    assert second.url.path.endswith("/Parcels/FeatureServer/0/query")
    assert dict(second.url.params)["where"] == "PARCELID='ACME-P-1'"
    assert real_get is not fake_get


def test_a_different_server_needs_only_a_field_map() -> None:
    mapping = json.loads(adapter.FIELD_MAP_PATH.read_text(encoding="utf-8"))
    mapping["parcel"]["parcel_id"] = "APN"
    mapping["parcel"]["owner"] = "OWNER_NAME"

    def fetch(path: str, params: dict) -> dict:
        return {
            "features": [
                {"attributes": {"APN": "99-001", "OWNER_NAME": "Example Owner", "ZONING": "R-1"}}
            ]
        }

    locator = adapter.ArcGisRestLocator(fetch, field_map=mapping)
    parcel = locator.parcel_by_number("99-001")
    assert parcel is not None and parcel.parcel_number == "99-001" and parcel.owner == "Example Owner"


def test_a_gis_error_object_raises(client) -> None:
    def fetch(path: str, params: dict) -> dict:
        return {"error": {"code": 400, "message": "Unable to complete operation.", "details": ["x"]}}

    with pytest.raises(adapter.GisServiceError):
        adapter.ArcGisRestLocator(fetch).find_candidates("anything")


def test_the_normaliser_handles_abbreviations_directionals_and_zips() -> None:
    from acme_city.gis.scoring import parse_address, parse_components, score_candidate

    parsed = parse_address("17 N. Oak St Apt #4B, ACME City, AC ACM-01401")
    assert parsed.number == "17"
    assert parsed.core == ("north", "oak")
    assert parsed.street_type == "street"
    assert parsed.unit == "4b"
    assert parsed.postcode == "01401"
    assert parsed.municipality_given and parsed.municipality_ok
    official = parse_components(
        number="17", street_name="North Oak Street", unit="4B", postcode="ACM-01401"
    )
    assert score_candidate(parsed, official)[0] == 100
    # A wrong ZIP costs points; a missing ZIP costs none.
    assert score_candidate(parse_address("17 N Oak St Apt 4B 01499"), official)[0] == 90
    assert score_candidate(parse_address("17 N Oak St Apt 4B"), official)[0] == 100

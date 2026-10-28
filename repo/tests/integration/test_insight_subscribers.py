"""Sanitation and Police: two more simulated subscribers of the property master."""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from insight_support import ADMIN, build_environment, open_factory
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.persistence.models import gis, permit, registry
from acme_city.persistence.session import transaction
from acme_city.ui.router import router as ui_router

CONFIG = Path(__file__).resolve().parents[2] / "config" / "property_subscribers.json"


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("subs"), synthetic=True, name="subs.db")


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": ADMIN}).status_code == 200
        yield test_client


def subscriber_entries() -> dict[str, dict]:
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    return {entry["department_key"]: entry for entry in document["subscribers"]}


def test_the_config_holds_six_subscribers_in_one_shape() -> None:
    entries = subscriber_entries()
    assert list(entries) == [
        "tax_assessor", "fire_safety", "code_enforcement", "utilities", "sanitation", "police",
    ]
    shape = set(entries["utilities"])
    for key in ("sanitation", "police"):
        assert set(entries[key]) == shape
        assert entries[key]["contract_text"].endswith("Writes nothing back.")
        assert "(synthetic)" in entries[key]["signal_label"]
    assert {"ADDRESSID", "UNITID", "USECD"} <= set(entries["sanitation"]["consumed_fields"])
    assert "collection" in entries["sanitation"]["contract_text"]
    assert "BUSLICCAT" in entries["police"]["consumed_fields"]
    assert "bars" in entries["police"]["contract_text"]


def test_the_reset_seeds_the_two_new_subscribers(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            rows = session.execute(
                select(gis.DatasetSubscriber).order_by(gis.DatasetSubscriber.position)
            ).scalars().all()
            assert [row.department_key for row in rows][-2:] == ["sanitation", "police"]
            assert len(rows) == 6
    finally:
        factory.dispose()


def test_the_property_record_shows_both_under_simulated_departments(client) -> None:
    body = client.get("/property/ACME-P-1001").text
    assert 'data-testid="simulated-departments-heading"' in body
    assert ">Simulated departments<" in body
    for key, label in (("sanitation", "Sanitation"), ("police", "Police")):
        row = re.search(rf'<tr data-department="{key}">(.*?)</tr>', body, re.S)
        assert row, key
        assert label in row.group(1)
    assert "Next collection day (synthetic)" in body
    assert "Licensed late-night premises (synthetic)" in body


def test_governance_and_sources_lists_them_under_the_same_heading(client) -> None:
    body = client.get("/governance").text
    assert ">Simulated departments<" in body
    for label in ("Sanitation", "Police"):
        assert re.search(rf"<th scope=\"row\">{label}</th>", body)
    assert "Reads the address, parcel use and business licence category" in body


def test_the_sanitation_signal_follows_the_parcel(client) -> None:
    commercial = client.get("/property/ACME-P-1001").text
    assert "Monday, Wednesday and Friday (commercial pickup)" in commercial
    residential = client.get("/property/ACME-P-1006").text
    assert re.search(r"Next collection day \(synthetic\): <strong>(Monday|Tuesday)</strong>", residential)


def test_the_police_signal_counts_licensed_bars_on_the_parcel(client, settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            bar_parcel = session.execute(
                select(registry.Parcel.source_parcel_number)
                .join(permit.ApplicationSite, permit.ApplicationSite.parcel_id == registry.Parcel.id)
                .join(
                    permit.ApplicationParty,
                    permit.ApplicationParty.application_id == permit.ApplicationSite.application_id,
                )
                .join(
                    registry.Credential,
                    registry.Credential.holder_party_id == permit.ApplicationParty.party_id,
                )
                .where(registry.Credential.business_category == "bar")
                .limit(1)
            ).scalar_one()
    finally:
        factory.dispose()
    with_bar = client.get(f"/property/{bar_parcel}").text
    match = re.search(r"Licensed late-night premises \(synthetic\): <strong>([^<]+)</strong>", with_bar)
    assert match and match.group(1).isdigit() and int(match.group(1)) >= 1
    without = client.get("/property/ACME-P-1006").text
    assert "Licensed late-night premises (synthetic): <strong>none on file</strong>" in without

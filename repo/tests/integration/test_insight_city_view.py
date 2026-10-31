"""The City view (/insight/city): filters, map, categories, trends, labels."""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from insight_support import ADMIN, SYNTHETIC_COUNT, build_environment, open_factory
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.insight.city_view import city_view, parse_filters
from acme_city.insight.queries import load_rows
from acme_city.persistence.models import permit
from acme_city.persistence.session import transaction
from acme_city.ui.router import router as ui_router

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("cityview"), synthetic=True, name="cv.db")


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def as_admin(client: TestClient) -> TestClient:
    assert client.post("/api/session/select", json={"actor_id": ADMIN}).status_code == 200
    return client


@pytest.fixture(scope="module")
def rows(settings):
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            return [
                row for row in load_rows(session)
                if row.status not in {"draft", "archived"} and row.submitted_at is not None
            ]
    finally:
        factory.dispose()


def view(settings, **filters):
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            return city_view(session, **filters)
    finally:
        factory.dispose()


def total_of(body: str) -> int:
    match = re.search(r'data-testid="insight-total"><strong>(\d+)</strong>', body)
    assert match, "the total is printed"
    return int(match.group(1))


def test_only_the_city_administrator_opens_the_city_view(client) -> None:
    anonymous = client.get("/insight/city", follow_redirects=False)
    assert anonymous.status_code == 303 and anonymous.headers["location"] == "/select"
    for actor in ("persona_applicant", "persona_data_steward", "persona_permit_reviewer"):
        client.post("/api/session/select", json={"actor_id": actor})
        assert client.get("/insight/city").status_code == 403, actor
    as_admin(client)
    assert client.get("/insight/city").status_code == 200


def test_the_city_view_is_read_only(client) -> None:
    as_admin(client)
    assert client.post("/insight/city").status_code in {403, 404, 405}
    assert client.put("/insight/city").status_code in {403, 404, 405}


def test_the_navigation_lists_the_city_view_for_the_administrator_only(client) -> None:
    for actor, listed in (
        (ADMIN, True), ("persona_applicant", False), ("persona_data_steward", False),
        ("persona_permit_reviewer", False),
    ):
        client.post("/api/session/select", json={"actor_id": actor})
        keys = re.findall(r'data-screen-key="([^"]+)"', client.get("/queue").text)
        assert ("insight_city" in keys) is listed, actor
        if listed:
            # Changed deliberately (policy 2, then P3c): the What-if entry follows
            # the City view and the four operations entries follow the What-if.
            assert keys[-6:] == [
                "insight_city", "policy_scenarios",
                "ops_dashboard", "ops_audit", "ops_support", "ops_checks",
            ]


def test_the_unfiltered_total_is_a_count_over_the_stored_applications(client, settings, rows) -> None:
    body = as_admin(client).get("/insight/city").text
    assert total_of(body) == len(rows)
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            stored = len(
                session.execute(
                    select(permit.Application.id).where(permit.Application.status.notin_(["draft", "archived"]))
                ).all()
            )
    finally:
        factory.dispose()
    assert stored == len(rows) < 13 + SYNTHETIC_COUNT  # archived cases are not activity
    assert "Permits: applications that have been submitted" in body  # the definition is printed
    assert "District: the zoning district" in body
    assert "Exceptions: a variance request" in body


@pytest.mark.parametrize("type_key", ["deck_fence", "shed", "sign", "zoning_variance"])
def test_the_type_filter_matches_an_independent_count(client, rows, type_key: str) -> None:
    body = as_admin(client).get(f"/insight/city?type={type_key}").text
    assert total_of(body) == sum(1 for r in rows if r.type_key == type_key)


@pytest.mark.parametrize("outcome", ["approved", "conditions", "denied", "undecided"])
def test_the_outcome_filter_matches_an_independent_count(client, rows, outcome: str) -> None:
    body = as_admin(client).get(f"/insight/city?outcome={outcome}").text
    assert total_of(body) == sum(1 for r in rows if r.outcome_key == outcome)


def test_the_restaurants_and_bars_view_filters_by_business_category(client, settings, rows) -> None:
    body = as_admin(client).get("/insight/city?category=restaurant,bar").text
    wanted = [r for r in rows if r.category in {"restaurant", "bar"}]
    assert total_of(body) == len(wanted) > 0
    # every row of the table is a restaurant or a bar
    table = body[body.index('data-testid="insight-rows"'):]
    categories = re.findall(r"<td>(Restaurant|Bar|Retail|Office|Other)</td><td>[^<]*</td>\s*</tr>", table)
    assert categories and set(categories) <= {"Restaurant", "Bar"}
    assert 'data-testid="dining-sites"' in body
    assert "Restaurant and bar permit locations" in body
    assert f"<strong>{len(wanted)}</strong> permits in this view are for restaurants and bars" in body
    # the quick link and the select option for the combined view exist
    assert 'data-testid="quick-restaurants-bars"' in body
    one = view(settings, category="bar")
    assert one["total"] == sum(1 for r in rows if r.category == "bar")
    assert view(settings, category="not-a-category")["total"] == len(rows)  # ignored


def test_the_exceptions_only_filter_keeps_variances_waivers_denials_and_conditions(client, rows) -> None:
    body = as_admin(client).get("/insight/city?exceptions=1").text
    wanted = [r for r in rows if r.exception_kinds]
    assert total_of(body) == len(wanted) > 0
    kinds = {k for r in wanted for k in r.exception_kinds}
    assert kinds == {"variance", "waiver", "denial", "conditions"}
    assert "No permit in this view carries an exception" not in body


def test_the_period_filter_counts_by_submission_date(settings, rows) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            now = datetime(2026, 10, 27, 17, tzinfo=UTC)
            whole = city_view(session, now=now)["total"]
            ninety = city_view(session, period="90d", now=now)["total"]
            thirty = city_view(session, period="30d", now=now)["total"]
            year = city_view(session, period="12m", now=now)["total"]
            nothing = city_view(session, period="30d", now=datetime(2030, 1, 1, tzinfo=UTC))["total"]
    finally:
        factory.dispose()
    assert whole >= year >= ninety >= thirty > 0
    assert nothing == 0
    assert ninety == sum(1 for r in rows if r.submitted_at >= now - timedelta(days=90))


def test_synthetic_data_is_labelled_and_can_be_excluded(client, rows) -> None:
    included = as_admin(client).get("/insight/city").text
    excluded = client.get("/insight/city?synthetic=exclude").text
    assert 'data-testid="synthetic-badge"' in included
    assert "synthetic data" in included
    assert 'data-testid="synthetic-toggle"' in included and "Exclude synthetic data" in included
    assert total_of(excluded) == sum(1 for r in rows if not r.synthetic) == 13
    assert 'data-testid="synthetic-badge"' not in excluded.split('data-testid="insight-rows"')[1]
    assert "Include synthetic data" in excluded


def test_without_synthetic_rows_the_view_says_so(tmp_path) -> None:
    settings = build_environment(tmp_path, synthetic=False, name="plain.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        body = as_admin(test_client).get("/insight/city").text
    assert "No synthetic data is loaded" in body
    assert total_of(body) == 13
    assert 'data-testid="synthetic-toggle"' not in body
    assert 'class="badge-synthetic"' not in body


def test_the_map_is_shaded_by_district_with_a_table_beside_it(client, settings) -> None:
    body = as_admin(client).get("/insight/city").text
    assert 'data-testid="insight-map"' in body
    for district in ("R-1", "R-2", "C-2"):
        assert f'<tr data-district="{district}">' in body
        assert f'data-district="{district}"' in body
    assert 'class="insight-parcel insight-shade-' in body
    data = view(settings)
    counts = {row["code"]: row["permits"] for row in data["map"]["district_table"]}
    assert sum(counts.values()) + data["map"]["unmapped"] == data["total"]
    assert data["map"]["unmapped"] > 0  # a fixture case with no matched parcel is counted, not hidden
    top = max(counts, key=counts.get)
    shade = {row["code"]: row["shade"] for row in data["map"]["district_table"]}
    assert shade[top] == 4
    assert all(0 <= value <= 4 for value in shade.values())
    # colour is not the only signal: the figure is printed on the map
    assert f'{counts[top]} permits' in body


def test_variance_clustering_is_visible_on_the_map(client, settings, rows) -> None:
    body = as_admin(client).get("/insight/city?type=zoning_variance&exceptions=1").text
    data = view(settings, type="zoning_variance", exceptions="1")
    table = {row["code"]: row for row in data["map"]["district_table"]}
    total = sum(row["variances"] for row in table.values())
    assert total == data["total"] == sum(1 for r in rows if r.type_key == "zoning_variance")
    assert table["R-2"]["variances"] / total > 0.6          # one district carries the pattern
    assert table["R-2"]["shade"] == 4
    dots = re.findall(r'<g class="insight-dot" data-parcel="([^"]+)" data-count="(\d+)">', body)
    assert dots
    assert sum(int(count) for _, count in dots) == total
    biggest = max(dots, key=lambda item: int(item[1]))
    assert int(biggest[1]) >= 5                           # a visible cluster on one parcel
    top = data["map"]["top_exception_parcels"][0]
    assert top["district"] == "R-2" and top["parcel"] == biggest[0]
    assert "Where exceptions cluster" in body
    assert "Orange dots mark parcels with exceptions" in body  # the map's own text alternative


def test_business_activity_by_category_is_a_table_with_totals(settings, rows) -> None:
    data = view(settings)
    by_key = {row["key"]: row for row in data["categories"]["rows"]}
    assert set(by_key) == {"restaurant", "bar", "retail", "office", "other"}
    for key, row in by_key.items():
        assert row["permits"] == sum(1 for r in rows if r.category == key)
    assert data["categories"]["linked_to_business"] == sum(1 for r in rows if r.category)
    sites = data["categories"]["where_opening"]
    assert sites and all(site["district"] == "C-2" for site in sites if site["district"])


def test_the_monthly_trend_covers_the_year_and_adds_up(client, settings) -> None:
    body = as_admin(client).get("/insight/city").text
    data = view(settings)
    months = [item["month"] for item in data["trend"]["rows"]]
    assert months == sorted(months) and len(months) >= 12
    assert sum(item["permits"] for item in data["trend"]["rows"]) == data["total"]
    assert 'data-testid="insight-trend-chart"' in body and 'data-testid="trend-table"' in body


def test_a_filtered_view_reports_the_total_before_filters(settings) -> None:
    data = view(settings, type="shed")
    assert data["total"] < data["total_before_filters"]
    assert data["what_if"] is None  # the what-if starter does not exist until P3policy


def test_filters_are_cleaned(settings) -> None:
    cleaned = parse_filters(period="forever", outcome="x", category="bar,zzz", exceptions="yes", synthetic="no")
    assert cleaned == {
        "type": "", "outcome": "", "period": "all", "category": ["bar"],
        "exceptions": True, "synthetic": "include",
    }


def test_every_staff_row_links_to_its_public_record(client, rows) -> None:
    body = as_admin(client).get("/insight/city").text
    link = re.search(r'<a href="(/city/community/permit/[^"]+)"', body)
    assert link
    assert client.get(link.group(1)).status_code == 200


def test_a_synthetic_case_opens_with_a_badge_and_a_synthetic_history(client, settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            application_id = session.execute(
                select(permit.Application.id).where(permit.Application.synthetic.is_(True)).limit(1)
            ).scalar_one()
    finally:
        factory.dispose()
    client.post("/api/session/select", json={"actor_id": "persona_permit_reviewer"})
    body = client.get(f"/permits/{application_id}").text
    assert 'data-testid="synthetic-badge"' not in body
    assert 'data-testid="synthetic-history-panel"' in body
    assert "Synthetic history" in body
    assert 'data-testid="history-panel"' not in body  # nobody acted, so there is no audit history


def test_the_screen_wording_is_neutral() -> None:
    needle = "unwinding"
    for root in (SRC, SRC.parent / "config"):
        for path in root.rglob("*"):
            if path.suffix in {".py", ".html", ".json", ".css", ".js"} and path.is_file():
                assert needle not in path.read_text(encoding="utf-8").lower(), path

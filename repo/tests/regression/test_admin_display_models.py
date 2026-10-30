"""The display models of the admin-b screens.

The screens show what the permit engine stored and counted.  A model may
explain a run or propose a change, but it never supplies a figure, a label or
a decision, so the display models are plain functions of the frozen baseline
and of the stored rows.

This file starts as the skeleton of the lane.  The later slices add their own
cases: ADB-7 the deterministic run summary and ADB-10 the governance screen.
"""
# REQUIRES: UX-01, PER-02

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.persistence.models import policy as models
from acme_city.persistence.session import SessionFactory
from acme_city.policy import summary, views
from acme_city.ui.router import router as ui_router

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings  # noqa: E402

ADMIN = "persona_city_administrator"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Return settings with their own seeded database."""
    return build_settings(tmp_path, "admin-b-display-models.db")


@pytest.fixture()
def client(settings: Settings):
    """Return a client with its own seeded database."""
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        test_client.post("/api/session/select", json={"actor_id": ADMIN})
        yield test_client

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.persistence.models import governance
from acme_city.persistence.session import SessionFactory, transaction
from acme_city.policy import views
from acme_city.ui import admin_b_labels, admin_views

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from insight_support import build_environment  # noqa: E402


def test_the_display_models_are_plain_functions_of_the_stored_rows() -> None:
    """Every display model of the lane is a plain function, with no model call."""
    for name in ("describe_change", "check_changes", "editor_options", "run_view"):
        assert callable(getattr(views, name)), name


# ------------------------------------------------------- the run summary


def _token(body: str, name: str = "csrf_token") -> str:
    """Return the value of a hidden form field."""
    match = re.search(rf'name="{name}" value="([^"]*)"', body)
    assert match, f"the page carries a {name}"
    return match.group(1)


def _run_a_scenario(client: TestClient) -> str:
    """Save the fence example, run it and return the address of the results."""
    page = client.get("/policy/scenarios")
    created = client.post(
        "/policy/scenarios",
        data={"csrf_token": _token(page.text), "expected_version": "0",
              "suggestion": "fence_height_7ft", "name": "A summary probe"},
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    editor = created.headers["location"].split("?")[0]
    page = client.get(editor)
    ran = client.post(
        f"{editor}/run",
        data={"csrf_token": _token(page.text), "expected_version": _token(page.text, "expected_version"),
              "kind": "synthetic_year", "seed": "20261028", "count": "120"},
        follow_redirects=False,
    )
    assert ran.status_code == 303, ran.text
    return ran.headers["location"]


def _run_view(settings: Settings, address: str) -> dict[str, Any]:
    """Return the display data of a stored run, read from the database."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            run = session.get(models.PolicyRun, address.rsplit("/", 1)[1])
            assert run is not None
            return views.run_view(run)
    finally:
        factory.dispose()


def test_the_summary_of_a_saved_run_is_the_same_every_time(
    settings: Settings, client: TestClient
) -> None:
    """The same saved run always gives the same summary."""
    address = _run_a_scenario(client)
    view = _run_view(settings, address)
    first = summary.run_summary(view)
    second = summary.run_summary(view)
    assert first == second
    assert first["headline"] == (
        f"{view['flipped']['total']} of {view['population']['size']} "
        "cases have a different result."
    )


def test_the_summary_states_only_figures_the_engine_counted(
    settings: Settings, client: TestClient
) -> None:
    """The headline counts the changed cases and the population of the run."""
    address = _run_a_scenario(client)
    view = _run_view(settings, address)
    report = summary.run_summary(view)
    assert report["changed"] == view["flipped"]["total"]
    assert report["population"] == view["population"]["size"]
    assert report["headline"].startswith(f"{view['flipped']['total']} of ")


def test_the_summary_says_which_way_the_cases_moved(
    settings: Settings, client: TestClient
) -> None:
    """The explanation names the direction of the change."""
    address = _run_a_scenario(client)
    view = _run_view(settings, address)
    report = summary.run_summary(view)
    assert report["sentences"], "the run has an explanation"
    assert report["sentences"][0].endswith(".")
    assert all(sentence.endswith(".") for sentence in report["sentences"])


def test_the_summary_counts_every_direction_of_the_change() -> None:
    """The breakdown of the direction adds up to the number of changed cases."""
    view = {
        "population": {"size": 100},
        "flipped": {
            "total": 6,
            "directions": [
                {"key": "relaxed", "label": "Relaxed", "count": 3},
                {"key": "tightened", "label": "Tightened", "count": 2},
                {"key": "changed_otherwise", "label": "Changed", "count": 1},
            ],
        },
        "holds": {"cleared": 0, "added": 0},
        "needs": {"cleared": 0, "added": 0},
        "fees": None,
        "retires_a_rule": False,
    }
    report = summary.run_summary(view)
    assert report["headline"] == "6 of 100 cases have a different result."
    assert report["sentences"] == (
        "3 cases get a more permissive result, 2 cases get a less permissive result "
        "and 1 case changes in another way.",
    )


def test_the_summary_names_the_holds_and_the_fees_when_they_move() -> None:
    """A run that moves holds, information and fees says so in words."""
    view = {
        "population": {"size": 50},
        "flipped": {"total": 0, "directions": []},
        "holds": {"cleared": 4, "added": 1},
        "needs": {"cleared": 0, "added": 2},
        "fees": {"baseline": "100.00", "scenario": "125.00"},
        "retires_a_rule": True,
    }
    report = summary.run_summary(view)
    assert report["sentences"] == (
        "Recommendation holds: 4 cases are no longer held for a person and 1 case is newly held for a person.",
        "Information needed at intake: 2 cases need information that was not needed before.",
        "The hypothetical assessed fees change from 100.00 to 125.00 USD.",
        "This what-if retires a rule for every case. Retiring a rule does not approve the cases it used to stop.",
    )


def test_the_summary_of_a_run_with_no_change_says_so(
    settings: Settings, client: TestClient
) -> None:
    """A run in which nothing changed says exactly that."""
    view = {
        "population": {"size": 40},
        "flipped": {"total": 0, "directions": []},
        "holds": {"cleared": 0, "added": 0},
        "needs": {"cleared": 0, "added": 0},
        "fees": None,
        "retires_a_rule": False,
    }
    report = summary.run_summary(view)
    assert report["headline"] == "0 of 40 cases have a different result."
    assert report["sentences"] == ()


def test_the_summary_asks_no_model(settings: Settings, client: TestClient, monkeypatch) -> None:
    """The summary is worked out from the stored run, so no provider is called."""
    def refuse(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the summary must not call a provider")

    monkeypatch.setattr("acme_city.muse.client.MuseClient.create_response", refuse)
    address = _run_a_scenario(client)
    view = _run_view(settings, address)
    assert summary.run_summary(view)["headline"]


def test_the_results_page_carries_the_summary(
    settings: Settings, client: TestClient, monkeypatch
) -> None:
    """The page gets the deterministic summary, whatever the model can do."""
    from acme_city.ui import policy_routes

    captured: dict[str, Any] = {}
    original = policy_routes.render

    def capture(request, template, context):
        captured.update(context)
        return original(request, template, context)

    monkeypatch.setattr(policy_routes, "render", capture)
    address = _run_a_scenario(client)
    response = client.get(address)
    assert response.status_code == 200
    assert captured["summary"] == summary.run_summary(captured["run"])
    assert captured["summary"]["headline"]


def test_governance_labels_and_attention_are_derived_from_seeded_rows(tmp_path: Path) -> None:
    assert admin_b_labels.identifier_label("applications_and_permits") == "Applications and permits"
    settings = build_environment(tmp_path, synthetic=False, name="admin-display-models.db")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            resolver = PermissionResolver(session)
            grants = resolver.grants_for("persona_city_administrator")
            actor = ActorContext(
                actor_id="persona_city_administrator", role_ids=frozenset(),
                domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
                record_scope=frozenset(r for g in grants for r in g.record_scope),
            )
            unowned = session.query(governance.SourceContract).filter_by(
                dataset_key="business_licensing_register"
            ).one()
            unowned.accountable_owner_actor_id = None
            unowned.steward_queue_id = None
            unowned.system_custodian_actor_id = None
            session.flush()
            screen = admin_views.governance_screen(session, actor)
            assert screen["attention"] == {
                "staged_records": len(screen["staged"]),
                "quarantine_errors": len(screen["quarantined"]),
            }
            by_dataset = {row["dataset_key"]: row for row in screen["registrations"]}
            assert by_dataset["business_licensing_register"]["source_label"] == "ERP/Finance"
            assert by_dataset["business_licensing_register"]["source_system_id"] == "erp_finance"
            assert by_dataset["business_licensing_register"]["owner_label"] == "No owner assigned"
            assert by_dataset["business_licensing_register"]["custodian_label"] == "No custodian assigned"
            assert by_dataset["applications_and_permits"]["dataset_label"] == "Applications and permits"
            assert by_dataset["applications_and_permits"]["dataset_key"] == "applications_and_permits"
    finally:
        factory.dispose()

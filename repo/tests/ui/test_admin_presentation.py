"""The presentation primitives of the administration area.

The shared macros and the operations helpers decide how a screen reads, never
what it says: they add a label, a group or a disclosure around the values the
view model already holds.  These checks prove that the primitives render the
markup the screens expect, that the plain labels replace the technical ones
and that the scope of the figures is always named.
"""
# REQUIRES: UX-01

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import admin_config_views, ops_views

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "acme_city" / "templates"


def _environment() -> Environment:
    """Return an environment that loads the templates of the application."""
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)


def _render(source: str) -> str:
    """Render one source that uses the shared macros."""
    template = _environment().from_string(
        "{% import 'components/admin_patterns.html' as adm %}" + source
    )
    return template.render()


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'admin-presentation.db'}",
            "ACME_SECRET_KEY": "admin-presentation-secret-value",
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
    return settings, bundle


@pytest.fixture()
def session(environment: tuple[Settings, FixtureBundle]) -> Session:
    settings, _ = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


def _actor_for(session: Session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


# ------------------------------------------------------------- the macros


def test_the_scope_note_names_the_scope_of_a_figure() -> None:
    html = _render("{{ adm.scope_note('Sample history excluded.', 'adm-note') }}")
    assert 'class="adm-scope-note"' in html
    assert 'data-testid="adm-note"' in html
    assert "Sample history excluded." in html


def test_the_status_summary_shows_every_state_with_its_tone() -> None:
    html = _render(
        "{{ adm.status_summary([{'label': 'Approved', 'value': 3, 'tone': 'ok'}], 'adm-states') }}"
    )
    assert 'class="adm-status-summary"' in html
    assert 'class="adm-status adm-status--ok"' in html
    assert "Approved" in html and "3" in html


def test_a_state_without_a_tone_keeps_the_plain_class() -> None:
    html = _render(
        "{{ adm.status_summary([{'label': 'Decisions recorded', 'value': 12}]) }}"
    )
    assert 'class="adm-status"' in html
    assert "adm-status--" not in html


def test_the_disclosure_holds_a_summary_and_its_body() -> None:
    html = _render(
        "{{ adm.disclosure('Required documents', '<p>Site plan</p>', 'adm-settings', true) }}"
    )
    assert 'class="adm-disclosure"' in html
    assert 'data-testid="adm-settings"' in html
    assert "open" in html
    assert "Required documents" in html
    assert "Site plan" in html


def test_the_field_label_names_the_value_of_a_stacked_cell() -> None:
    html = _render("<td>{{ adm.field_label('Review area') }}Building</td>")
    assert 'class="adm-field-label"' in html
    assert "Review area" in html
    assert "Building" in html


def test_the_macros_are_scoped_to_the_admin_area() -> None:
    html = _render(
        "{{ adm.scope_note('Scope', 'adm-note') }}"
        "{{ adm.status_summary([{'label': 'Approved', 'value': 3, 'tone': 'ok'}]) }}"
        "{{ adm.disclosure('Settings', 'Body') }}"
        "{{ adm.field_label('Review area') }}"
    )
    groups = set(re.findall(r'class="([^"]+)"', html))
    assert groups
    for group in groups:
        for name in group.split():
            assert name.startswith("adm-"), name


# ---------------------------------------------------- the operations words


def test_every_dashboard_figure_has_a_plain_label() -> None:
    assert set(ops_views.FIGURE_LABELS) == {
        "active",
        "average_age",
        "needs_a_person",
        "early_incomplete",
        "agent_processed",
        "decisions",
    }
    for key, label in ops_views.FIGURE_LABELS.items():
        assert ops_views.label_for(key) == label
        assert label == label[0].upper() + label[1:]
        assert " - " not in label and "—" not in label


def test_the_figures_sit_in_the_two_groups() -> None:
    assert ops_views.FIGURE_GROUPS == (
        ("workload", "Current workload"),
        ("processing", "Recorded processing"),
    )
    for key in ops_views.FIGURE_LABELS:
        assert ops_views.group_of(key) in {"workload", "processing"}
    assert ops_views.group_of("active") == "workload"
    assert ops_views.group_of("decisions") == "processing"


def test_the_grouping_keeps_every_figure_and_its_own_value() -> None:
    figures = [
        {"key": "active", "label": "Active cases", "value": 4, "display": "4"},
        {"key": "decisions", "label": "Decisions recorded", "value": 9, "display": "9"},
    ]
    groups = ops_views.figure_groups(figures)
    assert [group["key"] for group in groups] == ["workload", "processing"]
    workload, processing = groups
    assert [figure["key"] for figure in workload["figures"]] == ["active"]
    assert workload["figures"][0]["value"] == 4
    assert workload["figures"][0]["label"] == "Active cases"
    assert [figure["key"] for figure in processing["figures"]] == ["decisions"]
    assert processing["figures"][0]["display"] == "9"


def test_an_unknown_figure_is_kept_in_the_first_group() -> None:
    groups = ops_views.figure_groups([{"key": "new_figure", "value": 1}])
    assert groups[0]["figures"][0]["key"] == "new_figure"
    assert groups[1]["figures"] == []


def test_the_scope_of_the_figures_is_always_named() -> None:
    excluded = ops_views.scope_statement(False)
    included = ops_views.scope_statement(True)
    assert "Fictional" in excluded and "ACME" not in excluded
    assert excluded.endswith("Sample history excluded.")
    assert included.endswith("Sample history included.")


# ---------------------------------------------------------- the checks screen


def _recorded_run(**overrides) -> dict:
    """Return a recorded run of the checks for the presentation checks."""
    recorded = {
        "run_id": "checkrun_demo",
        "ran_at": "2026-10-29T12:00:00+00:00",
        "ran_by": "persona_city_administrator",
        "counts": {"pass": 2, "fail": 1, "not_applicable": 5},
        "results": [
            {"check_id": "one", "title": "One", "status": "pass", "reason": "holds"},
            {"check_id": "two", "title": "Two", "status": "fail", "reason": "broke"},
            {
                "check_id": "three",
                "title": "Three",
                "status": "not_applicable",
                "reason": "nothing to check",
            },
        ],
    }
    recorded.update(overrides)
    return recorded


def test_the_checks_presenter_names_the_counts_and_the_run() -> None:
    view = ops_views.checks_presentation(_recorded_run())
    assert view["has_run"] is True
    assert view["is_latest"] is True
    assert view["title"].startswith("Recorded result at ")
    assert view["counts"] == {"pass": 2, "fail": 1, "not_applicable": 5}
    assert view["headline"] == ""
    # The technical identifier is in the run details, not in the headline.
    assert view["details"][0]["value"] == "checkrun_demo"
    assert view["details"][0]["testid"] == "checks-run-id"


def test_a_failure_of_the_checks_is_read_first() -> None:
    view = ops_views.checks_presentation(_recorded_run())
    statuses = [item["status"] for item in view["results"]]
    assert statuses == ["fail", "pass", "not_applicable"]
    assert view["results"][0]["status_label"] == "Failed"
    # The results that are not failures keep the recorded order.
    assert [item["check_id"] for item in view["results"][1:]] == ["one", "three"]


def test_a_run_without_an_applicable_check_does_not_say_it_passed() -> None:
    recorded = _recorded_run(
        counts={"pass": 0, "fail": 0, "not_applicable": 8},
        results=[
            {
                "check_id": "one",
                "title": "One",
                "status": "not_applicable",
                "reason": "not applicable (historical seed)",
            }
        ],
    )
    view = ops_views.checks_presentation(recorded)
    assert view["headline"] == "No checks were applicable."
    assert "passed" not in view["headline"].lower()


def test_a_selected_run_is_named_as_a_selected_run() -> None:
    view = ops_views.checks_presentation(_recorded_run(), selected=True)
    assert view["is_latest"] is False
    assert view["title"].startswith("Selected run at ")


def test_no_recorded_run_is_an_empty_presentation() -> None:
    view = ops_views.checks_presentation(None)
    assert view["has_run"] is False
    assert view["results"] == []
    assert view["counts"] == {"pass": 0, "fail": 0, "not_applicable": 0}


# ------------------------------------------------------ the permit type register


def test_every_permit_type_says_what_it_asks_for(session: Session) -> None:
    actor = _actor_for(session, "persona_city_administrator")
    view = admin_config_views.administration(session, actor)
    types = view["permit_types"]
    assert types
    for row in types:
        assert row["requirements_summary"]
        assert row["review_area_label"]
        assert row["required_fields_label"]
        assert row["required_documents_label"]
        assert row["process_label"]
        assert row["fee_schedule_label"] != "-"
        if row["required_documents"]:
            for document in row["required_documents"]:
                assert document.replace("_", " ") in row["requirements_summary"]
        else:
            assert row["requirements_summary"] == "No required document"


def test_a_discretionary_type_says_that_it_needs_a_person_or_a_board(
    session: Session,
) -> None:
    actor = _actor_for(session, "persona_city_administrator")
    view = admin_config_views.administration(session, actor)
    discretionary = [row for row in view["permit_types"] if row["discretionary"]]
    assert discretionary
    for row in discretionary:
        assert row["discretionary_label"] == "Requires a person or board"
    for row in view["permit_types"]:
        if not row["discretionary"]:
            assert row["discretionary_label"] == "Does not require a person or board"


def test_a_value_that_was_never_recorded_says_so(session: Session) -> None:
    actor = _actor_for(session, "persona_city_administrator")
    view = admin_config_views.administration(session, actor)
    # The old register showed a dash for an empty value; it now names it.
    assert admin_config_views.NOT_RECORDED == "Not recorded"
    for row in view["permit_types"]:
        assert row["fee_schedule_label"] in {row["fee_schedule_key"], "Not recorded"}
        assert row["fee_schedule_label"] != "-"

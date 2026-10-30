"""The presentation primitives of the administration area.

The shared macros and the operations helpers decide how a screen reads, never
what it says: they add a label, a group or a disclosure around the values the
view model already holds.  These checks prove that the primitives render the
markup the screens expect, that the plain labels replace the technical ones
and that the scope of the figures is always named.

The last part is the copy and accessibility pass over the six screens of the
City Administrator: the words they write are plain, the help names the labels
they show, every control has a name and the focus follows the order the
screen is written in.
"""
# REQUIRES: UX-01

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.help_docs import content
from acme_city.persistence.models import audit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import admin_config_views, ops_views

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import choose, client, settings  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from p3c_support import seed_help_request  # noqa: E402

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


def test_configuration_log_presentation_keeps_raw_values_in_expanded_details() -> None:
    view = admin_config_views.configuration_log_presentation(
        [
            {
                "action": "config.reason_code.retire",
                "target_type": "reason_code",
                "target_id": "missing_plan",
                "actor": "persona_city_administrator",
                "before": {"active": True},
                "after": {"active": False},
            }
        ]
    )
    entry = view[0]
    assert entry["action"] == "config.reason_code.retire"
    assert entry["action_label"] == "Retired reason code"
    assert entry["target_label"] == "Reason code"
    assert entry["before_display"] == {"active": True}
    assert entry["after_display"] == {"active": False}


def test_a_value_that_was_never_recorded_says_so(session: Session) -> None:
    actor = _actor_for(session, "persona_city_administrator")
    view = admin_config_views.administration(session, actor)
    # The old register showed a dash for an empty value; it now names it.
    assert admin_config_views.NOT_RECORDED == "Not recorded"
    for row in view["permit_types"]:
        assert row["fee_schedule_label"] in {row["fee_schedule_key"], "Not recorded"}
        assert row["fee_schedule_label"] != "-"


# ------------------------------------------------- the six screens, in words

#: The screens of the City Administrator, by the address they answer at.
SCREENS = {
    "administration": "/admin",
    "planning overview": "/overview",
    "operations dashboard": "/ops/dashboard",
    "checks": "/ops/checks",
    "audit log": "/ops/audit",
    "support": "/ops/support",
}

#: The templates each of those screens is written in.
SCREEN_TEMPLATES = {
    "administration": (
        "admin.html",
        "admin/_permit_types.html",
        "admin/_appearance.html",
        "admin/_users.html",
        "admin/_reason_codes.html",
        "admin/_log.html",
    ),
    "planning overview": ("overview.html",),
    "operations dashboard": ("ops_dashboard.html",),
    "checks": ("ops_checks.html",),
    "audit log": ("ops_audit.html",),
    "support": ("ops_support.html",),
}

#: The tags that carry no content of their own.
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}


def _authored_copy(name: str) -> str:
    """Return the words a template writes, without the markup and without the code."""
    source = (TEMPLATES / name).read_text(encoding="utf-8")
    source = re.sub(r"\{#.*?#\}", " ", source, flags=re.S)
    source = re.sub(r"\{%.*?%\}", " ", source, flags=re.S)
    source = re.sub(r"\{\{.*?\}\}", " ", source, flags=re.S)
    source = re.sub(r"<[^>]*>", " ", source, flags=re.S)
    return " ".join(source.split())


class _Screen(HTMLParser):
    """The parts of a rendered screen that a reader has to be able to name."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.controls: list[tuple[str, dict[str, str], bool]] = []
        self.labels: list[dict[str, str]] = []
        self.ids: set[str] = set()
        self.tabindex: list[tuple[str, str]] = []
        self.links: list[tuple[str, dict[str, str]]] = []
        self.buttons: list[tuple[str, dict[str, str]]] = []
        self._open: list[str] = []
        self._capture: list | None = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if "tabindex" in attributes:
            self.tabindex.append((tag, attributes["tabindex"]))
        if tag in {"input", "select", "textarea"}:
            inside_label = bool(self._open) and self._open[-1] == "label"
            self.controls.append((tag, attributes, inside_label))
        elif tag == "label":
            self.labels.append(attributes)
        if tag in {"a", "button"}:
            self._capture = [tag, attributes, []]
        if tag not in VOID_TAGS:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None and self._capture[0] == tag:
            text = " ".join("".join(self._capture[2]).split())
            if tag == "a":
                self.links.append((text, self._capture[1]))
            else:
                self.buttons.append((text, self._capture[1]))
            self._capture = None
        if tag in self._open:
            while self._open:
                if self._open.pop() == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture[2].append(data)


@pytest.fixture(scope="module")
def help_request(settings):
    """One help request the administrator can answer."""
    return seed_help_request(settings, application_id="app_d05")


@pytest.fixture()
def another_help_request(settings):
    """A second request from the same applicant, for a different case."""
    return seed_help_request(
        settings,
        application_id="app_synth_001",
        question="What happens after the first review?",
    )


@pytest.fixture()
def administrator(client):
    """A client that acts as the City Administrator."""
    choose(client, "persona_city_administrator")
    return client


@pytest.mark.parametrize("screen", sorted(SCREENS))
def test_the_words_a_screen_writes_are_plain(screen: str) -> None:
    for name in SCREEN_TEMPLATES[screen]:
        copy = _authored_copy(name)
        # A dash in a sentence reads like a label, not like a sentence.
        assert " - " not in copy, name
        assert "—" not in copy and "–" not in copy, name
        # A plural is written out, never as "application(s)".
        assert "(s)" not in copy, name


def test_the_overview_counts_the_further_applications_as_words(administrator) -> None:
    body = administrator.get("/overview").text
    assert "further application(s)" not in body
    assert "further version(s)" not in body
    # The demo holds more than one, so the plural reads.
    assert "further applications are counted" in body


def test_the_help_names_the_labels_the_screens_show(
    administrator, settings, help_request
) -> None:
    from acme_city.fixtures.synthetic import load_synthetic_year

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            load_synthetic_year(session, seed=20261028, count=1)
            session.add(
                audit.AuditEvent(
                    id=new_id("audit"),
                    correlation_id=new_id("corr"),
                    occurred_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
                    actor_id="persona_city_administrator",
                    actor_role_ids=[],
                    action="test.help_label_render",
                    target_type="application",
                    target_id="app_d05",
                    outcome="accepted",
                )
            )
    finally:
        factory.dispose()

    guide = content.guide("read-the-operations-dashboard-and-audit-log")
    bodies = [
        administrator.get(path).text
        for path in (*SCREENS.values(), "/ops/dashboard?synthetic=include")
    ]
    for step in guide["steps"]:
        for label in re.findall(r'"([^"]+)"', step):
            assert any(label in body for body in bodies), label


def test_every_control_of_the_six_screens_has_a_name(administrator) -> None:
    for screen, path in SCREENS.items():
        page = _Screen(administrator.get(path).text)
        targets = {label.get("for") for label in page.labels if label.get("for")}
        for tag, attributes, inside_label in page.controls:
            if attributes.get("type") == "hidden":
                continue
            named = (
                attributes.get("aria-label")
                or attributes.get("aria-labelledby")
                or attributes.get("id") in targets
                or inside_label
            )
            assert named, (screen, tag, attributes)


def test_the_focus_of_the_six_screens_follows_the_order_they_are_written(
    administrator,
) -> None:
    for screen, path in SCREENS.items():
        page = _Screen(administrator.get(path).text)
        # A positive tabindex moves the focus out of the order of the page.
        assert [item for item in page.tabindex if item[1] not in {"-1", "0"}] == [], screen


def test_the_row_actions_of_the_overview_name_the_record_they_act_on(
    administrator,
) -> None:
    page = _Screen(administrator.get("/overview").text)
    actions = [
        link
        for link in page.links
        if link[0] in {"Open the case", "Open the version", "Open the property context"}
    ]
    assert actions
    for text, attributes in actions:
        label = attributes.get("aria-label", "")
        # The name keeps the words on the button and adds the record.
        assert label.startswith(text), label
        assert label != text, label


def test_the_reply_button_of_the_support_screen_names_its_request(
    administrator, help_request, another_help_request
) -> None:
    page = _Screen(administrator.get("/ops/support").text)
    replies = [button for button in page.buttons if button[0] == "Send reply"]
    assert len(replies) == 2, "the two seeded requests show reply buttons"
    labels = []
    for text, attributes in replies:
        label = attributes.get("aria-label", "")
        assert label.startswith(text), label
        assert label != text, label
        labels.append(label)
    assert len(labels) == len(set(labels)), labels

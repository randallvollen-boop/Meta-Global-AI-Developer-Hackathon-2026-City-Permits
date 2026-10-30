"""The selector contract of the Data Steward screens.

The Data Steward screens may change what they show, but they may not change
the selectors that the acceptance fixtures, the browser walkthroughs and the
regression tests use to find a control.  This module records that inventory:
the selectors each screen renders, the vocabulary of the dynamic row
selectors the queue uses, and the shared controls that every staff screen
carries.

A selector that the demonstration state does not reach is checked in the
markup that declares it, so a later restyle cannot drop it silently.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, MDM-02, SEC-01

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import acme_city
from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import change, gis, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The package of the application, and the markup that declares the selectors.
PACKAGE = Path(acme_city.__file__).resolve().parent
TEMPLATES = PACKAGE / "templates"

#: The selectors of the queue, the focused case, the record profile and the
#: intake queue.  Every one of them is used by a test or a browser
#: walkthrough, so every one of them has to stay.
QUEUE_SELECTORS = (
    "issue-filters",
    "issue-filter",
    "issue-filter-count",
    "issue-table",
    "issue-link",
    "issue-status",
    "work-by-source-record",
)
CASE_SELECTORS = (
    "case-q1",
    "case-q2",
    "case-q3",
    "case-q4",
    "case-q5",
    "case-q6",
    "candidate",
    "compare-table",
    "compare-result",
    "evidence-block",
    "action-preview",
    "provenance",
)
PROFILE_SELECTORS = (
    "profile-tabs",
    "profile-tab",
    "profile-overview",
    "record-name",
    "record-status-label",
)
PROFILE_SOURCE_SELECTORS = (
    "profile-sources",
    "master-sources",
    "value-submitted",
)
INTAKE_SELECTORS = (
    "intake-table",
    "intake-row",
    "intake-tabs",
    "intake-bulk-form",
    "intake-bulk-submit",
    "signal-parcel",
    "signal-agent",
)
SHARED_SELECTORS = (
    "demo-switch",
    "persona-select",
    "acting-persona",
    "feedback",
    "feedback-message",
)

#: The selectors the demonstration state does not reach.  Each one is checked
#: in the file that declares it.
DECLARED_SELECTORS: dict[str, tuple[str, ...]] = {
    "steward_review.html": ("queue-empty", "queue-confirmation", "denied-actions"),
    "record_profile.html": (
        "source-links",
        "trusted-view",
        "value-proposed",
        "value-issued",
    ),
    "intake_queue.html": ("intake-select", "signal-duplicate", "signal-document-quality"),
    "steward_case.html": ("case-result", "action-preview-block"),
}

#: The vocabulary of the dynamic row selectors of the queue.  The view model
#: names them, so they are checked where they are written.
ROW_SELECTORS = (
    "match-proposal",
    "crosswalk-row",
    "parcel-proposal",
    "parcel-decided",
    "case-row",
    "issue-row",
)


def ids_of(html: str) -> set[str]:
    """Return the literal test ids of one rendered page."""
    return set(re.findall(r'data-testid="([^"{]+)"', html))


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    """Return a settings object with its own database under the test folder."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'selector-contract.db'}",
            "ACME_SECRET_KEY": "selector-contract-secret-value",
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
def client(environment: Settings) -> TestClient:
    """Return a client that acts as the Data Steward."""
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        test_client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
        assert test_client.get("/steward").status_code == 200
        yield test_client


def _add_work(environment: Settings) -> None:
    """Add one row of every kind the queue can show, beside the Cedarline work.

    The rows are fictional and belong to the demonstration parties, so the
    queue reaches the row selectors that the reset alone does not reach.
    """
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="case_selector_contract",
                    target_type="party",
                    target_id="party_cedarline",
                    change_kind="factual",
                    correlation_id="corr_selector_contract",
                    title="Correct the Cedarline trading name",
                    status="in_review",
                    destination="Permitting applicant profile",
                )
            )
            session.add(
                change.GovernanceIssue(
                    id="issue_selector_contract",
                    subject_type="party",
                    subject_id="party_cedarline",
                    issue_type="registration",
                    description="The registration looks out of step with the record",
                    responsible_queue_id="queue_contractors",
                    blocking=True,
                    status="open",
                )
            )
            session.add(
                registry.Crosswalk(
                    id="xwalk_selector_contract",
                    entity_id="party_halcyon",
                    entity_type="party",
                    source_system_id="permitting",
                    source_dataset_key="applicant_profiles",
                    source_record_id="PER-AP-0099",
                    link_status="approved",
                    decision="the reference on the source matches the master record",
                    decision_actor_id="persona_data_steward",
                    decided_at=datetime(2026, 9, 14, 15, 20, tzinfo=UTC),
                )
            )
            session.add(
                gis.ApplicationParcelMatch(
                    id="match_selector_contract",
                    application_id="app_d07",
                    submitted_text="17 Mill Row, Unit 2",
                    parcel_number="",
                    locator_status="U",
                    link_state="proposed",
                    correlation_id="corr_selector_match",
                )
            )
    finally:
        factory.dispose()


@pytest.fixture()
def steward(client: TestClient, environment: Settings) -> TestClient:
    """Return a client whose queue holds one row of every kind."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    _add_work(environment)
    return client


def test_the_queue_keeps_its_filters_table_and_row_selectors(steward: TestClient) -> None:
    """The queue keeps its filters, its table and one row selector of every kind."""
    body = steward.get("/steward").text
    found = ids_of(body)
    for selector in QUEUE_SELECTORS:
        assert selector in found, selector
    assert body.count('data-testid="issue-filter"') == 4
    assert body.count('data-testid="issue-filter-count"') == 4
    rows = re.findall(r'data-testid="([a-z-]+)" data-kind=', body)
    assert "match-proposal" in rows
    assert "case-row" in rows
    assert "issue-row" in rows
    assert "parcel-proposal" in rows


def test_the_decided_links_keep_the_crosswalk_row_selector(steward: TestClient) -> None:
    """A decided link is a resolved row of the queue."""
    body = steward.get("/steward?filter=resolved").text
    assert "crosswalk-row" in ids_of(body)


def test_the_focused_case_keeps_its_six_questions_and_its_evidence(
    steward: TestClient,
) -> None:
    """The case keeps the six questions, the comparison and the evidence."""
    queue = steward.get("/steward").text
    hrefs = re.findall(r'href="(/steward/issues/link/[^"]+)"', queue)
    assert hrefs, "the queue holds a match to compare"
    found = ids_of(steward.get(hrefs[0]).text)
    for selector in CASE_SELECTORS:
        assert selector in found, selector


def test_the_record_profile_keeps_its_tabs_and_its_value_bands(
    steward: TestClient,
) -> None:
    """The profile keeps its tabs, its source table and its submitted values."""
    found = ids_of(steward.get("/masters/party_cedarline").text)
    for selector in PROFILE_SELECTORS:
        assert selector in found, selector
    sources = ids_of(steward.get("/masters/party_cedarline?view=sources").text)
    for selector in PROFILE_SOURCE_SELECTORS:
        assert selector in sources, selector


def test_the_issued_record_keeps_the_issued_value_band(steward: TestClient) -> None:
    """A record with an issued permit still shows the issued value."""
    found = ids_of(steward.get("/masters/party_marrow").text)
    assert "value-issued" in found


def test_the_applicant_view_keeps_the_source_links_table(steward: TestClient) -> None:
    """The People and organizations view of a record keeps its source table."""
    response = steward.post(
        "/api/session/select", json={"actor_id": "persona_applicant"}
    )
    assert response.status_code == 200
    found = ids_of(steward.get("/applicants/party_applicant_1?view=sources").text)
    assert "source-links" in found


def test_the_intake_queue_keeps_its_table_and_its_bulk_controls(
    steward: TestClient,
) -> None:
    """The intake queue keeps its table, its signals and the bulk form."""
    found = ids_of(steward.get("/queue/intake").text)
    for selector in INTAKE_SELECTORS:
        assert selector in found, selector


def test_every_steward_screen_keeps_the_shared_controls(steward: TestClient) -> None:
    """Every steward screen carries the demo switch, the persona and the feedback."""
    for path in (
        "/steward",
        "/steward?filter=resolved",
        "/masters",
        "/masters/party_cedarline",
        "/source-records",
        "/activity",
        "/queue/intake",
        "/queue/early-resolution",
    ):
        found = ids_of(steward.get(path).text)
        for selector in SHARED_SELECTORS:
            assert selector in found, (path, selector)


def test_the_recorded_selectors_are_still_declared() -> None:
    """No recorded selector may disappear from the markup that declares it."""
    for name, selectors in DECLARED_SELECTORS.items():
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for selector in selectors:
            quoted = re.compile("[" + chr(39) + chr(34) + "]" + re.escape(selector) + "[" + chr(39) + chr(34) + "]")
            assert quoted.search(text), (name, selector)
    views = (PACKAGE / "ui" / "steward_views.py").read_text(encoding="utf-8")
    for selector in ROW_SELECTORS:
        assert f'"{selector}"' in views, selector

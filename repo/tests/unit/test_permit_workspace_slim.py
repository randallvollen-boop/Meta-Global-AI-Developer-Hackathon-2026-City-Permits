"""The permit workspace shows the decision and collapses the rest.

The header, the tabs, the next action, the issues, the checks, the
recommendation, the decision and the property card stay in view. The other
sections sit inside a closed More details element.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import gis, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

REVIEWER = "persona_permit_reviewer"
CASE = "app_synth_001"

KEPT = (
    'data-testid="case-header"',
    'data-testid="workspace-tabs"',
    'data-testid="next-action"',
    'data-testid="issue-list-section"',
    'data-testid="application-checks"',
    'data-testid="stage-decision"',
    'data-testid="review-actions"',
    'data-testid="document-table"',
    'data-testid="responsibility-owner"',
    'data-testid="responsibility-open-issues"',
    'data-testid="empty-stages"',
)

COLLAPSED = (
    'data-testid="case-pipeline"',
    'data-testid="responsibility-steward"',
    'data-testid="muse-panel"',
    'data-testid="agent-section"',
    'data-testid="fee-preview"',
    'data-testid="more-actions"',
    'data-testid="corrections-more"',
    'data-testid="revision-list"',
    'data-testid="submitted-facts"',
    'data-testid="evidence-panel"',
    'data-testid="identity-parties"',
    'data-testid="comments-panel"',
)

REMOVED = (
    'data-testid="synthetic-badge"',
    'data-testid="applicant-tracker"',
    "Server-recorded state",
    "The rule checks do not test these links.",
    "Applicant-facing explanations are written",
    "A recommendation never supplies the reviewer identity",
    "Uploader and content hash are in each document",
    "Muse proposes values",
    "A replay is only a visual playback",
    "Simulated enterprise GIS",
    "The city identifies a property",
    "These are synthetic ACME fee rules",
)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'workspace-slim.db'}",
            "ACME_SECRET_KEY": "workspace-slim-test-secret-value",
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
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def inside_details(page: str, marker: str) -> bool:
    index = page.index(marker)
    opens = len(re.findall(r"<details\b", page[:index]))
    closes = len(re.findall(r"</details>", page[:index]))
    return opens > closes


def test_kept_sections_stay_visible_and_the_rest_is_collapsed(
    client: TestClient, environment: Settings
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, CASE)
            assert application is not None
            session.add(
                gis.ApplicationParcelMatch(
                    id="pmatch_slim",
                    application_id=CASE,
                    correlation_id=application.correlation_id,
                    version=1,
                    submitted_text="400 Lantern Row, Suite 2, ACME City",
                    matched_address="400 Lantern Row, Unit 2",
                    address_id="address_400_lantern_unit_2",
                    parcel_id="parcel_1001",
                    parcel_number="ACME-P-1001",
                    score=100.0,
                    locator_status="M",
                    method="locator",
                    link_state="approved",
                    proposed_by="persona_data_steward",
                )
            )
    finally:
        factory.dispose()
    assert client.post("/api/session/select", json={"actor_id": REVIEWER}).status_code == 200
    page = client.get(f"/permits/{CASE}").text
    for marker in KEPT:
        assert marker in page, marker
        assert not inside_details(page, marker), marker
    for marker in COLLAPSED:
        assert marker in page, marker
        assert inside_details(page, marker), marker
    # The history table exists only after a decision is recorded. On this
    # undecided case the empty line stays in view.
    assert 'data-testid="decision-table"' not in page
    assert 'data-testid="decision-empty"' in page
    assert not inside_details(page, 'data-testid="decision-empty"')
    decided = client.get("/permits/app_d07").text
    assert 'data-testid="decision-summary"' in decided
    assert not inside_details(decided, 'data-testid="decision-summary"')
    assert 'data-testid="decision-table"' in decided
    assert inside_details(decided, 'data-testid="decision-table"')
    for marker in REMOVED:
        assert marker not in page, marker
    assert 'data-testid="property-card"' in page
    assert not inside_details(page, 'data-testid="property-card"')
    assert 'data-testid="property-facts"' in page
    assert "Confirm parcel" in page
    # This seeded case has no extraction, so the notice is not on the page.
    # The template still carries the one-line product rule.
    template = (
        Path(__file__).resolve().parents[2]
        / "src/acme_city/templates/permit_workspace.html"
    ).read_text(encoding="utf-8")
    assert 'data-testid="ai-not-review"' in template
    assert "A successful extraction is not a review." in template
    assert "Suggested fields are proposals" not in template
    assert "Suggested fields are proposals" not in page
    queue = re.search(r'data-testid="responsibility-queue">(.*?)</p>', page, re.S)
    assert queue
    assert "This is a configured demonstration target and makes no service promise." in queue.group(1)
    assert "First review target" not in queue.group(1)
    blockers = re.search(r'id="application-blockers".*?</ul>', page, re.S)
    assert blockers
    assert not inside_details(page, 'id="application-blockers"')
    assert blockers.group(0).count("Blocker</span>") == blockers.group(0).count("<li>")
    assert 'class="issue bad"' not in page

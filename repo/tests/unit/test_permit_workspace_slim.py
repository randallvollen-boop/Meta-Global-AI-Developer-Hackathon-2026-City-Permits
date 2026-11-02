"""Each permit workspace section collapses, and the current step starts open.

The header and the tabs stay outside any disclosure. The section the next
step needs starts open. The other sections start closed. Nothing is stored.
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
from acme_city.ui.view_models import workspace_open_sections

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


def section_state(page: str, marker: str) -> str:
    """Return open, closed, or none for the details that holds this marker.

    A marker that sits on the details tag itself is that section. The open
    attribute is the only thing that starts a section open.
    """
    index = page.index(marker)
    head = page[:index]
    last_lt = head.rfind("<")
    if last_lt != -1 and page[last_lt : last_lt + 8].lower().startswith("<details"):
        end = page.find(">", index)
        if end != -1:
            head = page[: end + 1]
    stack: list[bool] = []
    for match in re.finditer(r"<details\b([^>]*)>|</details>", head, re.I):
        if match.group(0).lower().startswith("</"):
            if stack:
                stack.pop()
            continue
        attrs = match.group(1) or ""
        stack.append(bool(re.search(r"(?:^|\s)open(?:\s|=|$)", attrs)))
    if not stack:
        return "none"
    return "open" if stack[-1] else "closed"


def test_open_sections_follow_the_stage() -> None:
    before = workspace_open_sections(
        has_evaluation=False,
        decision=None,
        blockers=[{"code": "identity_unlinked"}],
        issued=False,
        has_assessment=False,
    )
    assert before["next"] is True
    assert before["checks"] is True
    assert before["issues"] is False
    assert before["decision"] is False
    assert before["actions"] is False
    assert before["fee"] is False
    assert before["permit"] is False
    assert before["property"] is False
    parcel = workspace_open_sections(
        has_evaluation=False,
        decision=None,
        blockers=[{"code": "parcel_unconfirmed"}],
        issued=False,
        has_assessment=False,
    )
    assert parcel["property"] is True
    assert parcel["checks"] is True
    assert parcel["issues"] is False
    blocked = workspace_open_sections(
        has_evaluation=True,
        decision=None,
        blockers=[{"code": "identity_unlinked"}],
        issued=False,
        has_assessment=False,
    )
    assert blocked["checks"] is True
    assert blocked["issues"] is True
    assert blocked["decision"] is False
    assert blocked["actions"] is False
    ready = workspace_open_sections(
        has_evaluation=True,
        decision=None,
        blockers=[],
        issued=False,
        has_assessment=False,
    )
    assert ready["checks"] is True
    assert ready["decision"] is True
    assert ready["actions"] is True
    assert ready["fee"] is False
    assert ready["issues"] is False
    approved = workspace_open_sections(
        has_evaluation=True,
        decision={"outcome": "approved"},
        blockers=[],
        issued=False,
        has_assessment=True,
    )
    assert approved["fee"] is True
    assert approved["actions"] is True
    assert approved["checks"] is False
    assert approved["decision"] is False
    assert approved["permit"] is False
    denied = workspace_open_sections(
        has_evaluation=True,
        decision={"outcome": "denied"},
        blockers=[],
        issued=False,
        has_assessment=False,
    )
    assert denied["decision"] is True
    assert denied["checks"] is True
    assert denied["actions"] is False
    assert denied["fee"] is False
    issued = workspace_open_sections(
        has_evaluation=True,
        decision={"outcome": "approved"},
        blockers=[],
        issued=True,
        has_assessment=True,
    )
    assert issued["permit"] is True
    assert issued["checks"] is False
    assert issued["decision"] is False
    assert issued["actions"] is False
    assert issued["fee"] is False
    assert issued["next"] is True


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
    open_now = (
        'data-testid="next-action"',
        'data-testid="application-checks"',
        'id="application-blockers"',
    )
    closed_now = (
        'data-testid="issue-list-section"',
        'data-testid="stage-decision"',
        'data-testid="review-actions"',
        'data-testid="document-table"',
        'data-testid="responsibility-owner"',
        'data-testid="responsibility-open-issues"',
        'data-testid="empty-stages"',
        'data-testid="decision-empty"',
        *COLLAPSED,
    )
    for marker in KEPT:
        assert marker in page, marker
    for marker in open_now:
        assert section_state(page, marker) == "open", marker
    for marker in closed_now:
        assert section_state(page, marker) == "closed", marker
    assert section_state(page, 'data-testid="case-header"') == "none"
    assert section_state(page, 'data-testid="workspace-tabs"') == "none"
    # The history table exists only after a decision is recorded. On this
    # undecided case the empty line stays in the closed decision section.
    assert 'data-testid="decision-table"' not in page
    assert 'data-testid="decision-empty"' in page
    decided = client.get("/permits/app_d07").text
    assert 'data-testid="decision-summary"' in decided
    assert section_state(decided, 'data-testid="decision-summary"') == "closed"
    assert 'data-testid="decision-table"' in decided
    assert section_state(decided, 'data-testid="decision-table"') == "closed"
    assert section_state(decided, 'data-testid="stage-permit"') == "open"
    assert section_state(decided, 'data-testid="application-checks"') == "closed"
    for marker in REMOVED:
        assert marker not in page, marker
    assert 'data-testid="property-card"' in page
    blocker_list = re.search(r'id="application-blockers".*?</ul>', page, re.S)
    assert blocker_list
    codes = re.findall(r'badge-blocking">([^<]+)', blocker_list.group(0))
    assert codes
    property_state = "open" if codes[0] == "parcel_unconfirmed" else "closed"
    assert section_state(page, 'data-testid="property-card"') == property_state
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
    assert "localStorage" not in template
    assert "Suggested fields are proposals" not in template
    assert "Suggested fields are proposals" not in page
    queue = re.search(r'data-testid="responsibility-queue">(.*?)</p>', page, re.S)
    assert queue
    assert "This is a configured demonstration target and makes no service promise." in queue.group(1)
    assert "First review target" not in queue.group(1)
    blockers = re.search(r'id="application-blockers".*?</ul>', page, re.S)
    assert blockers
    assert section_state(page, 'id="application-blockers"') == "open"
    assert blockers.group(0).count("Blocker</span>") == blockers.group(0).count("<li>")
    assert 'class="issue bad"' not in page
    summaries = re.findall(
        r'<details class="ws-section\b[^>]*>\s*<summary>(.*?)</summary>', page, re.S
    )
    assert summaries
    for summary in summaries:
        assert "<h2" in summary, summary

"""The permit workspace after the side rail is removed.

Record review decision, Advance, Issue permit and Run application checks sit
on the Review tab. The other actions sit in More actions. The case record
sits in the header, and the fee preview is collapsed.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance, gis, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.ui.router import router as ui_router

REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
CASE = "app_synth_001"
DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'workspace.db'}",
            "ACME_SECRET_KEY": "workspace-rail-test-secret-value",
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
    app.include_router(permit_router)
    with TestClient(app) as test_client:
        yield test_client


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def workspace(client: TestClient, application_id: str = CASE) -> str:
    response = client.get(f"/permits/{application_id}")
    assert response.status_code == 200, response.text
    return response.text


def review_panel(page: str) -> str:
    start = page.index('id="panel-review"')
    end = page.index('id="panel-documents"')
    return page[start:end]


def details_block(page: str, attr: str, value: str) -> str:
    """Return one details element, including nested details."""
    match = re.search(rf'<details\b[^>]*{attr}="{re.escape(value)}"[^>]*>', page)
    assert match, f"no details {attr}={value}"
    start = match.start()
    depth = 0
    for token in re.finditer(r"</?details\b[^>]*>", page[start:]):
        depth += -1 if token.group(0).startswith("</") else 1
        if depth == 0:
            return page[start : start + token.end()]
    raise AssertionError(f"unclosed details {attr}={value}")


def _attrs(tag: str) -> dict[str, str]:
    return {name: html.unescape(value) for name, value in re.findall(r'([\w:-]+)="([^"]*)"', tag)}


def form_values(block: str) -> dict[str, str]:
    """Return the fields a browser would post from the first form in ``block``."""
    form = re.search(r"<form\b.*?</form>", block, re.S)
    assert form, block[:120]
    body = form.group(0)
    values: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", body):
        attrs = _attrs(tag)
        if "name" in attrs:
            values[attrs["name"]] = attrs.get("value", "")
    for tag, text in re.findall(r"(<textarea\b[^>]*>)(.*?)</textarea>", body, re.S):
        attrs = _attrs(tag)
        if "name" in attrs:
            values[attrs["name"]] = html.unescape(text)
    for tag, inner in re.findall(r"(<select\b[^>]*>)(.*?)</select>", body, re.S):
        attrs = _attrs(tag)
        name = attrs.get("name")
        if not name:
            continue
        chosen = ""
        options = re.findall(r"<option\b([^>]*)>", inner)
        for option in options:
            parsed = _attrs(option)
            if "selected" in option:
                chosen = parsed.get("value", "")
                break
        else:
            if options:
                chosen = _attrs(options[0]).get("value", "")
        values[name] = chosen
    return values


def submit(client: TestClient, action_id: str, fields: dict[str, str]):
    return client.post(
        f"/ui/actions/{action_id}",
        data=fields,
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def approve_links(environment: Settings) -> None:
    """Record the canonical links a steward would have approved."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            for party_id in ("party_cedarline", "party_ironvale"):
                session.add(
                    registry.Crosswalk(
                        id=f"crosswalk_{party_id}",
                        entity_id=party_id,
                        entity_type="party",
                        source_system_id="permitting",
                        source_dataset_key="applicant_profiles",
                        source_record_id=f"PER-{party_id}",
                        link_status="approved",
                        decision="Approved by the data steward.",
                        decision_actor_id=STEWARD,
                        decided_at=DECIDED_AT,
                    )
                )
            session.add(
                finance.FinanceAccountLink(
                    id="faclink_legacy",
                    account_id="facct_cedarline_legacy",
                    party_id="party_cedarline",
                    link_status="approved",
                    decided_by_actor_id=STEWARD,
                    decided_at=DECIDED_AT,
                )
            )
    finally:
        factory.dispose()


def propose_parcel(environment: Settings, application_id: str = CASE) -> None:
    """Record a proposed parcel link the steward can approve."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, application_id)
            assert application is not None
            session.add(
                gis.ApplicationParcelMatch(
                    id=f"pmatch_{application_id}",
                    application_id=application_id,
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
                    link_state="proposed",
                    note="One candidate scored above the threshold.",
                    proposed_by=STEWARD,
                )
            )
    finally:
        factory.dispose()


def add_recommendation(environment: Settings, application_id: str, outcome: str) -> None:
    """Attach a pending recommendation to the current evaluation."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            evaluation = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.application_id == application_id,
                    permit.Evaluation.status == "current",
                )
            ).scalar_one()
            session.add(
                permit.Recommendation(
                    id=f"rec_{application_id}_{outcome}",
                    application_id=application_id,
                    evaluation_id=evaluation.id,
                    proposed_outcome=outcome,
                    evidence_refs=[],
                    status="pending",
                    rationale=f"The checks support {outcome}.",
                    stale=False,
                )
            )
    finally:
        factory.dispose()


def approve_parcel_link(client: TestClient, application_id: str = CASE) -> None:
    choose(client, STEWARD)
    page = workspace(client, application_id)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert token
    response = submit(
        client,
        "parcel.link.decide",
        {
            "csrf_token": html.unescape(token.group(1)),
            "action_id": "parcel.link.decide",
            "application_id": application_id,
            "decision": "approve",
            "expected_version": "1",
            "reason": "the corrected address falls inside this parcel",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"


def test_the_rail_is_gone_and_actions_sit_on_the_review_tab(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = workspace(client)
    review = review_panel(page)
    header = re.search(r'data-testid="case-header".*?</div>\s*</div>', page, re.S)
    assert header
    assert 'data-testid="case-record"' in header.group(0)
    visible = text_of(header.group(0))
    assert "Priority" in visible
    assert "app_synth_001" not in visible
    assert "com_ti" not in visible
    assert 'class="rail"' not in page
    assert 'aside class="rail"' not in page
    stylesheet = (ROOT / "src/acme_city/static/app.css").read_text(encoding="utf-8")
    assert ".rail" not in stylesheet

    assert 'data-testid="review-actions"' in review
    evaluate = details_block(review, "data-action-id", "permit.evaluate")
    assert 'data-permitted="true"' in evaluate
    assert "Run application checks" in evaluate
    issue = details_block(review, "data-action-id", "permit.issue")
    assert 'data-permitted="false"' in issue
    assert 'data-testid="action-denied-reason"' in issue
    assert "a current approved decision is required before issuance" in issue
    assert 'data-testid="decision-form"' not in page
    assert 'data-testid="advance-form"' not in page

    more = details_block(review, "data-testid", "more-actions")
    assert not re.search(r"<details\b[^>]*\bopen\b", more.split(">", 1)[0])
    assert 'data-action-id="permit.revise"' in more
    assert 'data-action-id="permit.evaluate"' not in more
    fees = details_block(review, "data-testid", "fee-preview")
    assert not re.search(r"<details\b[^>]*\bopen\b", fees.split(">", 1)[0])
    assert "These are synthetic ACME fee rules" not in fees


def test_run_application_checks_shows_the_rule_results(client: TestClient) -> None:
    choose(client, REVIEWER)
    fields = form_values(details_block(workspace(client), "data-action-id", "permit.evaluate"))
    assert fields["action_id"] == "permit.evaluate"
    response = submit(client, "permit.evaluate", fields)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    page = workspace(client)
    review = review_panel(page)
    assert 'data-testid="rule-results"' in review
    assert 'data-testid="decision-form"' in review
    assert "Record review decision" in review


def test_record_review_decision_needs_a_rationale(
    client: TestClient, environment: Settings
) -> None:
    approve_links(environment)
    choose(client, REVIEWER)
    checked = submit(
        client,
        "permit.evaluate",
        form_values(details_block(workspace(client), "data-action-id", "permit.evaluate")),
    )
    assert checked.status_code == 200, checked.text
    form = details_block(workspace(client), "data-testid", "decision-form")
    assert "Record the decision" in form
    refused = submit(client, "permit.decide", {**form_values(form), "outcome": "denied", "reason": "   "})
    assert refused.status_code == 422, refused.text
    assert "rationale" in refused.json()["message"]
    recorded = submit(
        client,
        "permit.decide",
        {
            **form_values(form),
            "outcome": "denied",
            "reason": "The work does not meet the code.",
            "reason_code": "DOES_NOT_MEET_CODE",
        },
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["status"] == "accepted"
    page = workspace(client)
    assert 'data-testid="decision-summary"' in page
    assert "Denied" in page or "denied" in page


def test_issue_permit_is_refused_until_reconciled(
    client: TestClient, environment: Settings
) -> None:
    approve_links(environment)
    choose(client, REVIEWER)
    checked = submit(
        client,
        "permit.evaluate",
        form_values(details_block(workspace(client), "data-action-id", "permit.evaluate")),
    )
    assert checked.status_code == 200, checked.text
    decided = submit(
        client,
        "permit.decide",
        {
            **form_values(details_block(workspace(client), "data-testid", "decision-form")),
            "outcome": "approved",
            "reason": "The submitted work meets the checks.",
        },
    )
    assert decided.status_code == 200, decided.text
    issue = details_block(review_panel(workspace(client)), "data-action-id", "permit.issue")
    assert 'data-permitted="true"' in issue
    assert "Issue permit" in issue
    refused = submit(client, "permit.issue", form_values(issue))
    assert refused.status_code == 422, refused.text
    assert "may not be issued yet" in refused.json()["message"]


def test_confirm_and_revert_the_recommendation(
    client: TestClient, environment: Settings
) -> None:
    choose(client, REVIEWER)
    checked = submit(
        client,
        "permit.evaluate",
        form_values(details_block(workspace(client), "data-action-id", "permit.evaluate")),
    )
    assert checked.status_code == 200, checked.text
    add_recommendation(environment, CASE, "deny")
    confirm = details_block(workspace(client), "data-testid", "recommendation-confirm")
    assert 'data-testid="recommendation-confirm-submit"' in confirm
    confirmed = submit(
        client,
        "recommendation.confirm",
        {
            **form_values(confirm),
            "reason": "the checks support a denial",
            "reason_code": "DOES_NOT_MEET_CODE",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "accepted"
    assert 'data-testid="recommendation-confirm"' not in workspace(client)

    other = "app_d03"
    choose(client, REVIEWER)
    other_checks = submit(
        client,
        "permit.evaluate",
        form_values(details_block(workspace(client, other), "data-action-id", "permit.evaluate")),
    )
    assert other_checks.status_code == 200, other_checks.text
    add_recommendation(environment, other, "approve")
    revert = details_block(workspace(client, other), "data-testid", "recommendation-revert")
    assert 'data-testid="recommendation-revert-submit"' in revert
    reverted = submit(
        client,
        "recommendation.revert",
        {**form_values(revert), "reason": "I want to check the setback myself"},
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "accepted"
    assert 'data-testid="recommendation-revert"' not in workspace(client, other)


def test_confirm_parcel(client: TestClient, environment: Settings) -> None:
    propose_parcel(environment)
    approve_parcel_link(client)
    choose(client, REVIEWER)
    page = workspace(client)
    confirm = details_block(page, "data-action-id", "parcel.confirm")
    assert 'data-permitted="true"' in confirm
    assert "Confirm parcel" in confirm
    response = submit(client, "parcel.confirm", form_values(confirm))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    again = details_block(workspace(client), "data-action-id", "parcel.confirm")
    assert 'data-permitted="false"' in again
    assert "the parcel is already confirmed" in again
    assert 'data-testid="action-denied-reason"' in again


def test_walkthrough_step_6_end_to_end(client: TestClient, environment: Settings) -> None:
    approve_links(environment)
    propose_parcel(environment)
    approve_parcel_link(client)
    choose(client, REVIEWER)
    confirmed = submit(
        client,
        "parcel.confirm",
        form_values(details_block(workspace(client), "data-action-id", "parcel.confirm")),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "accepted"

    checked = submit(
        client,
        "permit.evaluate",
        form_values(details_block(workspace(client), "data-action-id", "permit.evaluate")),
    )
    assert checked.status_code == 200, checked.text
    page = workspace(client)
    review = review_panel(page)
    assert 'data-testid="rule-results"' in review
    decision = details_block(review, "data-testid", "decision-form")
    assert "Record review decision" in decision
    decided = submit(
        client,
        "permit.decide",
        {
            **form_values(decision),
            "outcome": "approved",
            "reason": "The submitted work meets the checks.",
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "accepted"
    issue = details_block(review_panel(workspace(client)), "data-action-id", "permit.issue")
    refused = submit(client, "permit.issue", form_values(issue))
    assert refused.status_code == 422, refused.text
    assert "may not be issued yet" in refused.json()["message"]


def test_advance_on_the_review_tab_shows_why_or_moves_the_case(
    client: TestClient, environment: Settings
) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(permit.Application, CASE)
            assert row is not None
            row.status = "needs_information"
    finally:
        factory.dispose()
    choose(client, STEWARD)
    review = review_panel(workspace(client))
    form = details_block(review, "data-testid", "advance-form")
    assert "Advance to review" in form
    button = re.search(r'<button\b[^>]*data-testid="advance-submit"[^>]*>', form)
    assert button
    if "disabled" in button.group(0):
        assert 'data-testid="advance-blockers-why"' in form
        assert 'aria-describedby="advance-blockers-why"' in button.group(0)
        assert "Advance to review is off until these are cleared or waived" in form
        return
    response = submit(client, "permit.case.advance", form_values(form))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"

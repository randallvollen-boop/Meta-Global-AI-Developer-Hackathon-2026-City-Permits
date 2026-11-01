"""The operations, insight and rules screens after the slim-down.

A worker sees the figure, the filter, the check result and the next action.
Charts, extra filters, history and the add-reason form sit behind More
details. Every button of these screens is pressed here.
"""
# REQUIRES: UX-01, UX-02, UX-03
# The screens show only what a decision needs, and every action is exercised
# through the control that offers it.

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402
from p3c_support import seed_help_request  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.ids import new_id  # noqa: E402
from acme_city.persistence.models import audit  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

ADMIN = "persona_city_administrator"


def csrf_of(body: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None, "the page carries a form token"
    return match.group(1)


def choose(client: TestClient) -> None:
    """Establish a server-held session for the City Administrator."""
    response = client.post("/api/session/select", json={"actor_id": ADMIN})
    assert response.status_code == 200, response.text


def closed(body: str, testid: str) -> None:
    """Assert a disclosure is present and not forced open."""
    match = re.search(rf'<details[^>]*data-testid="{testid}"[^>]*>', body)
    assert match is not None, testid
    assert "open" not in match.group(0), testid


def open_disclosure(body: str, testid: str) -> str:
    """Return the markup inside a disclosure, whether it is open or not."""
    match = re.search(
        rf'<details[^>]*data-testid="{testid}"[^>]*>(.*?)</details>', body, re.S
    )
    assert match is not None, testid
    return match.group(1)


def post_action(client: TestClient, action_id: str, fields: dict, page: str) -> None:
    """Press one action button and require the server to accept it."""
    response = client.post(
        f"/ui/actions/{action_id}",
        data={"csrf_token": csrf_of(client.get(page).text), "next": page, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted", response.text


def press_apply(client: TestClient, page: str, testid: str, **query: str) -> str:
    """Press the Apply button of a filter form and return the new page.

    The button is a submit of the form, so the request is the form's action
    with the chosen values.
    """
    body = client.get(page).text
    tag = re.search(rf'<form[^>]*data-testid="{testid}"[^>]*>', body, re.S)
    assert tag is not None, testid
    action = re.search(r'action="([^"]+)"', tag.group(0))
    assert action is not None, testid
    target = action.group(1)
    if query:
        target += "?" + "&".join(f"{key}={value}" for key, value in query.items())
    response = client.get(target)
    assert response.status_code == 200, response.text
    return response.text


class _World:
    def __init__(self, client: TestClient, settings) -> None:
        self.client = client
        self.settings = settings


def test_the_dashboard_keeps_definitions_and_the_data_tables(client: _World) -> None:
    """Six figures keep their definitions, and each chart's table stays visible."""
    choose(client.client)
    dash = client.client.get("/ops/dashboard").text
    assert dash.count('data-testid="ops-figure"') == 6
    definitions = re.findall(
        r'data-testid="ops-figure-definition">(.*?)</span>', dash
    )
    assert len(definitions) == 6
    assert all(len(item) > 20 for item in definitions)
    assert "Counts over stored records." in dash
    assert 'data-testid="evidence-panel"' not in dash
    assert "adm-chart-details" not in dash
    assert "adm-table-details" not in dash
    # The outcome table says what it is in its heading, not in a second line.
    assert "Decision rows, all time, grouped by outcome." not in dash
    assert 'data-testid="ops-decisions"' in dash
    # The parts of a figure sit behind More details.
    more = re.search(
        r'<details[^>]*data-testid="ops-figure-more"[^>]*data-figure="needs_a_person"',
        dash,
    )
    assert more is not None
    assert "Recommendations held for a person" in open_disclosure(dash, "ops-figure-more")
    for testid in ("chart-status", "chart-channel"):
        chart = re.search(
            rf'<details[^>]*data-testid="{testid}-chart".*?</details>', dash, re.S
        )
        assert chart is not None and "open" not in chart.group(0).split(">", 1)[0]
        assert f'data-testid="{testid}-table"' not in chart.group(0)
        assert f'data-testid="{testid}-table"' in dash
    included = client.client.get("/ops/dashboard?synthetic=include").text
    assert "Sample history" in included
    toggle = re.search(r'href="([^"]+)"[^>]*data-testid="ops-synthetic-toggle"', dash)
    if toggle is not None:
        assert client.client.get(toggle.group(1)).status_code == 200


def test_run_checks_and_the_audit_filter_for_a_recorded_decision(client: _World) -> None:
    """Run checks, then filter the audit log the way the walkthrough does."""
    choose(client.client)
    checks = client.client.get("/ops/checks").text
    assert "Running checks does not change permits or fees." in checks
    assert 'data-testid="evidence-panel"' not in checks
    version = re.search(
        r'data-testid="checks-run-form".*?name="expected_version" value="([^"]*)"',
        checks,
        re.S,
    )
    assert version is not None
    post_action(
        client.client,
        "ops.checks.run",
        {"expected_version": version.group(1)},
        "/ops/checks",
    )
    recorded = client.client.get("/ops/checks").text
    assert recorded.count('data-testid="check-row"') == 8
    assert "not applicable (historical seed)" in recorded
    closed(recorded, "checks-details")

    factory = SessionFactory(client.settings.database_url)
    event_id = new_id("audit")
    try:
        with transaction(factory) as session:
            session.add(
                audit.AuditEvent(
                    id=event_id,
                    correlation_id=new_id("corr"),
                    occurred_at=datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
                    actor_id=ADMIN,
                    actor_role_ids=[],
                    action="permit.decide",
                    target_type="application",
                    target_id="app_d05",
                    outcome="accepted",
                    references=["app_d05"],
                    metadata_json={"approval_basis_label": "A recorded decision basis"},
                )
            )
    finally:
        factory.dispose()

    audit_page = client.client.get("/ops/audit").text
    assert 'data-testid="evidence-panel"' not in audit_page
    assert "See who changed a record" not in audit_page
    option = re.search(
        r'<option value="([^"]+)">Recorded permit decision</option>', audit_page
    )
    assert option is not None
    filtered = press_apply(
        client.client, "/ops/audit", "audit-filters", action=option.group(1)
    )
    row = filtered.split('data-testid="audit-row"', 1)[1].split("</tr>", 1)[0]
    assert "Recorded permit decision" in row
    assert 'data-detail-kind="audit-event"' in row
    assert "View details" in row
    # The basis of the outcome is behind View details, not in the table.
    assert "A recorded decision basis" not in row
    assert 'data-testid="audit-basis"' not in row

    drawer = client.client.get(f"/ops/audit?detail=audit-event:{event_id}").text
    body = drawer.split('data-testid="ui-drawer-body"', 1)[1]
    assert "Approval basis" in body
    assert "A recorded decision basis" in body
    assert "References" in body
    assert "SYN-APP-005" in body


def test_the_city_view_filters_and_keeps_the_map(client: _World) -> None:
    """Apply keeps the count, the definition and the district table."""
    choose(client.client)
    city = client.client.get("/insight/city").text
    assert 'data-testid="evidence-panel"' not in city
    assert "Fictional ACME City permit records by district" not in city
    assert "permits match" in city
    assert "Permits: applications that have been submitted" in city
    assert 'data-testid="district-table"' in city
    # The extra filters and the quick views are behind their disclosures.
    closed(city, "insight-more-filters")
    closed(city, "insight-quick-views")
    closed(city, "insight-exceptions")
    closed(city, "insight-categories")
    closed(city, "insight-trend")
    closed(city, "insight-mix")
    closed(city, "insight-records")
    assert "Exceptions: a variance request" not in city
    # The fictional note is one line.
    assert 'data-testid="synthetic-panel"' in city
    assert "Fictional data" not in city

    select = re.search(r'data-testid="filter-type".*?</select>', city, re.S)
    assert select is not None
    key = next(value for value in re.findall(r'<option value="([^"]+)"', select.group(0)) if value)
    chosen = press_apply(client.client, "/insight/city", "insight-filters", type=key)
    assert "permits match" in chosen
    assert 'data-testid="district-table"' in chosen
    assert f'value="{key}" selected' in chosen


def test_support_lookup_reply_and_record(client: _World) -> None:
    """Look up, send a reply, and record a case from the buttons on the page."""
    made = seed_help_request(
        client.settings, application_id="app_d05", question="OPS-QUESTION-4411"
    )
    choose(client.client)
    page = client.client.get("/ops/support").text
    assert "It cannot decide, issue, return or waive anything." in page
    assert "adm-support-layout" not in page
    assert 'data-testid="evidence-panel"' not in page
    assert "* Required" not in page
    closed(page, "support-record")
    closed(page, "support-faq")
    assert "The applicant can read this reply." in page
    assert 'data-testid="help-destination"' in page

    looked = client.client.get("/ops/support?ref=SYN-APP-005").text
    assert 'data-testid="support-lookup-result"' in looked
    assert 'data-testid="support-status"' in looked

    post_action(
        client.client,
        "support.help_request.answer",
        {
            "help_request_id": made["request_id"],
            "expected_version": str(made["version"]),
            "reply": "A reviewer opens it next.",
        },
        "/ops/support",
    )
    answered = client.client.get("/ops/support?request_status=answered").text
    assert "A reviewer opens it next." in answered

    post_action(
        client.client,
        "support.case.record",
        {"expected_version": "0", "reference": "", "channel": "counter", "summary": "Asked about a fence."},
        "/ops/support",
    )
    recorded = client.client.get("/ops/support").text
    assert "Asked about a fence." in recorded


def test_reason_codes_keep_the_decision_and_hide_the_add_form(client: _World) -> None:
    """The label, type, state and Retire stay. The code and the add form close."""
    choose(client.client)
    page = client.client.get("/admin?tab=reason-codes").text
    assert "Existing records keep this code." in page
    assert 'data-testid="admin-reason-code-retire"' in page
    # The register keeps four columns; the code and the description are detail.
    register = page.split('data-testid="admin-reason-codes"', 1)[1].split("</table>", 1)[0]
    assert "<th scope=\"col\">Technical code</th>" not in register
    assert register.count("<th scope=\"col\">") == 4
    closed(page, "admin-reason-codes-more")
    closed(page, "admin-add-reason-code-disclosure")
    detail = open_disclosure(page, "admin-reason-codes-more")
    assert "Technical code" in detail
    assert "The case repeats a record the City already holds." in detail
    add = page.index('data-testid="admin-add-reason-code"')
    details = page.rfind("<details", 0, add)
    assert details != -1 and "open" not in page[details:details + 120]

    post_action(
        client.client,
        "config.reason_code.add",
        {
            "action_id": "config.reason_code.add",
            "code": "DEMO_NOTE",
            "label": "Demo note",
            "description": "A code added from the screen",
            "code_type": "return",
        },
        "/admin?tab=reason-codes",
    )
    added = client.client.get("/admin?tab=reason-codes").text
    assert "Demo note" in added
    post_action(
        client.client,
        "config.reason_code.retire",
        {
            "action_id": "config.reason_code.retire",
            "code": "DEMO_NOTE",
        },
        "/admin?tab=reason-codes",
    )
    retired = client.client.get("/admin?tab=reason-codes").text
    assert 'data-code="DEMO_NOTE"' in retired
    row = retired.split('data-code="DEMO_NOTE"', 1)[1].split("</tr>", 1)[0]
    assert "Retired" in row


def test_rules_keep_the_diff_and_drop_the_panel(client: _World) -> None:
    """The register and the diff stay. The rest of the version is closed."""
    choose(client.client)
    rules = client.client.get("/rules?tab=rules&view=published").text
    assert 'data-testid="evidence-panel"' not in rules
    assert "Fictional ACME rules and fees" not in rules
    assert "what-if" not in rules
    assert "append-only" not in rules
    assert 'data-testid="approval-policy"' in rules
    assert "Approval policy:" in rules
    assert 'data-testid="rule-table"' in rules
    assert 'data-testid="rule-next-action"' in rules
    closed(rules, "rules-responsibility")
    closed(rules, "rules-approvers")
    closed(rules, "rules-draft")
    selected = client.client.get(
        "/rules?tab=rules&view=published&version=rulever_CT-1_v1"
    ).text
    assert 'data-testid="selected-version-diff"' in selected or (
        'data-testid="selected-version-diff-empty"' in selected
    )
    assert 'data-testid="selected-version-reason"' in selected
    closed(selected, "rules-version-more")
    assert "What changed" in selected.split('data-testid="rules-version-more"', 1)[0]
    # The versions of the register keep their approver behind the disclosure.
    assert 'data-testid="rule-approvers-table"' in rules


@pytest.fixture()
def client(tmp_path: Path) -> _World:
    """A demonstration database of its own, so a test leaves no trace."""
    settings = build_environment(tmp_path, synthetic=False, name="ops-screens.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield _World(test_client, settings)

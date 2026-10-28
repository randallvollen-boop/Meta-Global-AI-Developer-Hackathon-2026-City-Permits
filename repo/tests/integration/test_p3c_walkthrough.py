"""A scripted persona walkthrough: the simulator never decides a case's fate.

Random intake may produce high-priority records and records that will need a
return or a revision, but it never assigns ``returned`` or
``revisions_requested`` itself.  Only an authorized human action does, and the
terminal states then show on the dashboard of the City Administrator.
"""
# REQUIRES: PER-03, UX-01, AI-03

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from p3c_support import ADMIN, REVIEWER, STEWARD, build_settings, choose, post_action
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path):
    return build_settings(tmp_path)


@pytest.fixture()
def client(environment):
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def arrivals(environment):
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return [
                (row.id, row.source_application_number, row.status, row.priority, row.version)
                for row in session.execute(
                    select(permit.Application)
                    .where(permit.Application.scenario_id.is_(None))
                    .order_by(permit.Application.source_application_number)
                ).all()
                for row in [row[0]]
            ]
    finally:
        factory.dispose()


def figure(page: str, key: str) -> str:
    import re

    match = re.search(rf'data-figure="{key}".*?data-testid="ops-figure-value">([^<]*)<', page, re.S)
    assert match, key
    return match.group(1)


def test_the_simulator_never_assigns_the_human_only_statuses(client, environment) -> None:
    choose(client, ADMIN)
    assert post_action(client, "agent.toggle", {"agent_key": "intake", "mode": "awake", "expected_version": "1"}, page="/agent/intake").status_code == 200
    choose(client, STEWARD)
    assert post_action(client, "intake.simulate", {"scenario": "random", "count": "12"}, page="/agent/intake").status_code == 200
    assert {row[2] for row in arrivals(environment)} == {"submitted"}  # nothing is decided on arrival
    assert post_action(client, "agent.run.intake", {}, page="/agent/intake").status_code == 200
    cases = arrivals(environment)
    statuses = {row[2] for row in cases}
    assert not statuses & {"returned", "revisions_requested"}  # the agent routes; it never returns
    assert "needs_information" in statuses and "ready_for_review" in statuses
    assert any(row[3] == "high" for row in cases)  # random intake can state a high priority


def test_the_terminal_states_appear_only_after_human_actions(client, environment) -> None:
    choose(client, ADMIN)
    post_action(client, "agent.toggle", {"agent_key": "intake", "mode": "awake", "expected_version": "1"}, page="/agent/intake")
    choose(client, STEWARD)
    post_action(client, "intake.simulate", {"scenario": "random", "count": "12"}, page="/agent/intake")
    post_action(client, "agent.run.intake", {}, page="/agent/intake")
    cases = arrivals(environment)
    needs = next(row for row in cases if row[2] == "needs_information")
    ready = next(row for row in cases if row[2] == "ready_for_review")

    choose(client, ADMIN)
    before = client.get("/ops/dashboard").text
    active_before = int(figure(before, "active"))

    # The Data Steward returns one case: returned is terminal.
    choose(client, STEWARD)
    returned = post_action(client, "permit.case.return", {
        "application_id": needs[0], "reason_code": "INCOMPLETE_APPLICATION",
        "reason": "The site plan is missing.", "expected_version": str(needs[4])}, page="/agent/intake")
    assert returned.status_code == 200, returned.text
    again = post_action(client, "permit.case.advance", {"application_id": needs[0], "expected_version": str(needs[4] + 1)}, page="/agent/intake")
    assert again.status_code == 422  # a returned case is terminal

    # The Permit Reviewer asks for revisions on another case.
    choose(client, REVIEWER)
    revisions = post_action(client, "permit.case.request_revisions", {
        "application_id": ready[0], "reason_code": "REVISION_NEEDS_PLANS",
        "message": "The plans must show the setback.", "expected_version": str(ready[4])}, page="/agent/adjudication")
    assert revisions.status_code == 200, revisions.text

    after = {row[0]: row[2] for row in arrivals(environment)}
    assert after[needs[0]] == "returned" and after[ready[0]] == "revisions_requested"

    # The dashboard shows the new states honestly: a returned case leaves the Active set,
    # a case with revisions requested stays in it.
    choose(client, ADMIN)
    page = client.get("/ops/dashboard").text
    assert int(figure(page, "active")) == active_before - 1
    assert 'data-testid="chart-status-table"' in page and "Returned" in page and "Revisions requested" in page
    # And the checks still hold after the walkthrough.
    assert post_action(client, "ops.checks.run", {"expected_version": "0"}).status_code == 200
    results = client.get("/ops/checks").text
    assert 'data-status="fail"' not in results

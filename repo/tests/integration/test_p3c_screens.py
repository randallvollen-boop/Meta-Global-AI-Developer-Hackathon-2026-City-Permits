"""The four P3c screens of the City Administrator and their three governed writes."""
# REQUIRES: PER-04, SEC-01, SEC-03, UX-01

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from p3c_support import (
    ADMIN, APPLICANT, REVIEWER, STEWARD, build_settings, choose, post_action, seed_help_request, token,
)
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.ids import new_id
from acme_city.persistence.models import audit, help as help_models, permit
from acme_city.persistence.models.support import SupportCase
from acme_city.persistence.session import SessionFactory, transaction
from acme_city.ui.router import router as ui_router

SCREENS = ("/ops/dashboard", "/ops/audit", "/ops/support", "/ops/checks")


@pytest.fixture()
def environment(tmp_path):
    return build_settings(tmp_path)


@pytest.fixture()
def client(environment):
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def events(environment, action: str):
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return session.execute(select(audit.AuditEvent).where(audit.AuditEvent.action == action)).scalars().all()
    finally:
        factory.dispose()


def rows(environment, model, *where):
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            statement = select(model)
            for clause in where:
                statement = statement.where(clause)
            return session.execute(statement).scalars().all()
    finally:
        factory.dispose()


# ------------------------------------------------------------------ access


@pytest.mark.parametrize("path", SCREENS)
def test_only_the_city_administrator_opens_the_operations_screens(client, path) -> None:
    anonymous = client.get(path, follow_redirects=False)
    assert anonymous.status_code == 303 and anonymous.headers["location"] == "/select"
    for actor in (APPLICANT, STEWARD, REVIEWER):
        choose(client, actor)
        assert client.get(path).status_code == 403, (actor, path)
    choose(client, ADMIN)
    assert client.get(path).status_code == 200


def test_the_navigation_lists_the_operations_screens_for_the_administrator_only(client) -> None:
    wanted = ["ops_dashboard", "ops_audit", "ops_support", "ops_checks"]
    for actor, listed in ((ADMIN, True), (STEWARD, False), (REVIEWER, False), (APPLICANT, False)):
        choose(client, actor)
        keys = re.findall(r'data-screen-key="([^"]+)"', client.get("/queue", follow_redirects=True).text)
        assert all((key in keys) is listed for key in wanted), actor
        if listed:
            assert keys[-4:] == wanted


def test_the_screens_are_read_only(client) -> None:
    choose(client, ADMIN)
    for path in SCREENS:
        assert client.post(path).status_code in {403, 404, 405}, path
        assert client.put(path).status_code in {403, 404, 405}, path


def test_every_screen_has_a_help_button_and_prints_its_definitions(client) -> None:
    choose(client, ADMIN)
    for path in SCREENS:
        assert 'data-testid="ui-help"' in client.get(path).text, path
    dash = client.get("/ops/dashboard").text
    for key in ("active", "average_age", "early_incomplete", "agent_processed", "decisions", "needs_a_person"):
        assert f'data-figure="{key}"' in dash
    assert "Mean of now minus the original submission time" in dash
    for testid in ("chart-status", "chart-channel", "chart-backlog"):
        assert f'data-testid="{testid}-section"' in dash


def test_the_dashboard_groups_the_figures_and_names_the_scope(client) -> None:
    choose(client, ADMIN)
    dash = client.get("/ops/dashboard").text
    # The scope of the numbers is named before the figures.
    assert "Fictional demo records. Sample history excluded." in dash
    assert dash.index("Sample history excluded.") < dash.index('data-figure="active"')
    # The figures sit in two groups: the work that is open now and the work
    # the services recorded.
    assert "Current workload" in dash
    assert "Recorded processing" in dash
    assert 'data-testid="ops-figure-group" data-group="workload"' in dash
    assert 'data-testid="ops-figure-group" data-group="processing"' in dash
    # The plain labels of the figures are on the screen.
    for label in (
        "Active cases",
        "Average age of active cases",
        "Items needing attention",
        "Incomplete at first intake",
        "Applications processed by intake",
        "Decisions recorded",
    ):
        assert label in dash, label
    # The items that need attention name their two components.
    assert "Applications in needs information" in dash
    assert "Recommendations held for a person" in dash


def test_the_dashboard_scope_follows_the_history_switch(client) -> None:
    choose(client, ADMIN)
    included = client.get("/ops/dashboard?synthetic=include").text
    assert "Sample history included." in included
    excluded = client.get("/ops/dashboard").text
    assert "Sample history excluded." in excluded


def test_the_dashboard_breakdowns_keep_their_charts_and_their_tables(client) -> None:
    choose(client, ADMIN)
    dash = client.get("/ops/dashboard").text
    # Every breakdown with rows keeps its chart and its table in the page.
    for testid in ("chart-status", "chart-channel"):
        assert f'data-testid="{testid}-chart"' in dash, testid
        assert f'data-testid="{testid}-data"' in dash, testid
        assert f'data-testid="{testid}-table"' in dash, testid
    # The breakdown without rows says so instead of drawing an empty chart.
    assert 'data-testid="chart-backlog-empty"' in dash
    # The table of a breakdown keeps its rows and its total.
    assert "Total" in dash
    assert dash.count('class="ops-chart"') >= 2


# --------------------------------------------------------------- audit log


def test_the_audit_log_filters_and_links(client, environment) -> None:
    choose(client, ADMIN)
    post_action(client, "ops.checks.run", {"expected_version": "0"})
    body = client.get("/ops/audit").text
    assert 'data-testid="audit-row"' in body
    only_checks = client.get("/ops/audit?action=checks.run").text
    assert only_checks.count('data-testid="audit-row"') == 1
    assert 'data-testid="audit-record-link"' in only_checks  # checks_run has a page
    assert "/ops/checks?run=checkrun_" in only_checks
    persons = client.get("/ops/audit?actor_type=person").text
    assert 'data-actor-type="agent"' not in persons
    nothing = client.get("/ops/audit?search=zzzz-not-there").text
    assert 'data-testid="audit-empty"' in nothing


def test_the_event_detail_opens_in_the_drawer_for_the_administrator_only(client, environment) -> None:
    choose(client, ADMIN)
    post_action(client, "ops.checks.run", {"expected_version": "0"})
    event_id = events(environment, "checks.run")[0].id
    page = client.get(f"/ops/audit?action=checks.run&detail=audit-event:{event_id}").text
    assert 'data-testid="ui-drawer-title"' in page and "Audit event" in page
    choose(client, STEWARD)
    assert client.get(f"/detail/audit-event/{event_id}").status_code == 403


# ------------------------------------------------------------------ checks


def test_run_checks_records_one_canonical_event_and_shows_the_result(client, environment) -> None:
    choose(client, ADMIN)
    before = len(events(environment, "ui.ops.checks.run"))
    response = post_action(client, "ops.checks.run", {"expected_version": "0"})
    assert response.status_code == 200 and response.json()["status"] == "accepted"
    assert len(events(environment, "checks.run")) == 1  # the canonical event
    assert len(events(environment, "ui.ops.checks.run")) == before + 1  # the dispatcher's own feedback event
    page = client.get("/ops/checks").text
    assert page.count('data-testid="check-row"') == 8
    assert 'data-testid="check-status">Not applicable<' in page
    assert "not applicable (historical seed)" in page


def test_run_checks_refusals(client, environment) -> None:
    choose(client, STEWARD)
    # without the grant (and the screen is closed to the persona)
    assert post_action(client, "ops.checks.run", {"expected_version": "0"}, page="/queue").status_code == 403
    choose(client, ADMIN)
    # without the CSRF token
    assert post_action(client, "ops.checks.run", {"expected_version": "0"}, csrf="forged").status_code == 403
    # without an expected version
    assert post_action(client, "ops.checks.run", {}).status_code == 422
    # with a stale one
    assert post_action(client, "ops.checks.run", {"expected_version": "0"}).status_code == 200
    assert post_action(client, "ops.checks.run", {"expected_version": "0"}).status_code == 422
    assert len(events(environment, "checks.run")) == 1


def test_the_checks_screen_leads_with_the_recorded_result(client) -> None:
    choose(client, ADMIN)
    post_action(client, "ops.checks.run", {"expected_version": "0"})
    page = client.get("/ops/checks").text
    # The screen says what the checks do before it offers the action.
    assert "Check the stored records for consistency." in page
    assert "permits or fees." in page
    # The recorded result comes before the results themselves.
    assert page.index('data-testid="checks-result"') < page.index('data-testid="checks-counts"')
    assert page.index('data-testid="checks-counts"') < page.index('data-testid="checks-table"')
    assert page.index('data-testid="checks-table"') < page.index('data-testid="checks-details"')
    # The three counts are named.
    for label in ("Passed", "Failed", "Not applicable"):
        assert label in page, label
    # The technical identifier sits in the run details.
    assert 'data-testid="checks-run-id"' in page
    assert page.count('data-testid="check-row"') == 8
    # The run is recorded, and the screen says so without counting the rows.
    assert "is recorded in the audit log" in page


def test_the_checks_screen_keeps_the_reason_of_every_result(client) -> None:
    choose(client, ADMIN)
    post_action(client, "ops.checks.run", {"expected_version": "0"})
    page = client.get("/ops/checks").text
    assert page.count('data-testid="check-reason"') == 8
    assert "not applicable (historical seed)" in page
    # The reason of a check is never shortened to a count.
    assert "not applicable (historical seed)" in page.split('data-testid="check-row"', 1)[1]


def test_a_run_changes_no_business_row(client, environment) -> None:
    def snapshot():
        factory = SessionFactory(environment.database_url)
        try:
            with factory() as session:
                return tuple(
                    session.execute(select(func.count()).select_from(model)).scalar_one()
                    for model in (permit.Application, permit.Decision, permit.Permit, permit.ApplicationComment)
                )
        finally:
            factory.dispose()

    choose(client, ADMIN)
    before = snapshot()
    post_action(client, "ops.checks.run", {"expected_version": "0"})
    assert snapshot() == before


# ----------------------------------------------------------------- support


def test_lookup_shows_status_timeline_and_applicant_visible_comments_only(client, environment) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            for body, visibility in (("Please add the site plan.", "applicant"), ("INTERNAL-NOTE-9931 staff only", "internal")):
                session.add(
                    permit.ApplicationComment(
                        id=new_id("comment"), correlation_id=new_id("corr"), application_id="app_d05",
                        body=body, visibility=visibility, author_actor_id=REVIEWER, version=1,
                    )
                )
    finally:
        factory.dispose()
    choose(client, ADMIN)
    page = client.get("/ops/support?ref=SYN-APP-005").text
    assert 'data-testid="support-lookup-result"' in page
    assert "Please add the site plan." in page
    assert "INTERNAL-NOTE-9931" not in page
    assert 'data-testid="support-timeline"' in page
    missing = client.get("/ops/support?ref=NO-SUCH-REF").text
    assert 'data-testid="support-lookup-none"' in missing


def test_the_support_screen_has_the_faq_and_the_fictional_contact_notice(client) -> None:
    choose(client, ADMIN)
    page = client.get("/ops/support").text
    assert 'data-testid="support-faq"' in page and "fictional" in page
    assert 'data-testid="support-emergency"' in page


def test_record_assistance_with_and_without_a_reference(client, environment) -> None:
    choose(client, ADMIN)
    ok = post_action(client, "support.case.record", {
        "expected_version": "0", "reference": "SYN-APP-005", "channel": "phone", "summary": "Explained the setback rule."}, page="/ops/support")
    assert ok.status_code == 200, ok.text
    none = post_action(client, "support.case.record", {
        "expected_version": "0", "reference": "", "channel": "counter", "summary": "A visitor asked about fees."}, page="/ops/support")
    assert none.status_code == 200
    saved = rows(environment, SupportCase)
    assert len(saved) == 2 and sorted((r.reference or "") for r in saved) == ["", "SYN-APP-005"]
    assert [r.application_id for r in saved if r.reference] == ["app_d05"]
    listed = client.get("/ops/support").text
    assert listed.count('data-testid="support-case-row"') == 2 and "Recent support cases" in listed
    for event in events(environment, "support.case.record"):
        assert "setback" not in str(event.metadata_json) + str(event.reason)  # the summary is never audited


def test_record_assistance_refusals(client, environment) -> None:
    good = {"expected_version": "0", "reference": "", "channel": "phone", "summary": "ok"}
    choose(client, REVIEWER)
    assert post_action(client, "support.case.record", good, page="/queue").status_code == 403
    choose(client, ADMIN)
    assert post_action(client, "support.case.record", good, csrf="forged", page="/ops/support").status_code == 403
    assert post_action(client, "support.case.record", {**good, "expected_version": ""}, page="/ops/support").status_code == 422
    assert post_action(client, "support.case.record", {**good, "expected_version": "3"}, page="/ops/support").status_code == 422
    assert post_action(client, "support.case.record", {**good, "channel": "smoke"}, page="/ops/support").status_code == 422
    assert post_action(client, "support.case.record", {**good, "summary": " "}, page="/ops/support").status_code == 422
    assert post_action(client, "support.case.record", {**good, "reference": "NOPE-1"}, page="/ops/support").status_code == 422
    assert rows(environment, SupportCase) == []


def test_answering_a_help_request_writes_the_reply_status_and_comment_together(client, environment) -> None:
    made = seed_help_request(environment, application_id="app_d05", question="When will my review start?")
    choose(client, ADMIN)
    page = client.get(f"/ops/support?request={made['request_id']}").text
    assert "When will my review start?" in page and 'data-testid="help-answer-form"' in page
    response = post_action(client, "support.help_request.answer", {
        "help_request_id": made["request_id"], "expected_version": "1", "reply": "A reviewer opens it within the service target."},
        page="/ops/support")
    assert response.status_code == 200, response.text
    (request,) = rows(environment, help_models.HelpRequest)
    assert request.status == "answered" and request.version == 2
    assert request.reply == "A reviewer opens it within the service target." and request.answered_by_actor_id == ADMIN
    comments = rows(environment, permit.ApplicationComment, permit.ApplicationComment.application_id == "app_d05")
    visible = [c for c in comments if c.visibility == "applicant" and c.body == request.reply]
    assert len(visible) == 1 and visible[0].author_actor_id == ADMIN
    (event,) = events(environment, "support.help_request.answer")
    assert request.reply not in str(event.metadata_json) + str(event.reason) + str(event.references)
    assert event.metadata_json["replied_on"] == "request_and_comment"
    # the applicant reads it on the tracking page
    choose(client, APPLICANT)
    assert request.reply in client.get("/apply/track?ref=SYN-APP-005").text


def test_a_reply_without_a_case_stays_on_the_help_request(client, environment) -> None:
    made = seed_help_request(environment, application_id=None)
    choose(client, ADMIN)
    before = len(rows(environment, permit.ApplicationComment))
    assert post_action(client, "support.help_request.answer", {
        "help_request_id": made["request_id"], "expected_version": "1", "reply": "Call the desk."}, page="/ops/support").status_code == 200
    assert len(rows(environment, permit.ApplicationComment)) == before
    assert events(environment, "support.help_request.answer")[0].metadata_json["replied_on"] == "request_only"


def test_a_reply_on_an_archived_case_does_not_touch_the_application(client, environment) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(permit.Application, "app_d05")
            row.status_before_archive = row.status
            row.status = "archived"
            row.archived_at = datetime(2026, 10, 27, tzinfo=UTC)
            version, status = row.version, row.status
    finally:
        factory.dispose()
    made = seed_help_request(environment, application_id="app_d05")
    choose(client, ADMIN)
    assert "This reply stays on the help request. The archived case will not change." in client.get("/ops/support").text
    before = len(rows(environment, permit.ApplicationComment))
    assert post_action(client, "support.help_request.answer", {
        "help_request_id": made["request_id"], "expected_version": "1", "reply": "We will restore it."}, page="/ops/support").status_code == 200
    assert len(rows(environment, permit.ApplicationComment)) == before
    (application,) = rows(environment, permit.Application, permit.Application.id == "app_d05")
    assert (application.version, application.status) == (version, status)
    (request,) = rows(environment, help_models.HelpRequest)
    assert request.status == "answered" and request.reply == "We will restore it."


def test_answer_refusals(client, environment) -> None:
    made = seed_help_request(environment, application_id="app_d05")
    good = {"help_request_id": made["request_id"], "expected_version": "1", "reply": "Fine."}
    for actor in (APPLICANT, STEWARD, REVIEWER):
        choose(client, actor)
        assert post_action(client, "support.help_request.answer", good, page="/queue" if actor != APPLICANT else "/apply").status_code in {403}, actor
    choose(client, ADMIN)
    assert post_action(client, "support.help_request.answer", good, csrf="forged", page="/ops/support").status_code == 403
    assert post_action(client, "support.help_request.answer", {**good, "expected_version": ""}, page="/ops/support").status_code == 422
    assert post_action(client, "support.help_request.answer", {**good, "expected_version": "7"}, page="/ops/support").status_code == 422
    assert post_action(client, "support.help_request.answer", {**good, "reply": "  "}, page="/ops/support").status_code == 422
    assert post_action(client, "support.help_request.answer", {**good, "help_request_id": "helpreq_nope"}, page="/ops/support").status_code == 404
    (request,) = rows(environment, help_models.HelpRequest)
    assert request.status == "open" and request.reply is None
    assert rows(environment, permit.ApplicationComment) == []
    assert post_action(client, "support.help_request.answer", good, page="/ops/support").status_code == 200
    # a request is answered once
    assert post_action(client, "support.help_request.answer", {**good, "expected_version": "2"}, page="/ops/support").status_code == 422


def test_the_administrator_gains_no_decision_power(client, environment) -> None:
    def counts():
        factory = SessionFactory(environment.database_url)
        try:
            with factory() as session:
                return tuple(
                    session.execute(select(func.count()).select_from(model)).scalar_one()
                    for model in (permit.Decision, permit.Permit, permit.ApplicationAction, permit.ApplicationFinding)
                )
        finally:
            factory.dispose()

    choose(client, ADMIN)
    before = counts()
    for action in ("permit.decide", "permit.issue", "permit.case.return", "permit.finding.waive", "permit.case.advance"):
        response = post_action(client, action, {"application_id": "app_d05", "expected_application_version": "1", "expected_version": "1"}, page="/ops/support")
        assert response.status_code != 200, action
    assert counts() == before

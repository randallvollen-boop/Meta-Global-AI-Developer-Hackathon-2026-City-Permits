"""The Permit Reviewer screens: queue views, case workspace and their labels.

These tests read the rendered pages the reviewer sees.  They check real
counts, recognisable rows, plain-word labels, the workspace tabs, the
separation of AI suggestions from checks, task-named actions, document and
revision views, and that internal notes stay labelled internal.
"""
# REQUIRES: UX-01, UX-02, SEC-01

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import model_run, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.router import router as permit_router
from acme_city.ui import view_models
from acme_city.ui.router import router as ui_router

REVIEWER = "persona_permit_reviewer"
CASE = "app_synth_001"


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'reviewer-ui.db'}",
            "ACME_SECRET_KEY": "reviewer-ui-test-secret-value",
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


@pytest.fixture()
def factory(environment: Settings):
    made = SessionFactory(environment.database_url)
    yield made
    made.dispose()


def actor_for(session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def choose(client: TestClient, actor_id: str) -> None:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match
    return match.group(1)


def row_for(page: str, reference: str) -> str:
    rows = re.findall(r'<tr class="row" data-testid="queue-item".*?</tr>', page, re.S)
    return next(row for row in rows if f">{reference}<" in row)


# ------------------------------------------------------------------ queue


def test_queue_views_show_real_counts_and_only_states_that_exist(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/queue?view=all").text
    views = dict(re.findall(r'data-view="(\w+)".*?data-testid="queue-view-count">(\d+)', page, re.S))
    rows = re.findall(r'data-testid="queue-item"[^>]*data-bucket="(\w+)"', page)
    assert int(views["all"]) == len(rows) == 13
    for key in ("checks", "data", "applicant", "issued"):
        counted = rows.count(key)
        if counted:
            assert int(views[key]) == counted, key
        else:
            assert key not in views, f"{key} has no cases and must not be offered"
    assert views == {"data": "12", "issued": "1", "all": "13"}
    # The old metric cards are gone.
    for gone in ("queue-kpis", "Change cases", "Blocked</div>"):
        assert gone not in page


def test_a_queue_view_filters_to_its_cases(client: TestClient) -> None:
    choose(client, REVIEWER)
    issued = client.get("/queue?view=all&focus=issued").text
    assert issued.count('data-testid="queue-item"') == 1
    assert ">SYN-APP-007<" in issued
    data = client.get("/queue?view=all&focus=data").text
    assert data.count('data-testid="queue-item"') == 12
    assert ">SYN-APP-007<" not in data


def test_a_row_is_recognisable(client: TestClient) -> None:
    choose(client, REVIEWER)
    row = row_for(client.get("/queue?view=all").text, "SYN-APP-001")
    title = text_of(re.search(r'data-testid="queue-row-title">(.*?)</div>', row, re.S).group(1))
    assert title == (
        "SYN-APP-001 · Commercial tenant improvement · Cedarline Coffee Roasters LLC "
        "· 400 Lantern Row, Unit 2"
    )
    assert "party_cedarline" not in text_of(row)


def test_stage_issue_next_party_and_action_are_plain_words(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/queue?view=all").text
    row = row_for(page, "SYN-APP-001")
    assert "Submitted" in text_of(re.search(r'data-testid="queue-item-state">(.*?)</span>', row, re.S).group(1))
    assert "Identity needs confirmation" in text_of(re.search(r'data-testid="queue-issue">(.*?)</td>', row, re.S).group(1))
    assert "identity_link_unapproved" not in text_of(row)
    nxt = text_of(re.search(r'data-testid="queue-next-party">(.*?)</td>', row, re.S).group(1))
    assert "Permit review team" in nxt and "Waiting on steward" not in nxt
    assert text_of(re.search(r'data-testid="queue-action"[^>]*>(.*?)</a>', row, re.S).group(1)) == "Open application"
    assert "Property address needs confirmation" in text_of(row_for(page, "SYN-APP-004"))
    assert "Resolve identity link unapproved" not in page


def test_waiting_on_steward_appears_only_once_routed(client: TestClient) -> None:
    choose(client, REVIEWER)
    cells = re.findall(r'data-testid="queue-next-party">(.*?)</td>', client.get("/queue?view=all").text, re.S)
    assert cells and not any("Waiting on steward" in cell for cell in cells)
    token = csrf(client, f"/permits/{CASE}")
    sent = client.post(
        "/ui/actions/change.request",
        data={
            "csrf_token": token,
            "action_id": "change.request",
            "next": f"/permits/{CASE}",
            "target_type": "application",
            "target_id": CASE,
            "change_kind": "factual",
            "title": "Confirm the identity link",
            "reason": "The applicant link has not been approved.",
        },
        follow_redirects=False,
    )
    assert sent.status_code in (200, 303), sent.text[:300]
    row = row_for(client.get("/queue?view=all").text, "SYN-APP-001")
    assert "Waiting on steward" in text_of(row)
    assert "View referred issue" in text_of(row)


def test_dates_show_a_target_only_where_one_applies(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/queue?view=all").text
    assert "Submitted 2026-09-08" in text_of(row_for(page, "SYN-APP-001"))
    assert "Waiting since" in text_of(row_for(page, "SYN-APP-001"))
    assert 'data-testid="queue-target"' in row_for(page, "SYN-APP-001")
    issued = row_for(page, "SYN-APP-007")
    assert 'data-testid="queue-target"' not in issued
    assert 'data-testid="queue-age-note"' in page


def test_the_scope_is_labelled_for_what_it_is(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/queue").text
    assert "Permit review team" in page
    assert "Assigned to me" not in page, "no case carries an owner in the seed"


# --------------------------------------------------------------- workspace


def test_the_workspace_has_four_tabs_and_opens_on_review(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    tabs = re.findall(r'data-testid="workspace-tab" data-tab="(\w+)"[^>]*aria-selected="(\w+)"|aria-selected="(\w+)"', page)
    labels = [
        text_of(m)
        for m in re.findall(r'<button type="button" role="tab".*?>(.*?)</button>', page, re.S)
    ]
    assert [re.sub(r"\s*\d+$", "", label) for label in labels] == [
        "Review", "Documents", "People and organizations", "Activity",
    ]
    assert re.search(r'id="tab-review"[^>]*aria-selected="true"', page)
    assert re.search(r'id="tab-documents"[^>]*aria-selected="false"', page)
    documents = client.get(f"/permits/{CASE}?tab=documents").text
    assert re.search(r'id="tab-documents"[^>]*aria-selected="true"', documents)
    assert tabs


def test_the_case_header_reads_for_a_person(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    head = text_of(re.search(r'data-testid="case-header".*?</div>\s*</div>', page, re.S).group(0))
    assert "Commercial tenant improvement" in head
    assert "400 Lantern Row, Unit 2" in head
    assert "SYN-APP-001 · Cedarline Coffee Roasters LLC · Revision" in head
    assert "Back to the review queue" in head
    assert 'href="/queue/review"' in page
    visible = text_of(re.search(r'data-testid="case-header".*?</div>\s*</div>', page, re.S).group(0))
    assert "app_synth_001" not in visible and "com_ti" not in visible
    detail = client.get(f"/permits/{CASE}?detail=case-tech:{CASE}").text
    assert "app_synth_001" in detail and "com_ti" in detail


def test_empty_future_stages_are_one_line_and_expand_with_content(
    client: TestClient, factory
) -> None:
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    line = text_of(re.search(r'data-testid="empty-stages">(.*?)</p>', page, re.S).group(1))
    assert line == "Decision: Not recorded · Fee: Not assessed · Permit: Not issued"
    assert 'data-testid="stage-fee"' not in page and 'data-testid="stage-permit"' not in page
    with transaction(factory) as session:
        session.add(
            permit.Decision(
                id="decision_reviewer_ui",
                application_id=CASE,
                outcome="approved",
                decided_by_actor_id=REVIEWER,
                decided_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
                reason="Meets the checks.",
                status="current",
                conditions=["Inspection before opening"],
            )
        )
    page = client.get(f"/permits/{CASE}").text
    assert "Decision: Not recorded" not in page
    summary = text_of(re.search(r'data-testid="decision-summary">(.*?)</dl>', page, re.S).group(1))
    for part in ("Outcome", "Decided by", "Date", "Revision", "Reason", "Internal record", "Conditions", "Inspection before opening"):
        assert part in summary
    issued = client.get("/permits/app_d07").text
    assert 'data-testid="stage-permit"' in issued and 'data-testid="empty-stages"' not in issued


def test_reconfirm_is_offered_only_after_a_decision(client: TestClient, factory) -> None:
    choose(client, REVIEWER)
    assert 'data-action-id="permit.reconfirm"' not in client.get(f"/permits/{CASE}").text
    with transaction(factory) as session:
        session.add(
            permit.Decision(
                id="decision_reviewer_ui_2",
                application_id=CASE,
                outcome="approved",
                decided_by_actor_id=REVIEWER,
                decided_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
                status="current",
            )
        )
    after = client.get(f"/permits/{CASE}").text
    assert re.search(r'data-action-id="permit.reconfirm" data-permitted="true"', after)


def test_actions_name_the_task(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    assert "Open form" not in page
    for label in ("Run application checks", "Record review decision", "Correct the application record", "Request source correction"):
        assert label in text_of(page), label
    for old in ("Run validation", "Record reviewer decision", "Submit application correction"):
        assert old not in page, old


def test_a_state_guard_does_not_blame_a_grant_the_persona_holds(client: TestClient, factory) -> None:
    """The reviewer holds permit.decide: reconfirm is refused for state only."""
    with factory() as session:
        actor = actor_for(session, REVIEWER)
        actions = view_models.allowed_actions_for(session, actor, "permit", CASE)
    reconfirm = next(item for item in actions if item["action_id"] == "permit.reconfirm")
    assert reconfirm["permitted"] is False
    assert "no decision to reconfirm" in reconfirm["reason"]
    assert "does not hold" not in reconfirm["reason"]
    issue = next(item for item in actions if item["action_id"] == "permit.issue")
    assert issue["permitted"] is False
    assert "current approved decision is required" in issue["reason"]
    assert "does not hold" not in issue["reason"], "the reviewer holds permit.issue"
    with factory() as session:
        admin_actions = view_models.allowed_actions_for(
            session, actor_for(session, "persona_city_administrator"), "permit", CASE
        )
    denied = next(item for item in admin_actions if item["action_id"] == "permit.decide")
    assert "does not hold the 'permit.decide' grant" in denied["reason"]


def test_the_extraction_is_kept_apart_from_the_application_checks(
    client: TestClient, factory
) -> None:
    with transaction(factory) as session:
        session.add(
            permit.Document(
                id="doc_reviewer_ui",
                application_id=CASE,
                document_type="site_plan",
                version=1,
                file_ref="fixtures/none.pdf",
                content_hash="cd34" * 16,
                received_at=datetime(2026, 9, 8, 14, 31, tzinfo=UTC),
                uploaded_by_actor_id="persona_data_steward",
            )
        )
        session.add(
            model_run.ModelRun(
                id="run_reviewer_ui",
                correlation_id="corr_reviewer_ui",
                mode="replay",
                provider="meta",
                model="muse-spark-test",
                prompt_version="extraction-prompt-v1",
                schema_version="extraction-schema-v1",
                input_refs={"application_id": CASE, "documents": [{"document_id": "doc_reviewer_ui", "version": 1, "content_hash": "cd34" * 16, "document_type": "site_plan"}]},
                output={},
                validation_result={"checked": ["fields_present"], "issues": []},
                usage={"input_tokens": 10, "output_tokens": 5},
                latency_ms=100,
                started_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                completed_at=datetime(2026, 10, 1, 12, 0, 1, tzinfo=UTC),
                actor_id="persona_data_steward",
            )
        )
        session.flush()
        for name, value, state in (("setback", "12 ft", "proposed"), ("height", "9 ft", "accepted")):
            session.add(
                permit.ExtractionObservation(
                    id=f"obs_{name}",
                    document_id="doc_reviewer_ui",
                    document_version=1,
                    field_path=name,
                    proposed_value=value,
                    page_region="p1 r2",
                    model_run_id="run_reviewer_ui",
                    validation_state=state,
                )
            )
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    flat = text_of(page)
    assert "Extraction checks" in flat and "Application checks" in flat
    assert "Validation" not in re.findall(r'<div class="h">[^<]*', page).__str__()
    summary = text_of(re.search(r'data-testid="ai-summary">(.*?)</p>', page, re.S).group(1))
    assert "2 suggested fields" in summary
    assert "1 confirmed, 1 for steward review" in summary
    assert "Recorded replay" in summary
    assert "Run details" in summary
    assert 'data-testid="ai-not-review"' in page
    fields = re.findall(r'data-testid="suggested-field" data-confirmed="(\w+)"', page)
    assert sorted(fields) == ["false", "true"]
    assert "Suggested field" in flat and "Confirmed value" in flat
    # The Muse label and a one-click way into the run stay on screen.
    assert 'data-testid="muse-mode"' in page
    assert "detail=muse-run:run_reviewer_ui" in page or 'data-detail-id="run_reviewer_ui"' in page


def test_documents_show_name_version_received_view_and_history(
    client: TestClient, factory
) -> None:
    with transaction(factory) as session:
        session.add(
            permit.Document(
                id="doc_reviewer_ui_2",
                application_id=CASE,
                document_type="floor_plan",
                version=1,
                file_ref="fixtures/none.pdf",
                content_hash="ef56" * 16,
                received_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
                uploaded_by_actor_id="persona_data_steward",
            )
        )
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    table = re.search(r'data-testid="document-table".*?</table>', page, re.S).group(0)
    assert [text_of(h) for h in re.findall(r"<th scope=\"col\">(.*?)</th>", table)] == ["Name", "Version", "Received", "View"]
    assert "ef56" not in table and "persona_data_steward" not in table
    history = client.get(f"/permits/{CASE}?detail=doc-history:doc_reviewer_ui_2").text
    assert "ef56" * 16 in history and "Content hash" in history and "Uploaded by" in history


def test_revisions_show_what_changed_and_keep_both_addresses(
    client: TestClient, factory
) -> None:
    with transaction(factory) as session:
        first = session.query(permit.ApplicationRevision).filter_by(application_id=CASE).one()
        session.add(
            permit.ApplicationRevision(
                id="rev_reviewer_ui_2",
                application_id=CASE,
                revision_number=first.revision_number + 1,
                submitted_at=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
                snapshot={**dict(first.snapshot or {}), "valuation_cents": 999},
            )
        )
        number = first.revision_number + 1
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}?tab=documents").text
    rows = re.findall(r'data-testid="revision-row" data-current="(\w+)"', page)
    assert rows == ["true", "false"], "newest first, only one current"
    flat = text_of(page)
    assert "Earlier revision: superseded" in flat and "Current revision" in flat
    assert "needs re-review" in flat
    assert "Changed: valuation_cents" in flat
    both = text_of(re.search(r'data-testid="address-both">(.*?)</p>', page, re.S).group(1))
    assert "Suite 2" in both and "Unit 2" in both
    diff = client.get(f"/permits/{CASE}?detail=revision:{CASE}:{number}").text
    assert "valuation_cents" in diff and "Changed since the previous revision" in diff


def test_an_issued_case_keeps_issuance_and_follow_up_apart(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/permits/app_d07").text
    assert 'data-testid="issue-follow-up"' in page
    outstanding = re.search(r'data-testid="outstanding-issues"', page)
    assert outstanding is None, "an issued permit has no outstanding issues, only follow-up"
    follow = text_of(re.search(r'data-testid="issue-follow-up">(.*?)</div>\s*</section>', page, re.S).group(1))
    assert "Identity needs confirmation" in follow
    assert "stays issued" in follow
    assert 'data-testid="issuance-status"' in page and "Issued" in text_of(page)


# ------------------------------------------------------------------ privacy


def test_internal_notes_are_labelled_internal(client: TestClient) -> None:
    choose(client, REVIEWER)
    token = csrf(client, f"/permits/{CASE}")
    version = re.search(r'name="expected_version" value="(\d+)"', client.get(f"/permits/{CASE}").text).group(1)
    for body, visibility in (("INTERNAL-ONLY-MARKER", "internal"), ("APPLICANT-SEES-THIS", "applicant")):
        response = client.post(
            "/ui/actions/permit.case.comment",
            data={"csrf_token": token, "action_id": "permit.case.comment", "next": f"/permits/{CASE}", "application_id": CASE, "expected_version": version, "body": body, "visibility": visibility},
            follow_redirects=False,
        )
        assert response.status_code in (200, 303), response.text[:300]
        version = re.search(r'name="expected_version" value="(\d+)"', client.get(f"/permits/{CASE}").text).group(1)
    page = client.get(f"/permits/{CASE}?tab=activity").text
    rows = re.findall(r'<li data-testid="comment-row" data-visibility="(\w+)">(.*?)</li>', page, re.S)
    by_visibility = {vis: text_of(body) for vis, body in rows}
    assert "Internal note (City staff only)" in by_visibility["internal"]
    assert "INTERNAL-ONLY-MARKER" in by_visibility["internal"]
    assert "Visible to the applicant" in by_visibility["applicant"]
    assert "Internal note" not in by_visibility["applicant"]


def test_an_applicant_cannot_read_staff_details(client: TestClient) -> None:
    choose(client, "persona_applicant")
    for kind, item in (("case-tech", CASE), ("revision", f"{CASE}:1"), ("doc-history", "doc_x")):
        response = client.get(f"/detail/{kind}/{item}")
        assert response.status_code in (403, 404), (kind, response.status_code)
        for leak in ("app_synth_001", "com_ti", "party_cedarline", "Content hash"):
            assert leak not in response.text


def test_controls_and_messages_agree_on_the_decision_grant(client: TestClient) -> None:
    """The reviewer is offered the decision and no message says the grant is missing."""
    choose(client, REVIEWER)
    page = client.get(f"/permits/{CASE}").text
    assert re.search(r'data-testid="decision-form"|data-action-id="permit.decide" data-permitted="true"', page)
    assert "does not hold the &#39;permit.decide&#39; grant" not in page
    assert "does not hold the &#39;permit.issue&#39; grant" not in page
    choose(client, "persona_city_administrator")
    admin = client.get(f"/permits/{CASE}").text
    assert 'data-action-id="permit.decide" data-permitted="false"' in admin
    assert "does not hold the &#39;permit.decide&#39; grant" in admin

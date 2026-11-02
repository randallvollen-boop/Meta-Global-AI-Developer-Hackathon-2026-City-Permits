"""The Data Steward fixes a recorded data issue by hand.

Every kind of recorded issue the City raises offers at least one manual
action on its page.  An issue about an unknown field authority offers to
approve the pending source link, and every kind offers to close the issue with
a reason code and a note.  Each action shows a preview of what will change,
and closing an issue writes an audit event in the name of the steward.  The
page says in plain words what the issue means and keeps the technical
identifiers under "More details".

Fictional ACME City data only.
"""
# REQUIRES: UX-01, GOV-05, PER-04

from __future__ import annotations

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
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import audit, change, registry, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui import steward_views
from acme_city.ui.router import router as ui_router

STEWARD = "persona_data_steward"
AUTHORITY_SUBJECT = "party_cedarline:contractor_registration_status"

#: Every kind of issue the City raises, with the plain words its page shows.
KINDS: dict[str, tuple[str, str]] = {
    "unresolved_field_authority": (
        AUTHORITY_SUBJECT,
        "contractor registration status comes from a source nobody has approved yet",
    ),
    "late_source_version": ("party_cedarline:postal_address", "older version"),
    "source_version_payload_conflict": ("party_cedarline:contact_email", "Two versions of the same business record"),
    "unregistered_dataset": ("party_cedarline:contact_phone", "dataset the City has not registered"),
    # An issue a person escalated by hand carries any kind the person named.
    "disputed_by_applicant": ("party_cedarline:preferred_contact", "applicant disputes it"),
}


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'issue-actions.db'}",
            "ACME_SECRET_KEY": "issue-actions-secret-value",
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
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def raise_issues(environment: Settings) -> dict[str, str]:
    """Record one open issue of every kind and return their identifiers."""
    ids: dict[str, str] = {}
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            for number, (kind, (subject, _words)) in enumerate(KINDS.items()):
                issue = change.GovernanceIssue(
                    id=f"issue_test_{number}",
                    subject_type="canonical_entity",
                    subject_id=subject,
                    issue_type=kind,
                    description=(
                        "A person escalated this record because the applicant disputes it."
                        if kind == "disputed_by_applicant"
                        else f"the {kind} of {subject!r} is recorded"
                    ),
                    responsible_queue_id=None,
                    assigned_actor_id=STEWARD,
                    blocking=True,
                    status="open",
                )
                session.add(issue)
                ids[kind] = issue.id
    finally:
        factory.dispose()
    return ids


def propose_authority_link(environment: Settings, *, with_value: bool = True) -> str:
    """Add the pending link of the contractor register, and what it sent."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            link = registry.Crosswalk(
                id="crosswalk_test_contractor",
                entity_id="party_cedarline",
                entity_type="party",
                source_system_id="permitting",
                source_dataset_key="contractor_register",
                source_record_id="CR-2026-00188",
                link_status="proposed",
            )
            session.add(link)
            if with_value:
                session.add(
                    source.SourceSnapshot(
                        source_snapshot_id="snapshot_test_contractor",
                        correlation_id="corr_test_contractor",
                        source_system_id="permitting",
                        source_dataset_id="contractor_register",
                        source_record_id="CR-2026-00188",
                        source_record_version="1",
                        ingested_at=datetime.now(UTC),
                        payload_hash="0" * 64,
                        raw_payload={"status": "active"},
                        record_status="accepted",
                    )
                )
            return link.id
    finally:
        factory.dispose()


def page(client: TestClient, issue_id: str) -> str:
    response = client.get(f"/steward/issues/issue/{issue_id}")
    assert response.status_code == 200, response.text
    return response.text


def csrf(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match
    return match.group(1)


def post(client: TestClient, path_back: str, action: str, fields: dict[str, str]):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client.get(path_back).text), "next": path_back, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def stored_issue(environment: Settings, issue_id: str) -> change.GovernanceIssue:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(change.GovernanceIssue, issue_id)
            session.expunge(row)
            return row
    finally:
        factory.dispose()


def events(environment: Settings, action: str) -> list[audit.AuditEvent]:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(audit.AuditEvent)
                    .where(audit.AuditEvent.action == action)
                    .order_by(audit.AuditEvent.occurred_at)
                ).scalars()
            )
    finally:
        factory.dispose()


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_kind_of_issue_offers_an_action_with_a_preview(
    client: TestClient, environment: Settings, kind: str
) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    body = page(client, ids[kind])
    assert 'data-testid="no-actions"' not in body
    assert "No action is open for this issue." not in body
    blocks = re.findall(r'data-testid="action-preview-block"', body)
    assert blocks, kind
    assert "If you choose" in body
    assert "Close with a reason" in body
    assert 'name="reason_code"' in body and 'name="note"' in body


def test_the_page_says_what_the_issue_means_in_plain_words(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    for kind, (subject, words) in KINDS.items():
        body = page(client, ids[kind])
        problem = re.search(r'data-testid="case-q1".*?</section>', body, re.S).group(0)
        visible = re.sub(r"<details.*?</details>", "", problem, flags=re.S)
        assert "party_cedarline" not in visible, kind
        assert subject.partition(":")[2] not in visible, kind
        if words:
            assert words in visible, (kind, visible)
        # The technical identifier stays one click away.
        technical = re.search(r'data-testid="case-technical".*?</details>', problem, re.S)
        assert technical is not None and subject in technical.group(0), kind
    authority = page(client, ids["unresolved_field_authority"])
    assert (
        "contractor registration status comes from a source nobody has approved yet, "
        "so the City cannot say which value is right."
    ) in authority
    assert "Cedarline" in authority


def test_the_queue_names_the_record_not_the_internal_identifier(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    queue = client.get("/steward?filter=needs_review").text
    main = re.search(r'<main id="main">(.*?)</main>', queue, re.S).group(1)
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style|svg).*?</\1>", "", main, flags=re.S))
    assert f"/steward/issues/issue/{ids['unresolved_field_authority']}" in queue
    assert "contractor registration status comes from a source nobody has approved yet" in visible
    assert "party_cedarline:contractor_registration_status" not in visible


def test_closing_the_authority_issue_with_a_reason_closes_and_audits_it(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    issue_id = ids["unresolved_field_authority"]
    path = f"/steward/issues/issue/{issue_id}"
    response = post(
        client,
        path,
        "governance.issue.resolve",
        {
            "issue_id": issue_id,
            "expected_version": "1",
            "outcome": "not_applicable",
            "reason_code": "accepted_as_is",
            "note": "Cedarline holds no contractor registration; nothing to own.",
        },
    )
    assert response.status_code == 200, response.text
    assert stored_issue(environment, issue_id).status == "not_applicable"
    recorded = events(environment, "governance.issue.resolve")
    assert len(recorded) == 1
    assert recorded[0].actor_id == STEWARD
    assert recorded[0].target_id == issue_id
    assert recorded[0].metadata_json["reason_code"] == "accepted_as_is"
    assert recorded[0].metadata_json["outcome"] == "not_applicable"
    assert "nothing to own" in (recorded[0].reason or "")
    closed = page(client, issue_id)
    assert "No action is open" in closed or "no action is open" in closed
    assert "Accepted as it stands" in closed
    assert "Data Steward" in closed
    # The closed issue leaves the list of what needs review.
    queue = client.get("/steward?filter=needs_review").text
    assert f"/steward/issues/issue/{issue_id}" not in queue


def test_a_reason_and_a_note_are_required(client: TestClient, environment: Settings) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    issue_id = ids["late_source_version"]
    path = f"/steward/issues/issue/{issue_id}"
    for fields in (
        {"outcome": "resolved", "reason_code": "accepted_as_is", "note": "  "},
        {"outcome": "resolved", "reason_code": "", "note": "A note."},
        {"outcome": "gone", "reason_code": "accepted_as_is", "note": "A note."},
    ):
        response = post(
            client,
            path,
            "governance.issue.resolve",
            {"issue_id": issue_id, "expected_version": "1", **fields},
        )
        assert response.status_code == 422, (fields, response.text)
    assert stored_issue(environment, issue_id).status == "open"
    assert events(environment, "governance.issue.resolve") == []


def test_a_persona_without_the_grant_cannot_close_an_issue(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    issue_id = ids["late_source_version"]
    choose(client, "persona_permit_reviewer")
    response = post(
        client,
        "/queue/intake",
        "governance.issue.resolve",
        {
            "issue_id": issue_id,
            "expected_version": "1",
            "outcome": "resolved",
            "reason_code": "accepted_as_is",
            "note": "Not my issue.",
        },
    )
    assert response.status_code == 403, response.text
    assert stored_issue(environment, issue_id).status == "open"


def test_a_closed_issue_cannot_be_closed_twice(client: TestClient, environment: Settings) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    issue_id = ids["late_source_version"]
    fields = {
        "issue_id": issue_id,
        "expected_version": "1",
        "outcome": "resolved",
        "reason_code": "accepted_as_is",
        "note": "The accepted version stands.",
    }
    path = f"/steward/issues/issue/{issue_id}"
    assert post(client, path, "governance.issue.resolve", fields).status_code == 200
    assert post(client, path, "governance.issue.resolve", fields).status_code == 409
    assert len(events(environment, "governance.issue.resolve")) == 1


def test_the_pending_source_link_is_approved_from_the_issue_and_closes_it(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    link_id = propose_authority_link(environment)
    choose(client, STEWARD)
    issue_id = ids["unresolved_field_authority"]
    path = f"/steward/issues/issue/{issue_id}"
    body = page(client, issue_id)
    assert "Approve the link to" in body
    assert link_id in body
    # The preview comes before the button.
    assert body.index("If you choose “Approve the link to") < body.index('name="crosswalk_id"')
    response = post(
        client,
        path,
        "governance.issue.approve_link",
        {
            "issue_id": issue_id,
            "crosswalk_id": link_id,
            "entity_id": "party_cedarline",
            "source_system_id": "permitting",
            "dataset_key": "contractor_register",
            "source_record_id": "CR-2026-00188",
            "expected_version": "1",
            "reason": "The contractor register is the owner of this field.",
        },
    )
    assert response.status_code == 200, response.text
    assert stored_issue(environment, issue_id).status == "resolved"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert session.get(registry.Crosswalk, link_id).link_status == "approved"
    finally:
        factory.dispose()
    recorded = events(environment, "governance.issue.resolve")
    assert [event.actor_id for event in recorded] == [STEWARD]
    assert recorded[0].metadata_json["reason_code"] == "link_approved"


def test_without_a_pending_link_only_the_close_action_is_offered(
    client: TestClient, environment: Settings
) -> None:
    ids = raise_issues(environment)
    choose(client, STEWARD)
    body = page(client, ids["unresolved_field_authority"])
    assert "Approve the link to" not in body
    assert "Close with a reason" in body


def test_every_kind_the_steward_may_be_assigned_has_a_plain_sentence_or_the_recorded_words() -> None:
    from acme_city.registry.steward_assist import ISSUE_CLASSES

    assert set(ISSUE_CLASSES) <= set(steward_views.ISSUE_PLAIN_WORDS)
    assert set(ISSUE_CLASSES) <= set(steward_views.ISSUE_CLOSE_PREVIEW)


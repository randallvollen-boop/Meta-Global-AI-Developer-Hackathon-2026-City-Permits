"""The new record actions of parity phase 3a, through the dispatcher.

Every new action is a governed action: it checks the grant, the CSRF token
of the session and a mandatory expected version, and it writes an audit
record.  The browser never decides who may act.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'lifecycle.db'}",
            "ACME_SECRET_KEY": "lifecycle-action-test-secret-value",
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
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str) -> str:
    """Return the CSRF token of the session, from a screen the persona may open."""
    for candidate in (
        path,
        "/agent/intake",
        "/agent/adjudication",
        "/admin?tab=reason-codes",
        "/apply/deck_fence",
        "/apply",
    ):
        match = re.search(
            r'name="csrf_token" value="([^"]+)"', client.get(candidate).text
        )
        if match:
            return match.group(1)
    raise AssertionError(f"no CSRF token on {path}")


def post(
    client: TestClient,
    action_id: str,
    fields: dict,
    next_path: str,
    *,
    csrf: str | None = None,
    token_path: str | None = None,
) -> dict:
    """Post one action and return the JSON answer."""
    source = token_path or next_path
    data = {
        "csrf_token": token(client, source) if csrf is None else csrf,
        "action_id": action_id,
        "next": next_path,
        **fields,
    }
    response = client.post(
        f"/ui/actions/{action_id}",
        data=data,
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    return response.json()


def case_row(environment, application_id: str) -> dict:
    """Return the stored state of one application."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, application_id)
            assert row is not None
            return {
                "status": row.status,
                "version": row.version,
                "priority": row.priority,
                "owner_actor_id": row.owner_actor_id or "",
            }
    finally:
        factory.dispose()


#: Every new record action of phase 3a, with the persona that holds its
#: grant, the persona that does not, the state the case needs and the
#: fields the action posts.
NEW_ACTIONS: tuple[dict, ...] = (
    {
        "action_id": "permit.case.return",
        "holder": "persona_data_steward",
        "refused": "persona_permit_reviewer",
        "status": "needs_information",
        "fields": {"reason_code": "INCOMPLETE_APPLICATION"},
    },
    {
        "action_id": "permit.case.advance",
        "holder": "persona_data_steward",
        "refused": "persona_permit_reviewer",
        "status": "needs_information",
        "fields": {},
    },
    {
        "action_id": "permit.case.request_revisions",
        "holder": "persona_permit_reviewer",
        "refused": "persona_data_steward",
        "status": "ready_for_review",
        "fields": {
            "reason_code": "REVISION_NEEDS_PLANS",
            "message": "The plans must show the setback.",
        },
    },
    {
        "action_id": "permit.case.archive",
        "holder": "persona_city_administrator",
        "refused": "persona_data_steward",
        "status": "submitted",
        "fields": {"reason_code": "ARCHIVE_DUPLICATE_RECORD"},
    },
    {
        "action_id": "permit.case.restore",
        "holder": "persona_city_administrator",
        "refused": "persona_data_steward",
        "status": "archived",
        "fields": {},
    },
    {
        "action_id": "permit.case.priority",
        "holder": "persona_data_steward",
        "refused": "persona_permit_reviewer",
        "status": "submitted",
        "fields": {"priority": "high"},
    },
    {
        "action_id": "permit.case.assign",
        "holder": "persona_data_steward",
        "refused": "persona_city_administrator",
        "status": "submitted",
        "fields": {"owner_actor_id": "persona_data_steward"},
    },
    {
        "action_id": "permit.case.comment",
        "holder": "persona_data_steward",
        "refused": "persona_applicant",
        "status": "submitted",
        "fields": {"body": "A note.", "visibility": "internal"},
    },
    {
        "action_id": "permit.finding.waive",
        "holder": "persona_data_steward",
        "refused": "persona_permit_reviewer",
        "status": "needs_information",
        "fields": {
            "reason_code": "WAIVE_VERIFIED_DUPLICATE",
            "reason": "A person confirmed the duplicate.",
        },
    },
)


def prepare_case(environment, *, status: str) -> tuple[str, int, str]:
    """Put the seeded case in the state an action needs and return its identity."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.get(permit.Application, "app_synth_001")
            application.status = status
            version = application.version
            finding_id = ""
            if status == "needs_information":
                finding = permit.ApplicationFinding(
                    id="finding_permission_1",
                    correlation_id="corr_permission",
                    application_id=application.id,
                    finding_type="duplicate",
                    message="A person must confirm the duplicate.",
                    rule="ACME Code §13-401",
                    applicant_must="Confirm the duplicate.",
                    severity="review",
                    state="current",
                    revision_number=application.revision,
                    version=1,
                )
                session.add(finding)
                session.flush()
                finding_id = finding.id
        return application.id, version, finding_id
    finally:
        factory.dispose()


@pytest.mark.parametrize("action_spec", NEW_ACTIONS, ids=lambda spec: spec["action_id"])
def test_every_new_action_is_refused_without_the_grant(
    client: TestClient, environment, action_spec: dict
) -> None:
    application_id, version, finding_id = prepare_case(
        environment, status=action_spec["status"]
    )
    fields = {
        "application_id": application_id,
        **action_spec["fields"],
    }
    if action_spec["action_id"] == "permit.finding.waive":
        fields["finding_id"] = finding_id
    choose(client, action_spec["refused"])
    result = post(
        client,
        action_spec["action_id"],
        {**fields, "expected_version": str(version)},
        "/queue",
    )
    assert result["status"] == "denied", result
    assert result["code"] == "permission_denied", result


@pytest.mark.parametrize("action_spec", NEW_ACTIONS, ids=lambda spec: spec["action_id"])
def test_every_new_action_is_refused_without_the_csrf_token(
    client: TestClient, environment, action_spec: dict
) -> None:
    application_id, version, finding_id = prepare_case(
        environment, status=action_spec["status"]
    )
    fields = {
        "application_id": application_id,
        **action_spec["fields"],
    }
    if action_spec["action_id"] == "permit.finding.waive":
        fields["finding_id"] = finding_id
    choose(client, action_spec["holder"])
    result = post(
        client,
        action_spec["action_id"],
        {**fields, "expected_version": str(version)},
        "/queue",
        csrf="not-the-session-token",
    )
    assert result["code"] == "permission_denied", result
    assert "token" in result["message"], result


@pytest.mark.parametrize("action_spec", NEW_ACTIONS, ids=lambda spec: spec["action_id"])
def test_every_new_action_is_refused_without_an_expected_version(
    client: TestClient, environment, action_spec: dict
) -> None:
    application_id, _version, finding_id = prepare_case(
        environment, status=action_spec["status"]
    )
    fields = {
        "application_id": application_id,
        **action_spec["fields"],
    }
    if action_spec["action_id"] == "permit.finding.waive":
        fields["finding_id"] = finding_id
    choose(client, action_spec["holder"])
    result = post(
        client,
        action_spec["action_id"],
        fields,
        "/queue",
    )
    assert result["status"] == "denied", result
    assert "expected version" in result["message"], result


@pytest.mark.parametrize("action_spec", NEW_ACTIONS, ids=lambda spec: spec["action_id"])
def test_every_new_action_is_refused_with_a_stale_expected_version(
    client: TestClient, environment, action_spec: dict
) -> None:
    application_id, version, finding_id = prepare_case(
        environment, status=action_spec["status"]
    )
    fields = {
        "application_id": application_id,
        **action_spec["fields"],
    }
    if action_spec["action_id"] == "permit.finding.waive":
        fields["finding_id"] = finding_id
    choose(client, action_spec["holder"])
    result = post(
        client,
        action_spec["action_id"],
        {**fields, "expected_version": str(version + 9)},
        "/queue",
    )
    assert result["status"] == "denied", result
    assert "changed since it was read" in result["message"], result


def set_status(environment, application_id: str, status: str) -> None:
    """Put one application in a status, as a fixture would."""
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.get(permit.Application, application_id).status = status
    finally:
        factory.dispose()


def application_version(environment, application_id: str) -> int:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, application_id)
            assert row is not None
            return row.version
    finally:
        factory.dispose()


def test_a_return_is_refused_without_the_grant(client: TestClient, environment) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_permit_reviewer")
    result = post(
        client,
        "permit.case.return",
        {
            "application_id": "app_synth_001",
            "reason_code": "INCOMPLETE_APPLICATION",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "denied", result
    assert result["code"] == "permission_denied", result


def test_a_return_is_refused_without_the_csrf_token(client: TestClient, environment) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.return",
        {
            "application_id": "app_synth_001",
            "reason_code": "INCOMPLETE_APPLICATION",
            "expected_version": str(version),
        },
        "/queue",
        csrf="not-the-session-token",
    )
    # The CSRF check runs before the action, so the answer is the plain
    # error envelope of the application.
    assert result["code"] == "permission_denied", result
    assert "token" in result["message"], result


def test_a_return_is_refused_without_an_expected_version(
    client: TestClient, environment
) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.return",
        {
            "application_id": "app_synth_001",
            "reason_code": "INCOMPLETE_APPLICATION",
        },
        "/queue",
    )
    assert result["status"] == "denied", result
    assert "expected version" in result["message"], result


def test_a_return_is_refused_with_a_stale_expected_version(
    client: TestClient, environment
) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.return",
        {
            "application_id": "app_synth_001",
            "reason_code": "INCOMPLETE_APPLICATION",
            "expected_version": str(version + 7),
        },
        "/queue",
    )
    assert result["status"] == "denied", result
    assert "changed since it was read" in result["message"], result


def test_a_steward_returns_a_case_through_the_dispatcher(
    client: TestClient, environment
) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.return",
        {
            "application_id": "app_synth_001",
            "reason_code": "INCOMPLETE_APPLICATION",
            "reason": "The site plan is missing.",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "accepted", result
    assert case_row(environment, "app_synth_001")["status"] == "returned"
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "application.return"
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].actor_id == "persona_data_steward"
    finally:
        factory.dispose()


def test_a_reviewer_asks_for_revisions_through_the_dispatcher(
    client: TestClient, environment
) -> None:
    set_status(environment, "app_synth_001", "under_review")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_permit_reviewer")
    result = post(
        client,
        "permit.case.request_revisions",
        {
            "application_id": "app_synth_001",
            "reason_code": "REVISION_NEEDS_PLANS",
            "message": "The plans must show the setback.",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "accepted", result
    assert case_row(environment, "app_synth_001")["status"] == "revisions_requested"


def test_an_administrator_archives_and_restores_through_the_dispatcher(
    client: TestClient, environment
) -> None:
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_city_administrator")
    archived = post(
        client,
        "permit.case.archive",
        {
            "application_id": "app_synth_001",
            "reason_code": "ARCHIVE_DUPLICATE_RECORD",
            "reason": "The case repeats another record.",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert archived["status"] == "accepted", archived
    assert case_row(environment, "app_synth_001")["status"] == "archived"
    restored = post(
        client,
        "permit.case.restore",
        {
            "application_id": "app_synth_001",
            "expected_version": str(version + 1),
        },
        "/queue",
    )
    assert restored["status"] == "accepted", restored
    assert case_row(environment, "app_synth_001")["status"] == "submitted"


def test_a_steward_changes_the_priority_and_routes_the_case(
    client: TestClient, environment
) -> None:
    set_status(environment, "app_synth_001", "needs_information")
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.priority",
        {
            "application_id": "app_synth_001",
            "priority": "high",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "accepted", result
    row = case_row(environment, "app_synth_001")
    assert row["priority"] == "high"
    routed = post(
        client,
        "permit.case.assign",
        {
            "application_id": "app_synth_001",
            "owner_actor_id": "persona_data_steward",
            "expected_version": str(row["version"]),
        },
        "/queue",
    )
    assert routed["status"] == "accepted", routed
    assert case_row(environment, "app_synth_001")["owner_actor_id"] == "persona_data_steward"


def test_a_comment_is_written_through_the_dispatcher(client: TestClient, environment) -> None:
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.comment",
        {
            "application_id": "app_synth_001",
            "body": "An internal note about this case.",
            "visibility": "internal",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "accepted", result
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            comments = session.execute(
                select(permit.ApplicationComment).where(
                    permit.ApplicationComment.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(comments) == 1
            assert comments[0].visibility == "internal"
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "application.comment.add"
                )
            ).scalars().all()
            assert len(events) == 1
            assert "internal note" not in (events[0].reason or "")
    finally:
        factory.dispose()


def test_the_applicant_never_sees_an_internal_note(client: TestClient, environment) -> None:
    """The applicant reads no internal note on any surface."""
    version = application_version(environment, "app_d05")
    choose(client, "persona_data_steward")
    for body, visibility in (
        ("A message for the applicant.", "applicant"),
        ("An internal note about this case.", "internal"),
    ):
        result = post(
            client,
            "permit.case.comment",
            {
                "application_id": "app_d05",
                "body": body,
                "visibility": visibility,
                "expected_version": str(version),
            },
            "/queue",
        )
        assert result["status"] == "accepted", result
    choose(client, "persona_applicant")
    # The permit workspace of the applicant's own case.
    workspace = client.get("/permits/app_d05").text
    assert "A message for the applicant." in workspace
    assert "An internal note about this case." not in workspace
    # The portal tracker.
    tracker = client.get("/apply/track", params={"ref": "SYN-APP-005"}).text
    assert "Messages from the City" in tracker
    assert "A message for the applicant." in tracker
    assert "An internal note about this case." not in tracker
    # The API list.
    listed = client.get("/api/permits/applications/app_d05/comments").json()
    assert [row["visibility"] for row in listed["comments"]] == ["applicant"]
    # The identifier of an internal note is not a way to read it.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            internal = session.execute(
                select(permit.ApplicationComment).where(
                    permit.ApplicationComment.application_id == "app_d05",
                    permit.ApplicationComment.visibility == "internal",
                )
            ).scalars().one()
            internal_id = internal.id
    finally:
        factory.dispose()
    direct = client.get(f"/api/permits/comments/{internal_id}")
    assert direct.status_code == 404, direct.text


def test_a_comment_of_another_applicant_is_out_of_reach(
    client: TestClient, environment
) -> None:
    """A comment identifier of another applicant's case is refused."""
    version = application_version(environment, "app_synth_001")
    choose(client, "persona_data_steward")
    result = post(
        client,
        "permit.case.comment",
        {
            "application_id": "app_synth_001",
            "body": "A note on another applicant's case.",
            "visibility": "internal",
            "expected_version": str(version),
        },
        "/queue",
    )
    assert result["status"] == "accepted", result
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            comment = session.execute(
                select(permit.ApplicationComment).where(
                    permit.ApplicationComment.application_id == "app_synth_001"
                )
            ).scalars().one()
            comment_id = comment.id
    finally:
        factory.dispose()
    choose(client, "persona_applicant")
    direct = client.get(f"/api/permits/comments/{comment_id}")
    # The case of another applicant is outside the actor's record scope.
    assert direct.status_code in (403, 404), direct.text
    listed = client.get("/api/permits/applications/app_synth_001/comments")
    assert listed.status_code == 403, listed.text


def test_the_steward_reads_every_comment(client: TestClient, environment) -> None:
    """A member of the City reads the internal notes as well."""
    version = application_version(environment, "app_d05")
    choose(client, "persona_data_steward")
    for body, visibility in (
        ("A message for the applicant.", "applicant"),
        ("An internal note about this case.", "internal"),
    ):
        result = post(
            client,
            "permit.case.comment",
            {
                "application_id": "app_d05",
                "body": body,
                "visibility": visibility,
                "expected_version": str(version),
            },
            "/queue",
        )
        assert result["status"] == "accepted", result
    listed = client.get("/api/permits/applications/app_d05/comments").json()
    assert {row["visibility"] for row in listed["comments"]} == {"applicant", "internal"}
    workspace = client.get("/permits/app_d05").text
    assert "An internal note about this case." in workspace

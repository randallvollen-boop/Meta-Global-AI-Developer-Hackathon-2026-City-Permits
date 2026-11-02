"""Check my application, the hold, and the override a reviewer and intake read."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from acme_city.agents.control import AgentControlService
from acme_city.agents.intake import IntakeAgent
from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient
from acme_city.muse.schemas import PRESUBMIT_FEEDBACK_SCHEMA_VERSION
from acme_city.permits.queues import early_resolution
from acme_city.persistence.models import audit, gis, model_run, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


FENCE_FIELDS = {
    "applicant_name": "Demo Applicant",
    "applicant_email": "demo.applicant@example.invalid",
    "applicant_phone": "555-0100",
    "address_text": "400 Lantren Row",
    "height_ft": "4",
    "fence_material": "cedar",
    "location": "side_rear",
    "setback_ft": "2",
    "property_line_ack": "on",
    "project_description": "4 ft cedar side fence",
}

FRONT_SIX = {**FENCE_FIELDS, "height_ft": "6", "location": "front", "project_description": "6 ft front fence"}

#: An address the city locator cannot place.  The applicant may type one.
MADE_UP = {**FENCE_FIELDS, "address_text": "12 Imaginary Lane"}
MADE_UP_FRONT_SIX = {**FRONT_SIX, "address_text": "12 Imaginary Lane"}


def fence_files():
    return {
        "file__site_plan": ("sketch.txt", b"Site sketch of the fence line.\n", "text/plain"),
        "file__material_spec": ("spec.txt", b"Cedar panels.\n", "text/plain"),
    }


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("acme_city.applicant_portal.service.DOCUMENT_ROOT", tmp_path / "documents")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'presubmit.db'}",
            "ACME_SECRET_KEY": "presubmit-portal-test-secret",
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


def token(client: TestClient, path: str = "/apply/deck_fence") -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post_form(client, fields, files=None, intent="update", override_reason=None):
    data = {
        "csrf_token": token(client),
        "intent": intent,
        "certification_accepted": "on",
        **fields,
    }
    if override_reason is not None:
        data["override_reason"] = override_reason
    return client.post("/apply/deck_fence", data=data, files=files, follow_redirects=False)


def application_count(settings: Settings) -> int:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return int(
                session.execute(select(func.count()).select_from(permit.Application)).scalar_one()
            )
    finally:
        factory.dispose()


def context_for(session, actor_id: str) -> ActorContext:
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record_id for grant in grants for record_id in grant.record_scope),
    )


class FakeTransport(httpx.BaseTransport):
    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"id": "resp_presubmit", "status": "completed", "output_text": self.body},
        )


def test_a_legal_fence_still_submits_and_records_no_override(client, environment) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, FENCE_FIELDS, files=fence_files(), intent="submit")
    assert response.status_code == 303, response.text
    reference = response.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            assert application.presubmit_override is None
            assert application.status == "submitted"
    finally:
        factory.dispose()


def test_a_six_foot_front_fence_is_held_until_the_applicant_says_why(client, environment) -> None:
    choose(client, "persona_applicant")
    before = application_count(environment)
    missing = post_form(client, FRONT_SIX, files=fence_files(), intent="submit")
    assert missing.status_code == 422, missing.text
    assert application_count(environment) == before
    submit = re.search(r'<button[^>]*data-testid="submit-application"[^>]*>', missing.text)
    assert submit is not None and "disabled" in submit.group(0)
    assert "Fix the items under Must fix, or use Submit anyway." in missing.text
    assert "The assistant is offline." not in missing.text
    must_fix = missing.text.split('data-testid="must-fix"')[1].split("</section>")[0]
    assert "ACME Code §14-305" in must_fix
    assert "Use 4 or less." in must_fix

    blank = post_form(client, FRONT_SIX, files=fence_files(), intent="override", override_reason="   ")
    assert blank.status_code == 422, blank.text
    assert "Enter why submit now." in blank.text
    # The refused page leaves the button usable.  A script may disable it
    # until a reason is typed; the markup itself must not.
    anyway = re.search(r'<button[^>]*data-testid="submit-anyway"[^>]*>', blank.text)
    assert anyway is not None and "disabled" not in anyway.group(0)
    assert 'aria-describedby="submit-anyway-why"' in anyway.group(0)
    assert 'data-server-held="true"' in blank.text
    assert application_count(environment) == before

    reason = "The fence is already built."
    accepted = post_form(
        client, FRONT_SIX, files=fence_files(), intent="override", override_reason=reason
    )
    assert accepted.status_code == 303, accepted.text
    reference = accepted.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            assert application.presubmit_override["reason"] == reason
            assert application.presubmit_override["flag"] == "Submitted with known issues"
            assert "presubmit_override" not in (application.submitted_facts or {})
            actions = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.target_id == application.id,
                    audit.AuditEvent.action == "application.presubmit_override",
                )
            ).scalars().all()
            assert len(actions) == 1
            assert actions[0].reason == reason
    finally:
        factory.dispose()

    choose(client, "persona_permit_reviewer")
    workspace = client.get(f"/permits/{application_id}")
    assert workspace.status_code == 200, workspace.text
    assert 'data-testid="presubmit-flag"' in workspace.text
    flag = workspace.text.split('data-testid="presubmit-flag"')[1].split("</p>")[0]
    assert "Submitted with known issues" in flag
    said = workspace.text.split('data-testid="presubmit-reason"')[1].split("</p>")[0]
    assert f"The applicant said: {reason}" in said

    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            operator = context_for(session, "persona_agent_operator")
            AgentControlService(session).set_mode("intake", "awake", operator)
            IntakeAgent(session, settings=environment).run(
                application_id, triggered_by="persona_data_steward"
            )
            application = session.get(permit.Application, application_id)
            assert application is not None
            assert application.status == "needs_information"
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id,
                    permit.ApplicationFinding.finding_type == "judgment",
                    permit.ApplicationFinding.severity == "block",
                )
            ).scalars().all()
            assert findings
            assert any(reason in finding.message and "Submitted with known issues" in finding.message for finding in findings)
            assert any(
                finding.applicant_must == "A person at the City reviews these known issues."
                for finding in findings
            )
            board = early_resolution(session, context_for(session, "persona_data_steward"))
            blob = json.dumps(board)
            assert reference in blob
            assert reason in blob
    finally:
        factory.dispose()


def test_an_address_the_city_cannot_match_still_submits(client, environment) -> None:
    """A made-up address never holds the application: it is filed as typed."""
    choose(client, "persona_applicant")
    before = application_count(environment)
    response = post_form(client, MADE_UP, files=fence_files(), intent="submit")
    assert response.status_code == 303, response.text
    reference = response.headers["location"].rsplit("/", 1)[1]
    assert application_count(environment) == before + 1
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            assert application.presubmit_override is None
            assert application.status == "submitted"
            facts = dict(application.submitted_facts or {})
            # The address is kept exactly as it was typed.
            assert facts["submitted_site_text"] == "12 Imaginary Lane"
            # The property is not matched: the City matches it after filing.
            assert facts["parcel_number"] == ""
            assert facts["submitted_parcel"] == ""
            site = session.execute(
                select(permit.ApplicationSite).where(
                    permit.ApplicationSite.application_id == application_id
                )
            ).scalar_one()
            assert site.submitted_address_text == "12 Imaginary Lane"
            assert site.resolution_status == "unresolved"
    finally:
        factory.dispose()


def test_the_city_matches_the_property_after_the_case_is_filed(client, environment) -> None:
    """The case lands unmatched and the steward sees it as an unmatched property."""
    choose(client, "persona_applicant")
    response = post_form(client, MADE_UP, files=fence_files(), intent="submit")
    assert response.status_code == 303, response.text
    reference = response.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            operator = context_for(session, "persona_agent_operator")
            AgentControlService(session).set_mode("intake", "awake", operator)
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            IntakeAgent(session, settings=environment).run(
                application_id, triggered_by="persona_data_steward"
            )
            application = session.get(permit.Application, application_id)
            assert application is not None
            assert application.status == "needs_information"
            match = session.execute(
                select(gis.ApplicationParcelMatch).where(
                    gis.ApplicationParcelMatch.application_id == application_id
                )
            ).scalar_one()
            assert match.link_state == "not_found"
            assert match.submitted_text == "12 Imaginary Lane"
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id,
                    permit.ApplicationFinding.finding_type == "conflict",
                )
            ).scalars().all()
            assert any("12 Imaginary Lane" in finding.message for finding in findings)
            board = early_resolution(session, context_for(session, "persona_data_steward"))
            blob = json.dumps(board)
            assert reference in blob
            assert "12 Imaginary Lane" in blob
    finally:
        factory.dispose()


def test_the_override_works_with_an_address_the_city_cannot_match(client, environment) -> None:
    """A real rule breach is still held and still overridden with a reason."""
    choose(client, "persona_applicant")
    before = application_count(environment)
    held = post_form(client, MADE_UP_FRONT_SIX, files=fence_files(), intent="submit")
    assert held.status_code == 422, held.text
    assert application_count(environment) == before
    must_fix = held.text.split('data-testid="must-fix"')[1].split("</section>")[0]
    assert "ACME Code §14-305" in must_fix
    # The address is not a Must fix: it is a note under Should check.
    assert "does not match a parcel" not in must_fix
    should_check = held.text.split('data-testid="should-check"')[1].split("</section>")[0]
    assert "We could not match this address to a parcel." in should_check

    reason = "The fence is already built."
    accepted = post_form(
        client, MADE_UP_FRONT_SIX, files=fence_files(), intent="override", override_reason=reason
    )
    assert accepted.status_code == 303, accepted.text
    reference = accepted.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            assert application.presubmit_override["reason"] == reason
            assert application.presubmit_override["flag"] == "Submitted with known issues"
            kinds = {issue["kind"] for issue in application.presubmit_override["issues"]}
            assert kinds == {"rule"}
            # The case waits for a person: the agent routes it to early resolution.
            operator = context_for(session, "persona_agent_operator")
            AgentControlService(session).set_mode("intake", "awake", operator)
            IntakeAgent(session, settings=environment).run(
                application_id, triggered_by="persona_data_steward"
            )
            application = session.get(permit.Application, application_id)
            assert application is not None
            assert application.status == "needs_information"
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application_id,
                    permit.ApplicationFinding.severity == "block",
                )
            ).scalars().all()
            assert any(
                "Submitted with known issues" in finding.message for finding in findings
            )
            board = early_resolution(session, context_for(session, "persona_data_steward"))
            blob = json.dumps(board)
            assert reference in blob
            assert reason in blob
    finally:
        factory.dispose()


def test_the_live_check_does_not_call_an_unmatched_address_missing(client) -> None:
    """The background check of the form never holds an address the City cannot place."""
    choose(client, "persona_applicant")
    body = client.post(
        "/apply/deck_fence/check",
        data={
            **MADE_UP,
            "have__site_plan": "1",
            "have__material_spec": "1",
            "certification_accepted": "on",
        },
    ).json()
    assert body["complete"] is True
    assert body["can_submit"] is True
    assert body["missing"] == [] and body["items"] == [] and body["blocking"] == []
    assert body["banner"] == "Ready to submit. All required fields and documents are provided."


def draft_reference(page: str) -> str:
    """Return the draft reference the form is holding."""
    match = re.search(r'name="draft" value="([^"]+)"', page)
    assert match and match.group(1), page
    return match.group(1)


def test_a_reload_check_counts_documents_kept_on_the_draft(client) -> None:
    """A check after a refused submit posts no files; the draft's copies count."""
    choose(client, "persona_applicant")
    held = post_form(client, MADE_UP_FRONT_SIX, files=fence_files(), intent="submit")
    assert held.status_code == 422, held.text
    reference = draft_reference(held.text)
    body = client.post(
        "/apply/deck_fence/check",
        data={
            **MADE_UP_FRONT_SIX,
            "draft": reference,
            "certification_accepted": "on",
            "review": "1",
        },
    ).json()
    assert body["can_submit"] is True, body
    assert body["missing"] == [] and body["blocking"] == []
    assert body["review"]["held"] is True
    assert body["review"]["must_fix"]


def test_a_reload_check_counts_ticks_kept_on_the_draft(client) -> None:
    """Ticks stored on the draft count when the check does not post them again."""
    choose(client, "persona_applicant")
    saved = post_form(
        client,
        {
            **MADE_UP,
            "sent_separately__site_plan": "on",
            "sent_separately__material_spec": "on",
        },
        intent="update",
    )
    assert saved.status_code == 200, saved.text
    reference = draft_reference(saved.text)
    body = client.post(
        "/apply/deck_fence/check",
        data={**MADE_UP, "draft": reference, "certification_accepted": "on", "review": "1"},
    ).json()
    assert body["can_submit"] is True, body
    assert body["missing"] == []
    assert body["sent_separately"] == ["material_spec", "site_plan"]
    assert body["review"]["held"] is False
    assert body["review"]["must_fix"] == []


def test_an_untick_posted_with_the_check_is_not_restored_from_the_draft(client) -> None:
    """A check that posts its ticks is believed, so unticking one is missing."""
    choose(client, "persona_applicant")
    saved = post_form(
        client,
        {
            **MADE_UP,
            "sent_separately__site_plan": "on",
            "sent_separately__material_spec": "on",
        },
        intent="update",
    )
    reference = draft_reference(saved.text)
    body = client.post(
        "/apply/deck_fence/check",
        data={
            **MADE_UP,
            "draft": reference,
            "certification_accepted": "on",
            "sent_separately_posted": "1",
            "sent_separately__site_plan": "on",
        },
    ).json()
    assert body["can_submit"] is False, body
    missing = [item.lower() for item in body["missing"]]
    assert any("material" in item for item in missing), missing
    assert all("site" not in item for item in missing), missing


def test_submit_anyway_posts_the_draft_without_sending_the_files_again(client) -> None:
    """The reload drops the files.  Submit anyway is a plain post of the draft."""
    choose(client, "persona_applicant")
    held = post_form(client, MADE_UP_FRONT_SIX, files=fence_files(), intent="submit")
    assert held.status_code == 422, held.text
    anyway = re.search(r'<button[^>]*data-testid="submit-anyway"[^>]*>', held.text)
    assert anyway is not None and "disabled" not in anyway.group(0)
    assert 'data-override-field hidden' not in held.text
    accepted = post_form(
        client,
        {**MADE_UP_FRONT_SIX, "draft": draft_reference(held.text)},
        intent="override",
        override_reason="The fence is already built.",
    )
    assert accepted.status_code == 303, accepted.text
    assert "/apply/submitted/" in accepted.headers["location"]


def test_the_live_check_answers_with_the_rules_while_a_review_is_on_screen(client) -> None:
    """The browser learns the current answer, so a hold it cannot lift is lifted."""
    choose(client, "persona_applicant")
    data = {
        **MADE_UP_FRONT_SIX,
        "have__site_plan": "1",
        "have__material_spec": "1",
        "certification_accepted": "on",
    }
    plain = client.post("/apply/deck_fence/check", data=data).json()
    assert "review" not in plain
    held = client.post("/apply/deck_fence/check", data={**data, "review": "1"}).json()
    assert held["review"]["held"] is True
    assert held["review"]["must_fix"]
    assert held["review"]["assistant"] == "rules"
    fixed = client.post(
        "/apply/deck_fence/check",
        data={**data, "height_ft": "4", "location": "side_rear", "review": "1"},
    ).json()
    assert fixed["review"]["must_fix"] == []
    assert fixed["review"]["held"] is False


def test_check_my_application_uses_the_rules_layer_when_muse_is_off(client, environment) -> None:
    choose(client, "persona_applicant")
    response = client.post(
        "/apply/deck_fence/review",
        data={**FRONT_SIX, "certification_accepted": "on", "intent": "review"},
        files=fence_files(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant"] == "offline"
    assert body["assistant_note"] == "The assistant is offline."
    assert body["held"] is True
    assert body["must_fix"]
    assert "ACME Code §14-305" in body["must_fix"][0]["sentence"]
    assert body["must_fix"][0]["feedback"] is None
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            runs = session.execute(
                select(model_run.ModelRun).where(
                    model_run.ModelRun.schema_version == PRESUBMIT_FEEDBACK_SCHEMA_VERSION
                )
            ).scalars().all()
            assert runs == []
    finally:
        factory.dispose()


def _feedback(rule_id: str, text: str) -> str:
    return json.dumps(
        {"items": [{"rule_id": rule_id, "text": text}], "cannot_review": False, "reason": ""}
    )


def test_muse_feedback_is_shown_only_when_it_cites_a_real_rule(environment) -> None:
    live = environment.model_copy(
        update={
            "presubmit_review_live_enabled": True,
            "meta_api_key": SecretStr("test-presubmit-key-not-real"),
        }
    )
    accepted = FakeTransport(_feedback("DF-1", "Lower the front fence to 4 ft."))
    invented = FakeTransport(_feedback("DF-99", "See ACME Code §99-999 for the new rule."))
    app = create_app(live)
    app.include_router(ui_router)
    app.state.presubmit_muse_client = MuseClient(live, transport=accepted)
    with TestClient(app) as test_client:
        choose(test_client, "persona_applicant")
        payload = {**FRONT_SIX, "certification_accepted": "on"}
        first = test_client.post("/apply/deck_fence/review", data=payload, files=fence_files())
        assert first.status_code == 200, first.text
        shown = first.json()
        assert shown["assistant"] == "live"
        assert shown["assistant_note"] == ""
        assert shown["must_fix"][0]["feedback"] == "Lower the front fence to 4 ft."
        assert shown["must_fix"][0]["sentence"]
        assert len(accepted.requests) == 1
        sent = accepted.requests[0].content.decode()
        assert "Site sketch of the fence line." in sent
        assert "Cedar panels." in sent
        assert "demo.applicant@example.invalid" not in sent
        assert "555-0100" not in sent
        app.state.presubmit_muse_client = MuseClient(live, transport=invented)
        second = test_client.post("/apply/deck_fence/review", data=payload, files=fence_files())
        assert second.status_code == 200, second.text
        refused = second.json()
        assert refused["assistant"] == "rejected"
        assert refused["assistant_note"] == "The assistant is offline."
        assert "invented_rule" in refused["validation_issues"]
        assert refused["must_fix"][0]["feedback"] is None
        assert "DF-99" not in second.text
        assert "99-999" not in second.text
        assert "ACME Code §14-305" in second.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            runs = session.execute(
                select(model_run.ModelRun).where(
                    model_run.ModelRun.schema_version == PRESUBMIT_FEEDBACK_SCHEMA_VERSION
                )
            ).scalars().all()
            assert len(runs) == 2
            outputs = [run.output for run in runs]
            assert any(item is not None for item in outputs)
            assert any(item is None for item in outputs)
            for run in runs:
                blob = json.dumps(run.output)
                assert "DF-99" not in blob
                assert "99-999" not in blob
    finally:
        factory.dispose()

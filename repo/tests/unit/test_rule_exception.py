"""A reviewer may approve against a failed rule only as a recorded exception.

A hard blocker still refuses the approval.  A denial does not need the
exception reason.  The case page says which rule the approval went against.
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
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.core.results import ConflictResult
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.decisions import PermitDecisionCommand, PermitDecisionService
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.ui.router import router as ui_router

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
REVIEWER = "persona_permit_reviewer"
TITLE = "Fence height, front yard"
STATEMENT = f"Approved as an exception to {TITLE}"
FENCE_FACTS = {
    "parcel_number": "ACME-P-1001",
    "project_description": "6 ft front-yard fence",
    "valuation": "1200.00",
    "height_ft": 6,
    "setback_ft": 2,
    "structure_kind": "fence",
    "location": "front",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'exception.db'}",
            "ACME_SECRET_KEY": "rule-exception-test-secret-value",
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


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
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
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def failing_fence(session) -> tuple[PermitService, ActorContext, str, int]:
    """Submit a 6 ft front-yard fence whose only blocker is the failed rule."""
    service = PermitService(session)
    steward = context_for(session, "persona_data_steward")
    reviewer = context_for(session, REVIEWER)
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="deck_fence",
            facts=dict(FENCE_FACTS),
            applicant_party_id="party_cedarline",
        ),
        steward,
    )
    session.add(
        registry.Crosswalk(
            id=f"crosswalk_{view.application_id}",
            entity_id="party_cedarline",
            entity_type="party",
            source_system_id="permitting",
            source_dataset_key="applicant_profiles",
            source_record_id="PER-party_cedarline",
            link_status="approved",
            decision="Approved by the data steward.",
            decision_actor_id="persona_data_steward",
            decided_at=DECIDED_AT,
        )
    )
    session.flush()
    evaluation = service.evaluate(view.application_id, reviewer)
    application = service.load_application(view.application_id)
    stored = service.current_evaluation(application.id)
    assert stored is not None
    codes = {
        blocker.code
        for blocker in PermitDecisionService(session).blockers(application, stored)
    }
    assert codes == {"rule_fail"}
    return service, reviewer, view.application_id, evaluation.version


def decide(service, reviewer, application_id, evaluation_version, **fields):
    """Record a decision against the versions the reviewer just read."""
    application = service.load_application(application_id)
    return service.decide(
        PermitDecisionCommand(
            application_id=application_id,
            expected_application_version=application.version,
            expected_evaluation_version=evaluation_version,
            **fields,
        ),
        reviewer,
    )


def test_approving_a_failing_rule_needs_a_reason_and_records_the_exception(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service, reviewer, application_id, evaluation_version = failing_fence(session)
            with pytest.raises(ValidationError) as raised:
                decide(
                    service,
                    reviewer,
                    application_id,
                    evaluation_version,
                    outcome="approved",
                    reason="The fence can stay.",
                )
            message = str(raised.value)
            assert TITLE in message
            assert "exception reason" in message
            assert "unresolved blockers" not in message
            assert service.current_decision(application_id) is None

            result = decide(
                service,
                reviewer,
                application_id,
                evaluation_version,
                outcome="approved",
                reason="The fence can stay.",
                exception_reason="A variance was granted.",
            )
            assert not isinstance(result, ConflictResult)
            decision = result.value
            assert decision.outcome == "approved"
            assert decision.reason == "The fence can stay."
            recorded = decision.input_versions["exception"]
            assert recorded["reason"] == "A variance was granted."
            assert recorded["statement"] == STATEMENT
            assert recorded["rules"] == [
                {"rule_id": "DF-1", "title": TITLE, "status": "fail"}
            ]
            application = service.load_application(application_id)
            stored = service.current_evaluation(application.id)
            assert stored is not None
            assert any(
                blocker.code == "rule_fail"
                for blocker in PermitDecisionService(session).blockers(application, stored)
            )
            assert application.status == "approved"
            event = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "permit.decide",
                    audit.AuditEvent.target_id == decision.decision_id,
                )
            ).scalar_one()
            assert event.reason == STATEMENT
            assert event.metadata_json["exception_reason"] == "A variance was granted."
            assert event.metadata_json["reviewer_rationale"] == "The fence can stay."
            assert event.metadata_json["exception_rules"] == [TITLE]
    finally:
        factory.dispose()


def test_approve_with_conditions_uses_the_same_exception(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service, reviewer, application_id, evaluation_version = failing_fence(session)
            result = decide(
                service,
                reviewer,
                application_id,
                evaluation_version,
                outcome="approved_with_conditions",
                reason="The fence can stay if the variance conditions are kept.",
                conditions=["Keep the fence at the granted height."],
                exception_reason="A variance was granted.",
            )
            assert not isinstance(result, ConflictResult)
            assert result.value.outcome == "approved"
            assert result.value.conditions == ["Keep the fence at the granted height."]
            assert result.value.input_versions["exception"]["statement"] == STATEMENT
    finally:
        factory.dispose()


def test_a_denial_of_a_failing_rule_does_not_need_an_exception_reason(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service, reviewer, application_id, evaluation_version = failing_fence(session)
            result = decide(
                service,
                reviewer,
                application_id,
                evaluation_version,
                outcome="denied",
                reason="The front-yard fence is above the limit.",
                reason_code="DOES_NOT_MEET_CODE",
            )
            assert not isinstance(result, ConflictResult)
            assert result.value.outcome == "denied"
            assert "exception" not in result.value.input_versions
    finally:
        factory.dispose()


def test_a_hard_blocker_still_refuses_approval(seeded: Settings) -> None:
    """An exception reason does not clear an expired credential."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, REVIEWER)
            evaluation = service.evaluate("app_d03", reviewer)
            with pytest.raises(ValidationError) as raised:
                service.decide(
                    PermitDecisionCommand(
                        application_id="app_d03",
                        expected_application_version=service.load_application("app_d03").version,
                        outcome="approved",
                        reason="Approval attempt.",
                        exception_reason="A variance was granted.",
                        expected_evaluation_version=evaluation.version,
                    ),
                    reviewer,
                )
            assert "unresolved blockers" in str(raised.value)
            codes = {blocker["code"] for blocker in raised.value.details["blockers"]}
            assert "credential_expired" in codes
            assert service.current_decision("app_d03") is None
    finally:
        factory.dispose()


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
    return values


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


def test_the_case_page_shows_the_failing_rule_and_the_exception(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            _service, _reviewer, application_id, _version = failing_fence(session)
    finally:
        factory.dispose()

    app = create_app(seeded)
    app.include_router(ui_router)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        page = client.get(f"/permits/{application_id}")
        assert page.status_code == 200, page.text
        form = details_block(page.text, "data-testid", "decision-form")
        rule = re.search(r'data-testid="exception-rule">(.*?)</li>', form, re.S)
        assert rule is not None
        shown = html.unescape(re.sub(r"<[^>]+>", "", rule.group(1)))
        assert TITLE in shown
        assert "Failed: Front yard fence is above the 4 ft maximum." in shown
        area = re.search(r"<textarea\b[^>]*data-testid=\"exception-reason\"[^>]*>", form)
        assert area is not None
        assert "required" not in area.group(0)
        fields = form_values(form)
        refused = client.post(
            "/ui/actions/permit.decide",
            data={**fields, "outcome": "approved", "reason": "The fence can stay."},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert refused.status_code == 422, refused.text
        assert TITLE in refused.json()["message"]
        assert "exception reason" in refused.json()["message"]
        recorded = client.post(
            "/ui/actions/permit.decide",
            data={
                **fields,
                "outcome": "approved",
                "reason": "The fence can stay.",
                "exception_reason": "A variance was granted.",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert recorded.status_code == 200, recorded.text
        done = client.get(f"/permits/{application_id}")
        assert done.status_code == 200, done.text
        assert f'data-testid="decision-exception">{STATEMENT}' in done.text
        assert "A variance was granted." in done.text

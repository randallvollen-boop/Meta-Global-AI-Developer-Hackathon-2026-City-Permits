"""Snapshot the existing single-administrator rule approval contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, finance
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.rules.schemas import DraftRuleCommand, RuleLifecycleCommand
from acme_city.rules.service import RuleCatalogService
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "single")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'single-admin.db'}",
            "ACME_SECRET_KEY": "single-admin-regression-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


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
        record_scope=frozenset(record for grant in grants for record in grant.record_scope),
    )


def test_single_admin_approval_state_and_audit_snapshot(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = RuleCatalogService(session)
            admin = context_for(session, "persona_city_administrator")
            drafted = service.draft(
                DraftRuleCommand(
                    rule_id="REG-SNAPSHOT",
                    permit_type_key="com_ti",
                    title="Fictional access review",
                    citation="ACME Code 14 418",
                    field_path="occupancy_load",
                    operator="max",
                    limit_value="60",
                    on_violate="condition",
                    effective_from=datetime(2026, 10, 29, tzinfo=UTC),
                    reason="Regression snapshot.",
                ),
                admin,
            )
            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id,
                    expected_version=drafted.version,
                    reason="Ready for review.",
                ),
                admin,
            )
            row = session.get(finance.RuleVersion, drafted.value.row_id)
            assert row is not None
            assert (row.status, row.version) == ("in_review", reviewed.version)

            for actor_id in (
                "persona_applicant",
                "persona_data_steward",
                "persona_permit_reviewer",
                "persona_agent_operator",
            ):
                with pytest.raises(PermissionDeniedError):
                    service.approve(
                        RuleLifecycleCommand(
                            rule_version_id=row.id,
                            expected_version=row.version,
                            reason="Not authorized.",
                            confirm_author_approval=True,
                        ),
                        context_for(session, actor_id),
                    )
                assert (row.status, row.version) == ("in_review", reviewed.version)

            approved = service.approve(
                RuleLifecycleCommand(
                    rule_version_id=row.id,
                    expected_version=row.version,
                    reason="Approved by the one fictional administrator.",
                    confirm_author_approval=True,
                ),
                admin,
            )
            assert (row.status, row.version) == ("approved", approved.version)
            event = session.get(audit.AuditEvent, approved.audit_event_id)
            assert event is not None
            assert (
                event.action,
                event.actor_id,
                event.before_version,
                event.after_version,
            ) == (
                "rule.version.approve",
                "persona_city_administrator",
                reviewed.version,
                approved.version,
            )
            assert event.metadata_json["approval_basis_label"] == (
                "Approved by the author (single-administrator policy)"
            )
    finally:
        factory.dispose()


def test_single_admin_approval_http_authorization_and_redirect(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = RuleCatalogService(session)
            admin = context_for(session, "persona_city_administrator")
            drafted = service.draft(
                DraftRuleCommand(
                    rule_id="REG-HTTP", permit_type_key="com_ti",
                    title="Fictional HTTP approval", citation="ACME Code 14 419",
                    field_path="occupancy_load", operator="max", limit_value="61",
                    on_violate="condition",
                    effective_from=datetime(2026, 10, 30, tzinfo=UTC),
                    reason="HTTP regression snapshot.",
                ),
                admin,
            )
            reviewed = service.submit_for_review(
                RuleLifecycleCommand(
                    rule_version_id=drafted.value.row_id, expected_version=drafted.version,
                    reason="Ready for the HTTP approval check.",
                ),
                admin,
            )
            version_id = drafted.value.row_id
            expected_version = reviewed.version
    finally:
        factory.dispose()

    app = create_app(seeded)
    app.include_router(ui_router)
    # The page each persona's action token is read from.  Changed deliberately
    # (the applicant restyle, A1): the chooser of the applicant carries no
    # form of its own, so the token of the applicant comes from the form.
    token_pages = {
        "persona_city_administrator": "/rules?tab=rules&view=drafts",
        "persona_applicant": "/apply/deck_fence",
        "persona_data_steward": "/steward",
        "persona_permit_reviewer": "/permits/app_synth_001",
        "persona_agent_operator": "/agent/intake",
    }
    with TestClient(app) as client:
        def post_as(actor_id: str, version: int):
            assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
            page = client.get(token_pages[actor_id])
            marker = 'name="csrf_token" value="'
            assert marker in page.text
            token = page.text.split(marker, 1)[1].split('"', 1)[0]
            return client.post(
                "/ui/actions/rule.approve",
                data={
                    "csrf_token": token, "action_id": "rule.approve",
                    "next": "/rules?tab=rules&view=drafts",
                    "rule_version_id": version_id, "expected_version": str(version),
                    "reason": "HTTP authorization regression.",
                    "confirm_author_approval": "on",
                },
                follow_redirects=False,
            )

        approved = post_as("persona_city_administrator", expected_version)
        assert approved.status_code == 303
        assert approved.headers["location"].startswith("/rules?tab=rules&view=drafts")
        for actor_id in (
            "persona_applicant", "persona_data_steward",
            "persona_permit_reviewer", "persona_agent_operator",
        ):
            assert post_as(actor_id, expected_version + 1).status_code == 403

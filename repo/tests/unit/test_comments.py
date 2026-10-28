"""Comments: what the City wrote and who may read it.

A comment is either visible to the applicant or an internal note.  The
server enforces that choice; the identifier of an internal note is not a
way to read it, and the audit record of a comment carries the identifier
and the visibility but never the text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.comments import CommentService, comment_view, comments_for
from acme_city.permits.service import PermitService
from acme_city.permits.schemas import SubmitApplicationCommand

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence at 400 Lantern Row",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'comments.db'}",
            "ACME_SECRET_KEY": "comment-test-secret-value",
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


def make_case(session, *, status: str = "needs_information") -> permit.Application:
    """Submit one fictional case and put it in the status the test needs."""
    service = PermitService(session)
    steward = context_for(session, "persona_data_steward")
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            facts=dict(FACTS),
            applicant_party_id="party_cedarline",
        ),
        steward,
    )
    application = service.load_application(view.application_id)
    application.status = status
    session.flush()
    return application


def test_an_applicant_never_reads_an_internal_comment(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            service = CommentService(session)
            internal = service.add_comment(
                application_id=application.id,
                body="An internal note about the applicant.",
                visibility="internal",
                actor=steward,
                expected_version=application.version,
            )
            visible = service.add_comment(
                application_id=application.id,
                body="A message for the applicant.",
                visibility="applicant",
                actor=steward,
                expected_version=application.version,
            )
            applicant = context_for(session, "persona_applicant")
            rows = comments_for(session, application.id, applicant)
            assert [row.id for row in rows] == [visible.id]
            assert internal.id not in {row.id for row in rows}
            # The City reads every comment.
            steward_rows = comments_for(session, application.id, steward)
            assert {row.id for row in steward_rows} == {internal.id, visible.id}
    finally:
        factory.dispose()


def test_a_comment_needs_a_grant_and_an_expected_version(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            applicant = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError):
                CommentService(session).add_comment(
                    application_id=application.id,
                    body="A note.",
                    visibility="internal",
                    actor=applicant,
                    expected_version=application.version,
                )
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                CommentService(session).add_comment(
                    application_id=application.id,
                    body="A note.",
                    visibility="internal",
                    actor=steward,
                    expected_version=None,
                )
            with pytest.raises(ValidationError):
                CommentService(session).add_comment(
                    application_id=application.id,
                    body="A note.",
                    visibility="internal",
                    actor=steward,
                    expected_version=application.version + 5,
                )
            with pytest.raises(ValidationError):
                CommentService(session).add_comment(
                    application_id=application.id,
                    body="",
                    visibility="internal",
                    actor=steward,
                    expected_version=application.version,
                )
            with pytest.raises(ValidationError):
                CommentService(session).add_comment(
                    application_id=application.id,
                    body="A note.",
                    visibility="public",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_the_audit_record_of_a_comment_never_carries_its_text(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            comment = CommentService(session).add_comment(
                application_id=application.id,
                body="A private note that must not travel to the applicant.",
                visibility="internal",
                actor=steward,
                expected_version=application.version,
            )
            from acme_city.persistence.models import audit

            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "application.comment.add"
                )
            ).scalars().all()
            assert len(events) == 1
            assert comment.id in (events[0].references or [])
            assert events[0].metadata_json.get("visibility") == "internal"
            assert "private note" not in (events[0].reason or "")
            assert "private note" not in str(events[0].metadata_json)
    finally:
        factory.dispose()


def test_a_comment_does_not_change_the_state_of_the_case(seeded: Settings) -> None:
    """A comment is evidence; it never advances the case."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            version = application.version
            steward = context_for(session, "persona_data_steward")
            CommentService(session).add_comment(
                application_id=application.id,
                body="A message for the applicant.",
                visibility="applicant",
                actor=steward,
                expected_version=version,
            )
            session.refresh(application)
            assert application.version == version
            assert application.status == "needs_information"
    finally:
        factory.dispose()


def test_the_view_of_a_comment(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            comment = CommentService(session).add_comment(
                application_id=application.id,
                body="A message for the applicant.",
                visibility="applicant",
                actor=steward,
                expected_version=application.version,
            )
            view = comment_view(comment)
            assert view["body"] == "A message for the applicant."
            assert view["visibility"] == "applicant"
            assert view["author_actor_id"] == "persona_data_steward"
    finally:
        factory.dispose()

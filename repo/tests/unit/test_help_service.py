"""The governed writes of the applicant help assistant.

A question, a turn and a help request are the only writes of the assistant.
Each of them checks the grant of the acting persona and a mandatory expected
version, each of them is audited without the text of the question, and the
conversation belongs to the applicant who opened it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.applicant_help.service import ApplicantHelpService
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, help as help_models, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

QUESTION = "Do I need a permit for a 6 ft fence?"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'help-service.db'}",
            "ACME_SECRET_KEY": "help-service-test-secret-value",
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


def context_for(session, actor_id: str, *, session_id: str = "session-one") -> ActorContext:
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
        session_id=session_id,
    )


def test_a_question_is_recorded_with_its_sources(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            assert result.answer.matched is True
            assert result.answer.label == "Matching ACME rule text (not an AI answer)"
            assert result.conversation.turn_count == 1
            assert result.conversation.version == 1
            assert result.turn.outcome == "matched"
            assert result.turn.mode == "fallback"
            # The turn snapshots the source it used: the identifier, the
            # version, the text and the hash.
            assert result.turn.sources
            first = result.turn.sources[0]
            assert set(first) == {"source_id", "version", "text", "sha256"}
            assert first["sha256"]
            assert first["text"]
    finally:
        factory.dispose()


def test_the_answer_quotes_the_published_rule_and_never_claims_an_exemption(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            quoted = "\n".join(paragraph["text"] for paragraph in result.answer.paragraphs)
            assert "ACME Code §14-306" in quoted
            # A limit is not an exemption: the answer never says that a
            # permit is not needed.
            assert "no permit" not in quoted.lower()
            assert "not need a permit" not in quoted.lower()
            assert "exempt" not in quoted.lower()
    finally:
        factory.dispose()


def test_a_question_needs_a_grant_and_a_mandatory_version(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            steward = context_for(session, "persona_data_steward")
            service = ApplicantHelpService(session)
            with pytest.raises(PermissionDeniedError):
                service.ask(
                    steward,
                    question=QUESTION,
                    expected_version=0,
                    placement="chooser",
                )
            with pytest.raises(ValidationError):
                service.ask(
                    applicant,
                    question=QUESTION,
                    expected_version=None,
                    placement="chooser",
                )
    finally:
        factory.dispose()


def test_a_stale_version_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            conversation_id = result.conversation.id
            read_version = result.conversation.version
            with pytest.raises(ValidationError):
                service.ask(
                    applicant,
                    question=QUESTION,
                    expected_version=read_version + 5,
                    conversation_id=conversation_id,
                    placement="chooser",
                )
            # The version the applicant read is the version that is accepted.
            again = service.ask(
                applicant,
                question="What documents do I need for a shed?",
                expected_version=read_version,
                conversation_id=conversation_id,
                placement="chooser",
            )
            assert again.conversation.version == read_version + 1
    finally:
        factory.dispose()


def test_the_conversation_of_another_applicant_is_not_found(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            other = context_for(session, "service_applicant_2", session_id="session-two")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            assert service.conversation_for(other, result.conversation.id) is None
            with pytest.raises(NotFoundError):
                service.ask(
                    other,
                    question=QUESTION,
                    expected_version=result.conversation.version,
                    conversation_id=result.conversation.id,
                    placement="chooser",
                )
    finally:
        factory.dispose()


def test_the_question_is_length_limited(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            with pytest.raises(ValidationError):
                service.ask(
                    applicant,
                    question="",
                    expected_version=0,
                    placement="chooser",
                )
            with pytest.raises(ValidationError):
                service.ask(
                    applicant,
                    question="x" * 1001,
                    expected_version=0,
                    placement="chooser",
                )
    finally:
        factory.dispose()


def test_the_rate_limit_stops_a_session_that_asks_too_often(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            for index in range(10):
                service.ask(
                    applicant,
                    question=f"Question number {index} about a fence?",
                    expected_version=0,
                    placement="chooser",
                )
            with pytest.raises(ValidationError):
                service.ask(
                    applicant,
                    question="One question too many.",
                    expected_version=0,
                    placement="chooser",
                )
            # Another session of the same applicant has its own budget.
            other = context_for(session, "persona_applicant", session_id="session-two")
            service.ask(
                other,
                question="A question in another session.",
                expected_version=0,
                placement="chooser",
            )
    finally:
        factory.dispose()


def test_the_audit_record_of_a_question_carries_no_question_text(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "applicant.help.ask"
                )
            ).scalars().all()
            assert len(events) == 1
            event = events[0]
            assert event.target_id == result.conversation.id
            assert event.metadata_json["turn_id"] == result.turn.id
            assert event.metadata_json["outcome"] == "matched"
            assert QUESTION not in str(event.reason or "")
            assert QUESTION not in str(event.metadata_json or "")
    finally:
        factory.dispose()


def test_ask_the_city_creates_a_help_request_and_audits_without_the_question(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            conversation_id = result.conversation.id
            read_version = result.conversation.version
            request = service.escalate(
                applicant,
                conversation_id=conversation_id,
                expected_version=read_version,
                question=QUESTION,
            )
            assert request.status == "open"
            assert request.applicant_actor_id == applicant.actor_id
            assert request.question == QUESTION
            # The conversation version moves, so a stale escalation is refused.
            with pytest.raises(ValidationError):
                service.escalate(
                    applicant,
                    conversation_id=conversation_id,
                    expected_version=read_version,
                    question=QUESTION,
                )
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "applicant.help.escalate"
                )
            ).scalars().all()
            assert len(events) == 1
            assert QUESTION not in str(events[0].reason or "")
            assert QUESTION not in str(events[0].metadata_json or "")
            assert events[0].metadata_json["help_request_id"] == request.id
    finally:
        factory.dispose()


def test_ask_the_city_needs_the_grant_of_the_applicant(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            steward = context_for(session, "persona_data_steward")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            with pytest.raises(PermissionDeniedError):
                service.escalate(
                    steward,
                    conversation_id=result.conversation.id,
                    expected_version=result.conversation.version,
                    question=QUESTION,
                )
    finally:
        factory.dispose()


def test_the_assistant_writes_nothing_but_the_conversation_and_the_audit(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            before = {
                "applications": len(session.execute(select(permit.Application)).scalars().all()),
                "findings": len(session.execute(select(permit.ApplicationFinding)).scalars().all()),
                "decisions": len(session.execute(select(permit.Decision)).scalars().all()),
                "documents": len(session.execute(select(permit.Document)).scalars().all()),
            }
            service = ApplicantHelpService(session)
            service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            after = {
                "applications": len(session.execute(select(permit.Application)).scalars().all()),
                "findings": len(session.execute(select(permit.ApplicationFinding)).scalars().all()),
                "decisions": len(session.execute(select(permit.Decision)).scalars().all()),
                "documents": len(session.execute(select(permit.Document)).scalars().all()),
            }
            assert before == after
            turns = session.execute(select(help_models.HelpTurn)).scalars().all()
            assert len(turns) == 1
    finally:
        factory.dispose()


def test_the_assistant_never_calls_a_provider(seeded: Settings, monkeypatch) -> None:
    import acme_city.muse.client as muse_client

    def refuse(*args, **kwargs):  # pragma: no cover - the call must not happen
        raise AssertionError("the applicant assistant must not call a provider")

    monkeypatch.setattr(muse_client, "MuseClient", refuse)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            assert result.answer.mode == "fallback"
    finally:
        factory.dispose()


def test_the_turns_that_did_not_answer_are_counted_once_each(seeded: Settings) -> None:
    """One turn is one count: a turn that found nothing counts once."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            service = ApplicantHelpService(session)
            result = service.ask(
                applicant,
                question="purple monkey dishwasher",
                expected_version=0,
                placement="chooser",
            )
            conversation_id = result.conversation.id
            version = result.conversation.version
            assert result.turn.outcome == "no_match"
            assert service.unsuccessful_turn_count(result.conversation) == 1
            service.ask(
                applicant,
                question=QUESTION,
                expected_version=version,
                conversation_id=conversation_id,
                placement="chooser",
            )
            assert service.unsuccessful_turn_count(result.conversation) == 1
            service.ask(
                applicant,
                question="kryptonite sprockets",
                expected_version=version + 1,
                conversation_id=conversation_id,
                placement="chooser",
            )
            assert service.unsuccessful_turn_count(result.conversation) == 2
    finally:
        factory.dispose()


def test_the_audit_service_is_still_append_only(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = AuditService(session)
            assert not hasattr(service, "update")
            assert not hasattr(service, "delete")
    finally:
        factory.dispose()


def test_the_clock_of_the_service_is_the_one_it_was_given(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            moment = utc_now() - timedelta(hours=1)
            service = ApplicantHelpService(session, now=moment)
            result = service.ask(
                applicant,
                question=QUESTION,
                expected_version=0,
                placement="chooser",
            )
            assert result.turn.created_at <= moment
    finally:
        factory.dispose()

"""Processing a bounded selection of cases with the intake agent.

The bulk action has its own grant, refuses an empty selection, checks every
case before it runs any of them, and either processes the whole selection or
none of it.  It never falls through to the "process every waiting case"
action of the agent screen.
"""
# REQUIRES: PER-01, PER-03, AI-03, SEC-02
# The batch is bounded, deduplicated, version-checked, refused while the
# agent sleeps and all-or-nothing.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.control import AgentControlService
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import audit, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.bulk import MAX_SELECTION, Selection, process_selected
from acme_city.permits.service import PermitService
from acme_city.permits.schemas import SubmitApplicationCommand

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence at 400 Lantern Row",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, ACME City",
    "channel": "portal",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'bulk.db'}",
            "ACME_SECRET_KEY": "bulk-test-secret-value",
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


def make_arrival(session) -> permit.Application:
    """Submit one case that arrived from outside the City."""
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
    session.flush()
    return application


def wake_the_agent(session) -> None:
    """Put the intake agent to sleep."""
    service = AgentControlService(session)
    service.ensure_defaults()
    row = service.state(agent_models.AGENT_INTAKE)
    assert row is not None
    row.mode = agent_models.AGENT_AWAKE
    session.flush()


def intake_runs(session) -> list[agent_models.AgentRun]:
    """Return every recorded intake run."""
    return list(
        session.execute(
            select(agent_models.AgentRun).where(
                agent_models.AgentRun.agent_key == agent_models.AGENT_INTAKE
            )
        ).scalars().all()
    )


def test_only_the_steward_may_process_a_selection(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            arrival = make_arrival(session)
            selection = [Selection(arrival.id, arrival.version)]
            for actor_id in (
                "persona_permit_reviewer",
                "persona_city_administrator",
                "persona_applicant",
            ):
                actor = context_for(session, actor_id)
                with pytest.raises(PermissionDeniedError):
                    process_selected(
                        session, actor=actor, selections=selection
                    )
            assert intake_runs(session) == []
    finally:
        factory.dispose()


def test_an_empty_selection_is_refused_and_never_falls_through(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError) as raised:
                process_selected(session, actor=steward, selections=[])
            assert "choose at least one case" in str(raised.value)
            # Nothing was processed: the action never became "process all".
            assert intake_runs(session) == []
    finally:
        factory.dispose()


def test_a_selection_is_bounded_to_fifty_cases(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            steward = context_for(session, "persona_data_steward")
            selection = [Selection(f"app_fake_{index}", 1) for index in range(51)]
            with pytest.raises(ValidationError) as raised:
                process_selected(session, actor=steward, selections=selection)
            assert str(MAX_SELECTION) in str(raised.value)
    finally:
        factory.dispose()


def test_a_repeated_case_is_processed_once(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            arrival = make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            result = process_selected(
                session,
                actor=steward,
                selections=[
                    Selection(arrival.id, arrival.version),
                    Selection(arrival.id, arrival.version),
                ],
            )
            assert result.processed == (arrival.id,)
            assert len(intake_runs(session)) == 1
    finally:
        factory.dispose()


def test_a_case_named_at_two_versions_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            arrival = make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                process_selected(
                    session,
                    actor=steward,
                    selections=[
                        Selection(arrival.id, arrival.version),
                        Selection(arrival.id, arrival.version + 1),
                    ],
                )
            assert intake_runs(session) == []
    finally:
        factory.dispose()


def test_a_stale_version_refuses_the_whole_batch(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            first = make_arrival(session)
            second = make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                process_selected(
                    session,
                    actor=steward,
                    selections=[
                        Selection(first.id, first.version),
                        Selection(second.id, second.version + 5),
                    ],
                )
            assert intake_runs(session) == []
    finally:
        factory.dispose()


def test_a_case_that_does_not_wait_refuses_the_whole_batch(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            first = make_arrival(session)
            second = make_arrival(session)
            # The second case is already with the reviewer: it does not wait
            # for the intake agent.
            second.status = "ready_for_review"
            session.flush()
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                process_selected(
                    session,
                    actor=steward,
                    selections=[
                        Selection(first.id, first.version),
                        Selection(second.id, second.version),
                    ],
                )
            # All-or-nothing: the first case was not processed either.
            assert intake_runs(session) == []
            session.refresh(first)
            assert first.status == "submitted"
    finally:
        factory.dispose()


def test_the_batch_is_refused_while_the_agent_sleeps(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            arrival = make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError) as raised:
                process_selected(
                    session,
                    actor=steward,
                    selections=[Selection(arrival.id, arrival.version)],
                )
            assert "asleep" in str(raised.value)
            assert intake_runs(session) == []
    finally:
        factory.dispose()


def test_the_batch_processes_every_selected_case_and_is_audited(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            wake_the_agent(session)
            first = make_arrival(session)
            second = make_arrival(session)
            steward = context_for(session, "persona_data_steward")
            result = process_selected(
                session,
                actor=steward,
                selections=[
                    Selection(first.id, first.version),
                    Selection(second.id, second.version),
                ],
            )
            assert result.processed == (first.id, second.id)
            assert len(intake_runs(session)) == 2
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action
                    == "application.intake.process_selected"
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].actor_id == "persona_data_steward"
            metadata = dict(events[0].metadata_json or {})
            assert metadata["selection_size"] == 2
            assert sorted(metadata["application_ids"]) == sorted(
                [first.id, second.id]
            )
    finally:
        factory.dispose()

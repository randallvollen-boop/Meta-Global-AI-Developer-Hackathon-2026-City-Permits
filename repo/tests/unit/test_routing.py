"""Priority and assignment: the routing metadata of a case.

The owner of a case is routing metadata only.  It grants nothing, it never
makes the owner a decision maker, and it never adds a selectable persona.
The eligible owners of a case are the active people eligible for the stage
of the case.
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
from acme_city.permits.routing import RoutingService, stage_of
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'routing.db'}",
            "ACME_SECRET_KEY": "routing-test-secret-value",
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


def test_a_steward_changes_the_priority(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            RoutingService(session).set_priority(
                application_id=application.id,
                priority="high",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.priority == "high"
            with pytest.raises(ValidationError):
                RoutingService(session).set_priority(
                    application_id=application.id,
                    priority="urgent",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_only_the_steward_changes_the_priority(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            reviewer = context_for(session, "persona_permit_reviewer")
            with pytest.raises(PermissionDeniedError):
                RoutingService(session).set_priority(
                    application_id=application.id,
                    priority="high",
                    actor=reviewer,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_steward_routes_an_intake_case_to_a_steward_capable_person(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            routing = RoutingService(session)
            eligible = routing.eligible_owners("intake")
            assert [entry["actor_id"] for entry in eligible] == ["persona_data_steward"]
            routing.assign(
                application_id=application.id,
                owner_actor_id="persona_data_steward",
                actor=steward,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.owner_actor_id == "persona_data_steward"
    finally:
        factory.dispose()


def test_a_review_case_may_be_routed_to_a_reviewer_capable_person(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            reviewer = context_for(session, "persona_permit_reviewer")
            routing = RoutingService(session)
            eligible = routing.eligible_owners("review")
            assert [entry["actor_id"] for entry in eligible] == ["persona_permit_reviewer"]
            routing.assign(
                application_id=application.id,
                owner_actor_id="persona_permit_reviewer",
                actor=reviewer,
                expected_version=application.version,
            )
            session.refresh(application)
            assert application.owner_actor_id == "persona_permit_reviewer"
    finally:
        factory.dispose()


def test_a_service_identity_is_never_an_eligible_owner(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                RoutingService(session).assign(
                    application_id=application.id,
                    owner_actor_id="service_agent_intake",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_a_steward_may_not_route_a_review_case(seeded: Settings) -> None:
    """The stage of the case decides who may route it."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            steward = context_for(session, "persona_data_steward")
            with pytest.raises(ValidationError):
                RoutingService(session).assign(
                    application_id=application.id,
                    owner_actor_id="persona_data_steward",
                    actor=steward,
                    expected_version=application.version,
                )
    finally:
        factory.dispose()


def test_an_assignment_never_grants_an_authority(seeded: Settings) -> None:
    """The owner of a case holds no grant the owner did not have."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="ready_for_review")
            reviewer = context_for(session, "persona_permit_reviewer")
            RoutingService(session).assign(
                application_id=application.id,
                owner_actor_id="persona_permit_reviewer",
                actor=reviewer,
                expected_version=application.version,
            )
            resolver = PermissionResolver(session)
            grants = {grant.action for grant in resolver.grants_for("persona_permit_reviewer")}
            assert "permit.decide" in grants
            # The City Administrator holds none of the decision grants, and
            # an assignment never changes that.
            administrator = {
                grant.action
                for grant in resolver.grants_for("persona_city_administrator")
            }
            assert "permit.decide" not in administrator
            assert "permit.issue" not in administrator
    finally:
        factory.dispose()


def test_the_stage_of_a_case(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status="needs_information")
            assert stage_of(application) == "intake"
            application.status = "ready_for_review"
            assert stage_of(application) == "review"
            application.status = "archived"
            assert stage_of(application) is None
    finally:
        factory.dispose()

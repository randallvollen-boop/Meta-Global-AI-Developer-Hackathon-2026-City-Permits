"""D05: a profile update preserves the submitted and issued history.

The current profile shows the newer contact value while the submitted
revision keeps the value it was submitted with.  A case-specific correction
creates a new revision and leaves the earlier one alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import ReviseApplicationCommand
from acme_city.permits.service import PermitService

FIRST_CONTACT = "demo.applicant@example.invalid"
SECOND_CONTACT = "demo.applicant.new@example.invalid"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'd05.db'}",
            "ACME_SECRET_KEY": "d05-profile-history-secret-value",
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


def test_the_submitted_revision_keeps_the_first_contact(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            applicant = context_for(session, "persona_applicant")

            view = service.application_view(service.load_application("app_d05"))
            assert view.snapshot["contact_email"] == FIRST_CONTACT

            # The current profile of the party moves to version two.
            contact = session.execute(
                select(registry.PartyContact).where(
                    registry.PartyContact.id == "contact_applicant_1_email"
                )
            ).scalar_one()
            contact.value = SECOND_CONTACT
            session.flush()

            # The current profile shows the new value.
            stored = session.execute(
                select(registry.PartyContact).where(
                    registry.PartyContact.id == "contact_applicant_1_email"
                )
            ).scalar_one()
            assert stored.value == SECOND_CONTACT

            # The submitted facts keep the value they were submitted with.
            revision = service.current_revision("app_d05")
            assert revision.snapshot["contact_email"] == FIRST_CONTACT
            view = service.application_view(service.load_application("app_d05"))
            assert view.snapshot["contact_email"] == FIRST_CONTACT
            assert applicant.record_scope
    finally:
        factory.dispose()


def test_a_case_specific_correction_creates_a_new_revision(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            first = service.current_revision("app_d05")
            assert first.revision_number == 1

            revised = service.revise(
                ReviseApplicationCommand(
                    application_id="app_d05",
                    facts={"contact_email": SECOND_CONTACT},
                    reason="Fictional demonstration correction of the case.",
                ),
                steward,
            )
            assert revised.revision_number == 2
            assert revised.snapshot["contact_email"] == SECOND_CONTACT

            stored = session.execute(
                select(permit.ApplicationRevision).where(
                    permit.ApplicationRevision.id == first.id
                )
            ).scalar_one()
            assert stored.snapshot["contact_email"] == FIRST_CONTACT
            assert stored.revision_number == 1
    finally:
        factory.dispose()

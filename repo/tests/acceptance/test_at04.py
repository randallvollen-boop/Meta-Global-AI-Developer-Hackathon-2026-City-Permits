"""AT04: profile versus submission.

The current profile shows the newer value while the submitted facts and the
notices that were issued keep the value they were written with.  A
case-specific correction creates a revision.
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
from acme_city.permits.schemas import ReviseApplicationCommand, SubmitApplicationCommand
from acme_city.permits.service import PermitService

FIRST_CONTACT = "t.aldous@example.invalid"
SECOND_CONTACT = "t.aldous.second@example.invalid"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at04.db'}",
            "ACME_SECRET_KEY": "at04-profile-versus-submission-secret",
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


def test_the_profile_moves_and_the_submission_does_not(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")

            # The submitted revision at profile version one.
            submitted = service.application_view(service.load_application("app_d05"))
            assert submitted.snapshot["contact_email"] == FIRST_CONTACT
            first_revision_id = submitted.revision_id

            # The current profile moves to version two.
            contact = session.execute(
                select(registry.PartyContact).where(
                    registry.PartyContact.id == "contact_applicant_1_email"
                )
            ).scalar_one()
            contact.value = SECOND_CONTACT
            session.flush()

            current = session.execute(
                select(registry.PartyContact).where(
                    registry.PartyContact.id == "contact_applicant_1_email"
                )
            ).scalar_one()
            assert current.value == SECOND_CONTACT

            # The submitted facts keep version one.
            revision = session.execute(
                select(permit.ApplicationRevision).where(
                    permit.ApplicationRevision.id == first_revision_id
                )
            ).scalar_one()
            assert revision.snapshot["contact_email"] == FIRST_CONTACT
            assert revision.revision_number == 1

            # The evaluation of the submitted revision still uses version one.
            evaluation = service.evaluate("app_d05", reviewer)
            assert evaluation.inputs["contact_email"] == FIRST_CONTACT
    finally:
        factory.dispose()


def test_a_case_specific_correction_creates_a_revision(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            applicant = context_for(session, "persona_applicant")

            first = service.current_revision("app_d05")
            assert first.revision_number == 1
            assert first.snapshot["contact_email"] == FIRST_CONTACT

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

            # The earlier revision is unchanged and still available.
            stored = session.execute(
                select(permit.ApplicationRevision).where(
                    permit.ApplicationRevision.id == first.id
                )
            ).scalar_one()
            assert stored.snapshot["contact_email"] == FIRST_CONTACT
            revisions = session.execute(
                select(permit.ApplicationRevision).where(
                    permit.ApplicationRevision.application_id == "app_d05"
                )
            ).scalars().all()
            assert len(revisions) == 2
            assert applicant.record_scope
    finally:
        factory.dispose()


def test_the_application_facts_do_not_overwrite_the_shared_party_facts(
    seeded: Settings,
) -> None:
    """An application never rewrites a shared party or GIS record."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            before = session.execute(
                select(registry.Party).where(registry.Party.id == "party_applicant_1")
            ).scalar_one()
            display_name = before.display_name

            service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    applicant_party_id="party_applicant_1",
                    facts={
                        "project_description": "A fictional studio tenant improvement.",
                        "valuation": 31000.0,
                        "valuation_cents": 3100000,
                        "occupancy_load": 12,
                        "contractor_license": "CR-2026-00188",
                        "applicant_role": "individual",
                        "organization_name": "A name the applicant wrote",
                        "submitted_parcel": "ACME-P-1002",
                        "submitted_site_text": "12 Marrow Creek Road, ACME City",
                    },
                ),
                steward,
            )
            after = session.execute(
                select(registry.Party).where(registry.Party.id == "party_applicant_1")
            ).scalar_one()
            assert after.display_name == display_name
    finally:
        factory.dispose()

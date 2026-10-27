"""Application revision tests: immutable submissions and the date basis.

A submitted revision never changes.  A later revision adds facts; it never
rewrites what an earlier revision declared, and the initial submission date
is never moved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError
from acme_city.core.results import ConflictResult
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import ReviseApplicationCommand, SubmitApplicationCommand
from acme_city.permits.service import PermitService

FACTS = {
    "project_description": "A fictional interior tenant improvement.",
    "valuation": 50000.0,
    "valuation_cents": 5000000,
    "occupancy_load": 42,
    "contractor_license": "CR-2026-00188",
    "organization_name": "Cedar Line Coffee Roasters",
    "applicant_role": "business",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'revisions.db'}",
            "ACME_SECRET_KEY": "application-revisions-secret-value",
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


def test_a_submission_records_an_immutable_first_revision(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            view = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts=dict(FACTS),
                    applicant_party_id="party_cedarline",
                    parties=[],
                ),
                steward,
            )
            assert view.revision_number == 1
            assert view.status == "submitted"
            assert view.initial_submitted_at is not None
            assert view.snapshot["valuation_cents"] == 5000000

            stored = session.execute(
                select(permit.ApplicationRevision).where(
                    permit.ApplicationRevision.id == view.revision_id
                )
            ).scalar_one()
            assert stored.snapshot["valuation_cents"] == 5000000
            assert stored.date_basis == "initial_submitted_at"
    finally:
        factory.dispose()


def test_a_revision_preserves_the_initial_submission_date(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            submitted = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts=dict(FACTS),
                    applicant_party_id="party_cedarline",
                ),
                steward,
            )
            initial = submitted.initial_submitted_at
            assert initial is not None

            revised = service.revise(
                ReviseApplicationCommand(
                    application_id=submitted.application_id,
                    facts={"valuation": 70000.0, "valuation_cents": 7000000},
                    reason="Fictional demonstration correction.",
                ),
                steward,
            )
            assert isinstance(revised, ConflictResult) is False
            assert revised.revision_number == 2
            assert revised.initial_submitted_at == initial
            assert revised.revision_submitted_at is not None
            assert revised.snapshot["valuation_cents"] == 7000000
            # The facts of the first revision are unchanged.
            assert submitted.snapshot["valuation_cents"] == 5000000
    finally:
        factory.dispose()


def test_a_stale_expected_version_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            submitted = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts=dict(FACTS),
                    applicant_party_id="party_cedarline",
                ),
                steward,
            )
            refused = service.revise(
                ReviseApplicationCommand(
                    application_id=submitted.application_id,
                    facts={"valuation": 70000.0},
                    reason="Stale expectation.",
                    expected_version=99,
                ),
                steward,
            )
            assert isinstance(refused, ConflictResult)
            assert refused.code == "version_conflict"
            assert refused.current_version == submitted.application_version
    finally:
        factory.dispose()


def test_an_applicant_may_not_revise_another_applicants_case(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            applicant = context_for(session, "persona_applicant")
            with pytest.raises(PermissionDeniedError):
                service.revise(
                    ReviseApplicationCommand(
                        application_id="app_synth_001",
                        facts={"valuation": 1.0},
                        reason="Out of scope.",
                    ),
                    applicant,
                )
    finally:
        factory.dispose()


def test_a_revision_invalidates_the_dependent_work(seeded: Settings) -> None:
    """A new revision makes the evaluation and the decision stale."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            submitted = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts=dict(FACTS),
                    applicant_party_id="party_cedarline",
                ),
                steward,
            )
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate(submitted.application_id, reviewer)
            assert evaluation.status == "current"
            assert evaluation.stale is False

            service.revise(
                ReviseApplicationCommand(
                    application_id=submitted.application_id,
                    facts={"valuation": 70000.0, "valuation_cents": 7000000},
                    reason="Fictional demonstration correction.",
                ),
                steward,
            )
            stored = session.execute(
                select(permit.Evaluation).where(permit.Evaluation.id == evaluation.evaluation_id)
            ).scalar_one()
            assert stored.stale is True
            assert stored.status == "superseded"
    finally:
        factory.dispose()


def test_the_site_is_resolved_against_the_official_records(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
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
            assert view.site is not None
            assert view.site.resolution_status == "resolved"
            assert view.site.parcel_id == "parcel_1001"
    finally:
        factory.dispose()


def test_an_unresolved_parcel_is_not_invented(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            facts = dict(FACTS)
            facts["submitted_parcel"] = "ACME-P-9999"
            facts["submitted_site_text"] = "1234 Kestrel Pass, ACME City"
            view = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts=facts,
                    applicant_party_id="party_hollis",
                ),
                steward,
            )
            assert view.site is not None
            assert view.site.resolution_status == "unresolved"
            assert view.site.parcel_id is None
    finally:
        factory.dispose()

"""The source bundle of the applicant help assistant.

The bundle is built from the City's published rule versions and from the
stored permit-type configuration.  A draft rule never reaches an applicant, a
rule is rendered with its applicability, its operator, its threshold and its
conditions, and the bundle carries the applicant's own case only: never
another applicant's record and never an internal note.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.applicant_help.config import load_config
from acme_city.applicant_help.sources import build_bundle
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.payloads import assert_no_truth_in_payload
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'help-sources.db'}",
            "ACME_SECRET_KEY": "help-sources-test-secret-value",
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


def application_of(session, reference: str) -> permit.Application:
    """Return one seeded application by its reference."""
    row = session.execute(
        select(permit.Application).where(
            permit.Application.source_application_number == reference
        )
    ).scalar_one()
    return row


def test_the_bundle_holds_the_published_rule_and_never_the_draft(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                permit_type_key="com_ti",
            )
            texts = "\n".join(source.text for source in bundle.passages)
            # The published version of CT-2 is in force; the draft of the
            # same rule is not.
            assert "ACME Code §14-415" in texts
            assert "Threshold: 250000." in texts
            assert "Threshold: 300000." not in texts
    finally:
        factory.dispose()


def test_a_rule_is_rendered_with_its_applicability_operator_threshold_and_conditions(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                permit_type_key="deck_fence",
            )
            passage = bundle.source("rule.DF-1.DF-1@1")
            assert passage is not None
            assert "Applies when: location = front; structure_kind = fence." in passage.text
            assert "Operator: must not be more than." in passage.text
            assert "Threshold: 4." in passage.text
            # The message of a rule describes a violation.  It is rendered
            # as a condition, never as a fact about the applicant.
            assert "If the rule is not met: Front yard fence is above the 4 ft maximum." in passage.text
            assert passage.version == "DF-1@1"
    finally:
        factory.dispose()


def test_the_applicant_is_asked_for_the_address_and_not_for_a_parcel_number(
    seeded: Settings,
) -> None:
    """The address locator finds the parcel, so the applicant gives the address.

    The application form has no parcel field, so the published passages must
    not ask for a parcel number either.
    """
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                permit_type_key="com_ti",
            )
            texts = "\n".join(source.text for source in bundle.passages)
            assert "Required fields: Property address" in texts
            assert "Parcel number" not in texts
            assert "Have the address of the work ready" in texts
            assert "parcel number" not in texts
    finally:
        factory.dispose()


def test_the_bundle_carries_no_truth(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            bundle = build_bundle(session, applicant, config=load_config())
            assert_no_truth_in_payload(bundle.to_payload())
    finally:
        factory.dispose()


def test_the_bundle_of_a_case_carries_that_case_and_no_other(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            own = application_of(session, "SYN-APP-005")
            other = application_of(session, "SYN-APP-011")
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                application_id=own.id,
            )
            texts = "\n".join(source.text for source in bundle.passages)
            assert "SYN-APP-005" in texts
            assert other.source_application_number not in texts
            assert bundle.application_reference == "SYN-APP-005"
    finally:
        factory.dispose()


def test_the_bundle_of_another_applicants_case_is_refused(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            other = application_of(session, "SYN-APP-011")
            with pytest.raises(Exception) as refusal:
                build_bundle(
                    session,
                    applicant,
                    config=load_config(),
                    application_id=other.id,
                )
            assert "not available" in str(refusal.value)
    finally:
        factory.dispose()


def test_the_bundle_carries_no_internal_note(seeded: Settings) -> None:
    from acme_city.permits.comments import CommentService

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            steward = context_for(session, "persona_data_steward")
            own = application_of(session, "SYN-APP-005")
            CommentService(session).add_comment(
                application_id=own.id,
                body="An internal note that stays inside the City.",
                visibility="internal",
                actor=steward,
                expected_version=own.version,
            )
            CommentService(session).add_comment(
                application_id=own.id,
                body="A message the applicant reads.",
                visibility="applicant",
                actor=steward,
                expected_version=own.version,
            )
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                application_id=own.id,
            )
            texts = "\n".join(source.text for source in bundle.passages)
            assert "A message the applicant reads." in texts
            assert "An internal note that stays inside the City." not in texts
    finally:
        factory.dispose()


def test_the_rules_of_a_case_are_the_ones_in_force_when_it_was_filed(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            own = application_of(session, "SYN-APP-005")
            bundle = build_bundle(
                session,
                applicant,
                config=load_config(),
                application_id=own.id,
            )
            assert bundle.basis_at == own.initial_submitted_at
    finally:
        factory.dispose()


def test_the_guidance_of_the_chooser_uses_the_time_of_the_server(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            applicant = context_for(session, "persona_applicant")
            bundle = build_bundle(session, applicant, config=load_config())
            assert bundle.basis_at is not None
            assert bundle.application_reference == ""
            # The chooser knows no type yet, so the bundle holds the rules of
            # every active permit type.
            texts = "\n".join(source.text for source in bundle.passages)
            assert "Applies to: Shed or accessory building (shed)." in texts
    finally:
        factory.dispose()

"""Evaluation tests: what an evaluation records and what it invalidates.

An evaluation persists the application revision, the rule versions, every
evaluated input, the basis date and every result, so that a later change can
be shown to affect exactly the cases it affects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService

BASIS = datetime(2026, 9, 8, 14, 30, tzinfo=UTC)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'evaluations.db'}",
            "ACME_SECRET_KEY": "evaluations-test-secret-value",
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


def test_an_evaluation_persists_its_versions_inputs_and_results(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_synth_001", reviewer)

            assert evaluation.rule_versions == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
            assert evaluation.citations == ["ACME Code §14-412", "ACME Code §14-415"]
            assert evaluation.date_basis.startswith("initial_submitted_at@")
            assert evaluation.inputs["valuation_cents"] == 5000000
            assert evaluation.inputs["occupancy_load"] == 42
            assert evaluation.outcome == "pass"
            assert {result.rule_id for result in evaluation.results} == {"CT-1", "CT-2"}

            stored = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.id == evaluation.evaluation_id
                )
            ).scalar_one()
            assert stored.revision_id is not None
            assert stored.rule_versions == {"CT-1": "CT-1@1", "CT-2": "CT-2@1"}
            assert stored.results
            assert stored.source_versions is not None
    finally:
        factory.dispose()


def test_the_date_basis_is_the_initial_submission_date(seeded: Settings) -> None:
    """The P0 basis for rules and fees is the initial submission date."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_synth_001", reviewer)
            assert evaluation.date_basis == f"initial_submitted_at@{BASIS.isoformat()}"
    finally:
        factory.dispose()


def test_an_evaluation_registers_its_dependencies(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_synth_001", reviewer)
            assert "rule:CT-1" in evaluation.dependencies
            assert "rule:CT-2" in evaluation.dependencies
            assert "credential:cred_license_cedarline" in evaluation.dependencies
            assert "credential:cred_contractor_ironvale" in evaluation.dependencies
            assert "party:party_cedarline" in evaluation.dependencies
            assert evaluation.dependency_versions["rule:CT-2"] == "CT-2@1"
    finally:
        factory.dispose()


def test_a_second_evaluation_supersedes_the_first(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            first = service.evaluate("app_synth_001", reviewer)
            second = service.evaluate("app_synth_001", reviewer)
            assert second.evaluation_id != first.evaluation_id

            stored = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.id == first.evaluation_id
                )
            ).scalar_one()
            assert stored.status == "superseded"
            assert stored.stale is True
    finally:
        factory.dispose()


def test_an_unchanged_revision_reuses_the_current_evaluation(seeded: Settings) -> None:
    """The review screen can show the stored result without a second row.

    ``evaluate`` itself still records a new row. The reuse path is the one
    the Run checks again button uses.
    """
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            first = service.evaluate("app_synth_001", reviewer)
            session.flush()
            again = service.unchanged_evaluation("app_synth_001", reviewer)
            assert again is not None
            assert again.evaluation_id == first.evaluation_id
            assert again.version == first.version
            rows = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(rows) == 1

            stored = rows[0]
            original_results = list(stored.results or [])
            stored.results = []
            session.flush()
            assert service.unchanged_evaluation("app_synth_001", reviewer) is None
            stored.results = original_results
            stored.stale = True
            session.flush()
            assert service.unchanged_evaluation("app_synth_001", reviewer) is None
            still = session.execute(
                select(permit.Evaluation).where(
                    permit.Evaluation.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(still) == 1
    finally:
        factory.dispose()


def test_an_expired_credential_is_recorded_as_a_blocker(seeded: Settings) -> None:
    """The contractor registration of D03 expired before the decision date."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d03", reviewer)
            codes = {blocker.code for blocker in evaluation.blockers}
            assert "credential_expired" in codes
            assert evaluation.outcome in {"pass", "condition", "fail", "review"}
    finally:
        factory.dispose()


def test_an_unresolved_site_is_recorded_as_a_blocker(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d04", reviewer)
            codes = {blocker.code for blocker in evaluation.blockers}
            assert "site_unresolved" in codes
    finally:
        factory.dispose()


def test_evaluating_an_issued_case_does_not_reopen_it(seeded: Settings) -> None:
    """The issued state of a case is never changed by an evaluation."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            reviewer = context_for(session, "persona_permit_reviewer")
            evaluation = service.evaluate("app_d07", reviewer)
            assert evaluation.evaluation_id
            application = service.load_application("app_d07")
            assert application.status == "issued"
    finally:
        factory.dispose()


def test_a_missing_required_field_is_recorded_as_a_blocker(seeded: Settings) -> None:
    """A required input that was never supplied is an explicit blocker."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            service = PermitService(session)
            steward = context_for(session, "persona_data_steward")
            reviewer = context_for(session, "persona_permit_reviewer")
            submitted = service.submit(
                SubmitApplicationCommand(
                    permit_type_key="com_ti",
                    facts={
                        "project_description": "A fictional tenant improvement.",
                        "valuation": 50000.0,
                        "valuation_cents": 5000000,
                        "contractor_license": "CR-2026-00188",
                        "organization_name": "Cedar Line Coffee Roasters",
                        "applicant_role": "business",
                        "submitted_parcel": "ACME-P-1001",
                        "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
                    },
                    applicant_party_id="party_cedarline",
                ),
                steward,
            )
            evaluation = service.evaluate(submitted.application_id, reviewer)
            codes = {blocker.code for blocker in evaluation.blockers}
            assert "missing_required_field" in codes
            details = {
                blocker.detail
                for blocker in evaluation.blockers
                if blocker.code == "missing_required_field"
            }
            assert any("occupancy_load" in detail for detail in details)
    finally:
        factory.dispose()

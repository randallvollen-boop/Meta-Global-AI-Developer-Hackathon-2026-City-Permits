"""The generated intake records: a deterministic mix, bounded and governed.

The generator builds the sample cases a demonstration needs.  The tests pin
what the build plan asks for: the same seed and nonce build the same
records, a different nonce builds new ones, the mix of outcomes is exact,
the caps are refused, every case waits for the intake agent and the
protected inputs stay untouched.
"""
# REQUIRES: ING-01, ING-02, PER-01
# The records are pure data, the caps are refused, and every case is created
# through the governed intake path.

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.agents.control import AgentControlService, is_awake
from acme_city.agents.intake import find_duplicate
from acme_city.agents.runtime import run_agent
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import audit as audit_models
from acme_city.persistence.models import permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.models.source import SourceSnapshot
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.generated import (
    GENERATED_REFERENCE_PREFIX,
    MAX_GENERATED_PER_CALL,
    MAX_GENERATED_TOTAL,
    OUTCOME_KINDS,
    generate_outcomes,
    outcome_mix,
)
from acme_city.portal_intake.schemas import IntakeRecordCommand
from acme_city.portal_intake.service import IntakeService

REPO = Path(__file__).resolve().parents[2]
HASHES = REPO / "tests" / "regression" / "data" / "protected_fixture_hashes.json"

#: The site the walkthrough applies at.  The generated records never use it.
WALKTHROUGH_SITE = "400 Lantern Row, ACME City"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'generated.db'}",
            "ACME_SECRET_KEY": "generated-test-secret-value",
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


@pytest.fixture()
def document_root(tmp_path: Path) -> Path:
    """Return the directory the generated documents are written to."""
    return tmp_path / "documents"


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


def _walkthrough_pair(service: IntakeService, actor: ActorContext) -> tuple[str, str]:
    """Submit the same project twice at the walkthrough site."""
    facts = {
        "parcel_number": "ACME-P-1001",
        "submitted_parcel": "ACME-P-1001",
        "submitted_site_text": WALKTHROUGH_SITE,
        "project_description": "6 ft rear-yard wood privacy fence",
        "height_ft": 6,
        "setback_ft": 2,
        "structure_kind": "fence",
        "location": "side_rear",
    }
    ids = []
    for index in (1, 2):
        result = service.submit_record(
            IntakeRecordCommand(
                channel="portal",
                portal_reference=f"PORTAL-2026-WALKTHROUGH-{index:03d}",
                applicant={
                    "name": "Walkthrough Applicant",
                    "email": "walkthrough@example.invalid",
                },
                site_address=WALKTHROUGH_SITE,
                parcel_text="ACME-P-1001",
                permit_type_key="deck_fence",
                submitted_facts=facts,
            ),
            actor,
        )
        ids.append(result.application_id)
    return ids[0], ids[1]


# ------------------------------------------------------------------- the mix


def test_the_same_seed_and_nonce_build_the_same_records() -> None:
    first = generate_outcomes(7, 12, nonce="run1")
    second = generate_outcomes(7, 12, nonce="run1")
    assert [item.record for item in first] == [item.record for item in second]
    assert [item.outcome for item in first] == [item.outcome for item in second]


def test_a_different_nonce_builds_different_records() -> None:
    first = generate_outcomes(7, 12, nonce="run1")
    other = generate_outcomes(7, 12, nonce="run2")
    assert [item.record for item in first] != [item.record for item in other]
    assert [item.record.portal_reference for item in first] != [
        item.record.portal_reference for item in other
    ]


def test_a_different_seed_builds_different_records() -> None:
    first = generate_outcomes(7, 12, nonce="run1")
    other = generate_outcomes(8, 12, nonce="run1")
    assert [item.record for item in first] != [item.record for item in other]


@pytest.mark.parametrize("count", [1, 2, 5, 6, 7, 11, 12, 13, 19, 20])
def test_the_mix_is_exact(count: int) -> None:
    batch = generate_outcomes(3, count, nonce="run1")
    mix: dict[str, int] = {kind: 0 for kind in OUTCOME_KINDS}
    for item in batch:
        mix[item.outcome] += 1
    assert mix == outcome_mix(count)
    assert sum(mix.values()) == count
    assert set(mix) == set(OUTCOME_KINDS)


def test_the_references_carry_the_run_nonce() -> None:
    batch = generate_outcomes(3, 6, nonce="run7")
    assert [item.record.portal_reference for item in batch] == [
        f"{GENERATED_REFERENCE_PREFIX}-run7-{index:02d}" for index in range(1, 7)
    ]


def test_a_nonce_is_made_safe_for_a_portal_reference() -> None:
    batch = generate_outcomes(3, 1, nonce="a run/with spaces")
    reference = batch[0].record.portal_reference
    assert reference == f"{GENERATED_REFERENCE_PREFIX}-a-run-with-spaces-01"


def test_every_record_carries_the_facts_and_documents_its_type_asks_for() -> None:
    batch = generate_outcomes(3, 12, nonce="run1")
    for item in batch:
        record = item.record
        facts = record.submitted_facts
        assert facts["parcel_number"] and facts["submitted_site_text"]
        assert facts["project_description"]
        if record.permit_type_key == "deck_fence":
            assert facts["height_ft"] and facts["setback_ft"]
            types = {document.document_type for document in record.documents}
            assert types <= {"site_plan", "material_spec"}
            if item.outcome == "missing_document":
                assert "site_plan" not in types
            else:
                assert types == {"site_plan", "material_spec"}
        else:
            assert record.permit_type_key == "hvac"
            assert facts["contractor_license"]
            assert facts["contractor_license_expired_on"]
            assert [document.document_type for document in record.documents] == [
                "contractor_license_copy"
            ]


def test_the_repeat_of_a_case_is_the_case_before_it() -> None:
    batch = generate_outcomes(3, 12, nonce="run1")
    for index, item in enumerate(batch):
        if item.outcome != "duplicate_applicant":
            continue
        previous = batch[index - 1].record
        assert item.record.applicant.name == previous.applicant.name
        assert item.record.site_address == previous.site_address
        assert (
            item.record.submitted_facts["project_description"]
            == previous.submitted_facts["project_description"]
        )
        assert item.record.portal_reference != previous.portal_reference
        # The repeat arrived complete, so only the repeat itself is held.
        assert {document.document_type for document in item.record.documents} == {
            "site_plan",
            "material_spec",
        }


def test_the_generated_records_name_no_walkthrough_person_or_site() -> None:
    batch = generate_outcomes(3, 20, nonce="run1")
    for item in batch:
        name = item.record.applicant.name
        assert "Tamsin" not in name
        assert "Demo Applicant" not in name
        assert not item.record.site_address.startswith("400 Lantern Row")


def test_the_generated_records_name_none_of_the_d_parties() -> None:
    batch = generate_outcomes(3, 20, nonce="run1")
    names = {item.record.applicant.name for item in batch}
    for forbidden in (
        "Cedarline Coffee Roasters LLC",
        "Cedarline Coffee Works LLC",
        "Halcyon Framing and Build LLC",
        "Quarry Lane Imports LLC",
        "Ironvale Construction Group LLC",
    ):
        assert forbidden not in names


# -------------------------------------------------------------------- caps


@pytest.mark.parametrize("count", [0, -1, 21, 100, 1.5, True])
def test_one_call_is_capped_at_twenty(count: object) -> None:
    with pytest.raises(ValidationError):
        generate_outcomes(3, count, nonce="run1")  # type: ignore[arg-type]


def test_the_caps_are_twenty_per_call_and_two_hundred_in_all() -> None:
    assert MAX_GENERATED_PER_CALL == 20
    assert MAX_GENERATED_TOTAL == 200


@pytest.mark.parametrize("seed", [-1, 1.5, True])
def test_a_seed_that_is_not_a_whole_number_is_refused(seed: object) -> None:
    with pytest.raises(ValidationError):
        generate_outcomes(seed, 5, nonce="run1")  # type: ignore[arg-type]


# --------------------------------------------------------------- the cases


def test_the_records_become_cases_that_wait_for_the_intake_agent(
    seeded: Settings, document_root: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            results = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
        assert [result.status for result in results] == ["created"] * 6
        assert {result.triage_outcome for result in results} == {"awaiting_intake_agent"}
        with transaction(factory) as session:
            rows = session.execute(
                select(permit.Application).where(
                    permit.Application.id.in_(
                        [result.application_id for result in results]
                    )
                )
            ).scalars().all()
            assert len(rows) == 6
            assert {row.status for row in rows} == {"submitted"}
            # A generated case waits for a person: it carries no scenario id
            # and no run of the intake agent.
            assert {row.scenario_id for row in rows} == {None}
            runs = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id.in_(
                        [result.application_id for result in results]
                    )
                )
            ).scalars().all()
            assert runs == []
            assert is_awake(session, "intake") is False
    finally:
        factory.dispose()


def test_a_generated_case_writes_its_audit_rows(
    seeded: Settings, document_root: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            results = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
            session.flush()
            events = session.execute(
                select(audit_models.AuditEvent).where(
                    audit_models.AuditEvent.action == "intake.generate"
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].actor_id == "persona_city_administrator"
            assert len(events[0].references) == 6
            submits = session.execute(
                select(audit_models.AuditEvent).where(
                    audit_models.AuditEvent.action == "intake.record.submit"
                )
            ).scalars().all()
            assert len(submits) == 6
            assert {event.target_id for event in submits} == {
                result.application_id for result in results
            }
    finally:
        factory.dispose()


def test_the_intake_agent_finds_the_repeat_and_the_missing_document(
    seeded: Settings, document_root: Path
) -> None:
    """Each kind of the mix reaches the place it was built for."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            results = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
            control = AgentControlService(session)
            control.ensure_defaults()
            state = control.state(agent_models.AGENT_INTAKE)
            assert state is not None
            state.mode = agent_models.AGENT_AWAKE
            session.flush()
            observed = []
            for outcome, result in zip(OUTCOME_KINDS, results):
                application = session.get(permit.Application, result.application_id)
                assert application is not None
                run_agent(
                    session,
                    application=application,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by="persona_agent_operator",
                    settings=seeded,
                )
                session.flush()
                findings = session.execute(
                    select(permit.ApplicationFinding).where(
                        permit.ApplicationFinding.application_id == result.application_id
                    )
                ).scalars().all()
                observed.append(
                    (
                        outcome,
                        application.status,
                        sorted(finding.finding_type for finding in findings),
                    )
                )
        assert observed == [
            ("clean_approve", "ready_for_review", []),
            ("missing_document", "needs_information", ["duplicate", "missing_document"]),
            ("duplicate_applicant", "needs_information", ["duplicate"]),
            ("rule_breach", "ready_for_review", []),
            ("expired_contractor", "ready_for_review", []),
            ("borderline", "ready_for_review", []),
        ]
    finally:
        factory.dispose()


def test_a_named_run_of_a_scenario_creates_new_cases(
    seeded: Settings, document_root: Path
) -> None:
    """A repeat of a scenario under a new name creates new cases."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            first = service.simulate(
                "fence-conforming-rear", count=None, actor=administrator, nonce="run1"
            )
            second = service.simulate(
                "fence-conforming-rear", count=None, actor=administrator, nonce="run2"
            )
        assert [result.status for result in first] == ["created"]
        assert [result.status for result in second] == ["created"]
        assert first[0].portal_reference != second[0].portal_reference
        assert first[0].application_id != second[0].application_id
    finally:
        factory.dispose()


def test_a_run_without_a_name_repeats_the_scenario(
    seeded: Settings, document_root: Path
) -> None:
    """The scenario still builds the references it always built."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            first = service.simulate(
                "fence-conforming-rear", count=None, actor=administrator
            )
            second = service.simulate(
                "fence-conforming-rear", count=None, actor=administrator
            )
        assert [result.status for result in first] == ["created"]
        assert [result.status for result in second] == ["duplicate"]
        assert first[0].portal_reference == second[0].portal_reference
        assert first[0].application_id == second[0].application_id
    finally:
        factory.dispose()


def test_a_second_identical_call_returns_duplicates(
    seeded: Settings, document_root: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            first = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            second = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
        assert [result.status for result in first] == ["created"] * 6
        assert [result.status for result in second] == ["duplicate"] * 6
        assert [result.application_id for result in first] == [
            result.application_id for result in second
        ]
    finally:
        factory.dispose()


def test_a_different_nonce_creates_new_cases(
    seeded: Settings, document_root: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            first = service.generate_cases(
                seed=7, count=6, nonce="run1", actor=administrator
            )
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            second = service.generate_cases(
                seed=7, count=6, nonce="run2", actor=administrator
            )
        assert [result.status for result in second] == ["created"] * 6
        assert not set(result.application_id for result in first) & set(
            result.application_id for result in second
        )
    finally:
        factory.dispose()


def test_the_total_cap_is_refused(seeded: Settings, document_root: Path) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            # The demonstration already holds the whole allowance.
            for index in range(MAX_GENERATED_TOTAL):
                session.add(
                    SourceSnapshot(
                        source_snapshot_id=f"snapshot_generated_{index:04d}",
                        source_system_id="intake_portal",
                        source_dataset_id="submitted_applications",
                        source_record_id=(
                            f"{GENERATED_REFERENCE_PREFIX}-held-{index:04d}"
                        ),
                        source_record_version="1",
                        payload_hash="0" * 64,
                        ingested_at=datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
                        correlation_id=f"correlation_generated_{index:04d}",
                    )
                )
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            with pytest.raises(ValidationError):
                service.generate_cases(
                    seed=7, count=1, nonce="run1", actor=administrator
                )
    finally:
        factory.dispose()


def test_a_generated_case_is_never_a_duplicate_of_a_seeded_party(
    seeded: Settings, document_root: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            results = service.generate_cases(
                seed=7, count=12, nonce="run1", actor=administrator
            )
            parties = session.execute(select(registry.Party)).scalars().all()
            names = {party.display_name for party in parties}
            assert names
            for result in results:
                application = session.get(permit.Application, result.application_id)
                assert application is not None
                facts = dict(application.submitted_facts or {})
                assert facts["applicant_name"] not in names
                assert application.applicant_party_id is None
    finally:
        factory.dispose()


def test_the_walkthrough_duplicate_is_still_flagged(
    seeded: Settings, document_root: Path
) -> None:
    """A second application for the same project is still a duplicate."""
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            administrator = context_for(session, "persona_city_administrator")
            service = IntakeService(session, settings=seeded, document_root=document_root)
            service.generate_cases(seed=7, count=12, nonce="run1", actor=administrator)
            walkthrough = _walkthrough_pair(service, administrator)
        with transaction(factory) as session:
            original = session.get(permit.Application, walkthrough[0])
            repeat = session.get(permit.Application, walkthrough[1])
            assert original is not None and repeat is not None
            found = find_duplicate(session, repeat)
            assert found is not None
            assert found.id == original.id
    finally:
        factory.dispose()


def test_the_protected_inputs_are_untouched() -> None:
    recorded = json.loads(HASHES.read_text(encoding="utf-8"))
    changed = [
        relative
        for relative, digest in recorded["files"].items()
        if hashlib.sha256((REPO / relative).read_bytes()).hexdigest() != digest
    ]
    assert changed == []

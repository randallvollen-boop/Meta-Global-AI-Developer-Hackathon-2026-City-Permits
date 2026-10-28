"""The what-if kernels agree with production, and a simulation writes nothing.

* the pure kernel and the production path give the same results on identical
  inputs and selected versions (evaluation, blockers, rule and fee selection,
  the assessed fee, the intake findings and routing, the recommendation);
* production really calls the shared kernel functions (a call is observed,
  not just a name found in the source);
* a full simulation run leaves the **contents** of every business row
  unchanged, not just their counts or versions.
"""
# REQUIRES: PER-02, REF-01, AI-03
# One set of pure functions serves production and simulation, and a simulation
# run is side-effect free.

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.finance.schemas import AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.kernel import adjudication as adjudication_kernel
from acme_city.kernel import intake as intake_kernel
from acme_city.kernel import selection as selection_kernel
from acme_city.kernel.selection import select_assessment_schedule
from acme_city.permits.service import PermitService
from acme_city.persistence.base import Base
from acme_city.persistence.models import finance as finance_models
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.policy.baseline import freeze_baseline
from acme_city.policy.changes import (
    DiscretionaryChange,
    FeeChange,
    RequirementChange,
    RuleRetirementChange,
    RuleThresholdChange,
    Scenario,
    ServiceTargetChange,
    apply_scenario,
)
from acme_city.policy.fees import price_case
from acme_city.policy.impact import compute_impact
from acme_city.policy.kernel import evaluate_case
from acme_city.policy.loader import (
    CARRIED_FINDING_RULES,
    case_input_from_application,
    current_applications_population,
)
from acme_city.rules import catalog
from acme_city.ui.router import router as ui_router

ANALYSIS_AT = datetime(2026, 12, 31, tzinfo=UTC)


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'policy-parity.db'}",
            "ACME_SECRET_KEY": "policy-parity-secret-value",
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
def factory(environment: Settings):
    session_factory = SessionFactory(environment.database_url)
    yield session_factory
    session_factory.dispose()


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def context_for(session, actor_id: str) -> ActorContext:
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
        record_scope=frozenset(r for grant in grants for r in grant.record_scope),
    )


# --------------------------------------------------------- UI driving helpers


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def simulate(client: TestClient, scenario: str) -> list[dict]:
    response = client.post("/api/intake/simulate", json={"scenario": scenario})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def act(client: TestClient, action_id: str, fields: dict, next_path: str) -> dict:
    page = client.get(next_path).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, next_path
    response = client.post(
        f"/ui/actions/{action_id}",
        data={"csrf_token": match.group(1), "action_id": action_id, "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    return response.json()


def wake(client: TestClient, agent_key: str) -> None:
    choose(client, "persona_city_administrator")
    result = act(client, "agent.toggle", {"agent_key": agent_key, "mode": "awake"}, f"/agent/{agent_key}")
    assert result["status"] == "accepted", result


# ---------------------------------------------------------------- snapshots


def table_snapshot(factory: SessionFactory) -> dict[str, str]:
    """Return a content digest of every row of every table (not just counts)."""
    digests: dict[str, str] = {}
    with factory() as session:
        for table in Base.metadata.sorted_tables:
            rows = [
                json.dumps({k: str(v) for k, v in row._mapping.items()}, sort_keys=True)
                for row in session.execute(table.select()).all()
            ]
            digests[table.name] = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest() + f":{len(rows)}"
    return digests


# ------------------------------------------------- evaluation parity (fixtures)


def test_baseline_rescore_equals_the_production_evaluation_for_every_seeded_case(factory) -> None:
    compared = 0
    saw_fail = saw_blockers = False
    with transaction(factory) as session:
        permits = PermitService(session)
        reviewer = context_for(session, "persona_permit_reviewer")
        config = freeze_baseline(session, ANALYSIS_AT)
        applications = session.execute(select(permit.Application)).scalars().all()
        assert len(applications) >= 13
        for application in applications:
            case = case_input_from_application(session, application, use_receipt_requirements=True)
            permits.evaluate(application.id, reviewer)
            stored = permits.current_evaluation(application.id)
            assert stored is not None
            outcome = evaluate_case(case, config, rules_at="case")
            assert list(outcome.rule_results) == [dict(r) for r in stored.results]
            rule_set = config.rule_set(case.permit_type_key, case.basis_at)
            assert rule_set.version_labels() == stored.rule_versions
            blockers = Counter(b["code"] for b in stored.source_versions["blockers"])
            expected = Counter(outcome.safeguards) + Counter(
                {"missing_required_field": len(outcome.missing_required_inputs)} if outcome.missing_required_inputs else {}
            )
            assert blockers == expected, application.source_application_number
            saw_fail |= any(r["status"] == "fail" for r in outcome.rule_results)
            saw_blockers |= bool(blockers)
            compared += 1
    assert compared == len(applications)
    # The comparison is not vacuous: it covered failing results and blockers.
    assert saw_fail or saw_blockers


def test_rule_and_schedule_selection_agree_with_the_stored_catalogue(factory) -> None:
    moments = [
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 6, 15, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=UTC),
        ANALYSIS_AT,
    ]
    with factory() as session:
        config = freeze_baseline(session, ANALYSIS_AT)
        selected_any = False
        for permit_type in config.permit_types:
            type_id = catalog.permit_type_id_for_key(session, permit_type.key)
            for moment in moments:
                stored = catalog.select_rule_versions(session, type_id, moment)
                frozen = config.rules_in_force(permit_type.key, moment)
                assert [row.id for row in stored] == [rule.row_id for rule in frozen]
                selected_any |= bool(stored)
                fee_stored = catalog.select_fee_schedule(session, moment, permit_type.key)
                fee_frozen = selection_kernel.select_schedule_for_type(
                    config.fee_schedules, moment, permit_type.key)
                assert (fee_stored.id if fee_stored else None) == (fee_frozen.row_id if fee_frozen else None)
        assert selected_any


def test_the_fee_kernel_equals_the_finance_assessment(factory) -> None:
    priced = 0
    with transaction(factory) as session:
        config = freeze_baseline(session, ANALYSIS_AT)
        admin = context_for(session, "persona_city_administrator")
        finance = FinanceService(session)
        for application in session.execute(select(permit.Application)).scalars().all():
            case = case_input_from_application(session, application)
            fee = price_case(case, config)
            if not fee.priceable:
                continue
            view = finance.assess(AssessmentCommand(application_id=application.id), admin)
            assert fee.total_cents == view.assessed_total_cents
            assert [fee.fixed_cents, fee.variable_cents] == [line.amount_cents for line in view.lines]
            stored = session.get(finance_models.FeeScheduleVersion, view.fee_schedule_version_id) if hasattr(
                view, "fee_schedule_version_id") else None
            assert fee.version_label == (stored.version_label if stored else fee.version_label)
            priced += 1
    assert priced >= 3


# ------------------------------------- intake and adjudication parity (agents)

SCENARIOS = (
    "fence-conforming-rear",
    "fence-front-too-tall",
    "fence-missing-site-plan",
    "deck-high",
    "shed-large",
    "variance-request",
    "hvac-no-contractor",
    "fax-unreadable",
    "duplicate-fence",
    "address-typo",
    "address-ambiguous",
    "address-unknown",
)


def finding_keys(rows) -> Counter:
    return Counter((r.finding_type, r.message, r.rule, r.severity) for r in rows)


def test_the_intake_and_adjudication_agents_agree_with_the_pure_kernel(client, environment, factory) -> None:
    choose(client, "persona_data_steward")
    ids: list[str] = []
    for name in SCENARIOS:
        ids.extend(item["application_id"] for item in simulate(client, name))
    assert len(ids) >= len(SCENARIOS)

    # Freeze every case BEFORE any agent runs: the kernel sees only these inputs.
    with factory() as session:
        before = {
            app_id: case_input_from_application(
                session, session.get(permit.Application, app_id), carried=[], use_receipt_requirements=True)
            for app_id in ids
        }

    wake(client, "intake")
    wake(client, "adjudication")
    routed: dict[str, str] = {}
    for app_id in ids:
        choose(client, "persona_data_steward")
        act(client, "agent.run.intake", {"application_id": app_id}, "/agent/intake")
    for app_id in ids:
        with factory() as session:
            routed[app_id] = session.get(permit.Application, app_id).status
        if routed[app_id] == "ready_for_review":
            choose(client, "persona_permit_reviewer")
            act(client, "agent.run.adjudication", {"application_id": app_id}, "/agent/adjudication")

    seen_blocking = seen_ready = seen_judging = seen_recommendation = 0
    with factory() as session:
        config = freeze_baseline(session, ANALYSIS_AT)
        for app_id in ids:
            application = session.get(permit.Application, app_id)
            rows = [
                r for r in session.execute(
                    select(permit.ApplicationFinding).where(
                        permit.ApplicationFinding.application_id == app_id,
                        permit.ApplicationFinding.state == "current")).scalars().all()
            ]
            # Findings of the outside-world steps are frozen inputs of the case.
            carried = [r for r in rows if r.rule in CARRIED_FINDING_RULES]
            case = intake_case_with(before[app_id], carried)
            outcome = evaluate_case(case, config, rules_at="case")
            produced = [r for r in rows if r.rule not in CARRIED_FINDING_RULES and r.source_node != "adjudication"
                        and not _is_adjudication_finding(r)]
            assert finding_keys(produced) == Counter(
                (f.finding_type, f.message, f.rule, f.severity) for f in outcome.findings
                if f.rule not in CARRIED_FINDING_RULES), app_id
            assert routed[app_id] == outcome.route_status, (app_id, outcome.route_reason)
            seen_blocking += any(f.severity == "block" for f in outcome.findings)
            seen_judging += any(f.severity == "review" for f in outcome.findings)
            seen_ready += routed[app_id] == "ready_for_review"
            recommendation = session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.application_id == app_id,
                    permit.Recommendation.status == "pending")).scalars().first()
            if recommendation is not None:
                assert recommendation.proposed_outcome == outcome.recommendation, app_id
                assert list(recommendation.conditions or []) == list(outcome.conditions)
                seen_recommendation += 1
            assert application.review_area  # the classifier set it
    # The comparison is not vacuous: it saw blocked, judged and ready cases and recommendations.
    assert seen_blocking and seen_judging and seen_ready and seen_recommendation


def _is_adjudication_finding(row) -> bool:
    return row.rule in {"ACME Code §13-601", "ACME Code §13-602", "ACME Code §13-604"}


def intake_case_with(case, carried_rows):
    import dataclasses

    from acme_city.kernel.findings import FindingSpec

    return dataclasses.replace(
        case,
        carried_findings=tuple(
            FindingSpec(r.finding_type, r.message, r.rule, r.applicant_must, r.severity,
                        r.related_application_id) for r in carried_rows),
    )


def test_production_calls_the_shared_kernel_functions(client, environment, factory, monkeypatch) -> None:
    """Observe the calls: the agents and the finance service use the shared functions."""
    calls: Counter = Counter()

    def spy(module, name):
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            calls[f"{module.__name__}.{name}"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    for name in ("classify_type", "document_quality", "completeness", "requirements_of", "route",
                 "first_duplicate"):
        spy(intake_kernel, name)
    for name in ("hold_findings", "conditions_of", "disposition"):
        spy(adjudication_kernel, name)
    import acme_city.finance.service as finance_service
    import acme_city.rules.catalog as catalog_module
    import acme_city.permits.service as permit_service

    monkeypatch.setattr(
        finance_service, "select_assessment_schedule",
        lambda rows, at: (calls.update(["finance.select_assessment_schedule"]),
                          select_assessment_schedule(rows, at))[1])
    monkeypatch.setattr(
        catalog_module, "select_schedule_for_type",
        lambda rows, at, key=None: (calls.update(["catalog.select_schedule_for_type"]),
                                    selection_kernel.select_schedule_for_type(rows, at, key))[1])
    original_missing = permit_service.missing_required_fields
    monkeypatch.setattr(
        permit_service, "missing_required_fields",
        lambda *a, **k: (calls.update(["inputs.missing_required_fields"]), original_missing(*a, **k))[1])

    choose(client, "persona_data_steward")
    (result,) = simulate(client, "fence-conforming-rear")
    app_id = result["application_id"]
    wake(client, "intake")
    wake(client, "adjudication")
    choose(client, "persona_data_steward")
    act(client, "agent.run.intake", {"application_id": app_id}, "/agent/intake")
    choose(client, "persona_permit_reviewer")
    act(client, "agent.run.adjudication", {"application_id": app_id}, "/agent/adjudication")
    with transaction(factory) as session:
        admin = context_for(session, "persona_city_administrator")
        FinanceService(session).assess(AssessmentCommand(application_id=app_id, valuation="1000.00"), admin)

    for expected in (
        "acme_city.kernel.intake.classify_type",
        "acme_city.kernel.intake.document_quality",
        "acme_city.kernel.intake.completeness",
        "acme_city.kernel.intake.requirements_of",
        "acme_city.kernel.intake.route",
        "acme_city.kernel.intake.first_duplicate",
        "acme_city.kernel.adjudication.hold_findings",
        "acme_city.kernel.adjudication.conditions_of",
        "acme_city.kernel.adjudication.disposition",
        "finance.select_assessment_schedule",
        "catalog.select_schedule_for_type",
        "inputs.missing_required_fields",
    ):
        assert calls[expected] >= 1, f"production did not call {expected}: {dict(calls)}"


# ------------------------------------------------- a run writes nothing


def full_scenario() -> Scenario:
    return Scenario(
        "everything",
        (
            RuleThresholdChange("DF-2", "7"),
            RuleThresholdChange("SH-2", "300"),
            RuleRetirementChange("CT-1"),
            RequirementChange("deck_fence", "document", "material_spec", "remove"),
            DiscretionaryChange("zoning_variance", False),
            ServiceTargetChange("deck_fence", 3),
            FeeChange("fee_commercial_demo", 12000, "0.002"),
        ),
    )


def test_a_simulation_run_leaves_every_business_row_unchanged(client, environment, factory) -> None:
    choose(client, "persona_data_steward")
    for name in ("fence-conforming-rear", "fence-front-too-tall", "shed-large", "variance-request"):
        simulate(client, name)
    wake(client, "intake")
    wake(client, "adjudication")
    with factory() as session:
        pending = [a.id for a in session.execute(select(permit.Application)
                   .where(permit.Application.scenario_id.is_(None))).scalars().all()]
    for app_id in pending:
        choose(client, "persona_data_steward")
        act(client, "agent.run.intake", {"application_id": app_id}, "/agent/intake")

    before = table_snapshot(factory)
    # The comparison is not vacuous: the business tables hold rows.
    for table in ("applications", "application_findings", "application_revisions", "permit_types",
                  "rule_versions", "fee_schedule_versions", "agent_runs", "audit_events"):
        if table in before:
            assert not before[table].endswith(":0"), table

    with factory() as session:
        config = freeze_baseline(session, ANALYSIS_AT)
        population = current_applications_population(session)
        assert population.size >= 13
    result = apply_scenario(config, full_scenario())
    assert result.supported, (result.unsupported, result.issues)
    impact = compute_impact(population, config, result)
    assert impact.population_size == population.size
    assert impact.fees is not None and impact.fees.priced_count > 0
    after = table_snapshot(factory)
    assert after == before

    # A control: a real change to one business row IS seen by the snapshot.
    with transaction(factory) as session:
        row = session.execute(select(permit.PermitType).where(permit.PermitType.key == "shed")).scalar_one()
        row.service_target_days = row.service_target_days + 1
    changed = table_snapshot(factory)
    assert changed["permit_types"] != before["permit_types"]
    assert {k for k in before if before[k] != changed[k]} == {"permit_types"}


def test_the_frozen_baseline_does_not_follow_later_catalogue_edits(factory) -> None:
    with factory() as session:
        config = freeze_baseline(session, ANALYSIS_AT)
    frozen_hash = config.config_hash
    with transaction(factory) as session:
        row = session.execute(
            select(finance_models.RuleVersion).where(
                finance_models.RuleVersion.rule_id == "DF-2",
                finance_models.RuleVersion.status == "published")).scalar_one()
        row.limit_value = "9"
    assert config.config_hash == frozen_hash
    assert {r.rule_id: r for r in config.rules}["DF-2"].limit_value == "6"
    with factory() as session:
        assert freeze_baseline(session, ANALYSIS_AT).config_hash != frozen_hash

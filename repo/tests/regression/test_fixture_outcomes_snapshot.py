"""The outcomes of the controlled scenarios after a reset are unchanged.

``data/fixture_outcomes.json`` records, after ``reset_demo``, the row count of
every seeded table and, for each D01-D11 application, its status, its seeded
decision and reason codes, its fee total and the outcome of the deterministic
rules.  The DF-1/DF-2 entries are the two fence scenarios of the intake
simulator (front yard too tall, rear yard within the limit), evaluated against
the deck-and-fence rules with the fee their schedule assesses.

Tables a later lane adds are excluded by name: each lane lists its tables in
``tests/support/schema_groups_<lane>.py``, which ``test_schema.py`` merges too.
The actor, role and grant tables are excluded as well, because lanes add
actors and change grants on purpose; the grant snapshot with
``persona_grant_deltas.json`` guards those instead.
The rules are evaluated in a session that is rolled back, so nothing is written.

A lane never edits the snapshot to make this pass.  A deliberate, reviewed
change of an outcome is recorded by running this module as a script.
"""
# REQUIRES: D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11
# A reset seeds the same rows, and every controlled scenario keeps its status,
# decision, reason codes, fee and rule outcome.

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.finance.calculator import calculate_fee, to_cents
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo, seeded_row_counts
from acme_city.kernel.inputs import build_inputs
from acme_city.permits.service import PermitService
from acme_city.persistence.models import finance, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.scenarios import build_scenario
from acme_city.rules.evaluator import evaluate, overall_status
from acme_city.rules.service import RuleCatalogService

SNAPSHOT = Path(__file__).resolve().parent / "data" / "fixture_outcomes.json"
SUPPORT = Path(__file__).resolve().parents[1] / "support"

#: The lane files whose tables are excluded from the row counts.
LANE_SCHEMA_GROUP_FILES: tuple[str, ...] = (
    "schema_groups_operator.py",
    "schema_groups_autolink.py",
)

#: The actor, role and grant tables, which lanes change on purpose.
ACTOR_TABLES: frozenset[str] = frozenset(
    {"actors", "actor_roles", "actor_grants", "roles", "role_permissions"}
)

#: The scenarios whose applications are recorded.
SCENARIOS = tuple(f"D{number:02d}" for number in range(1, 12))

#: The fence scenarios of the DF-1 and DF-2 rules.
FENCE_SCENARIOS = {"DF-1": "fence-front-too-tall", "DF-2": "fence-conforming-rear"}

#: The persona whose grants evaluate an application.
EVALUATOR = "persona_permit_reviewer"


def lane_tables() -> set[str]:
    """Return the tables the lanes list in their schema groups."""
    tables: set[str] = set()
    for file_name in LANE_SCHEMA_GROUP_FILES:
        path = SUPPORT / file_name
        spec = importlib.util.spec_from_file_location(f"_acme_outcomes_{path.stem}", path)
        assert spec is not None and spec.loader is not None, path
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for group in module.SCHEMA_GROUPS.values():
            tables.update(group)
    return tables


def _actor(session: Session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record for grant in grants for record in grant.record_scope),
    )


def _applications(session: Session) -> dict[str, Any]:
    rows = session.execute(
        select(permit.Application)
        .where(permit.Application.scenario_id.in_(SCENARIOS))
        .order_by(permit.Application.id)
    ).scalars().all()
    observed: dict[str, Any] = {}
    for row in rows:
        decisions = session.execute(
            select(permit.Decision)
            .where(permit.Decision.application_id == row.id, permit.Decision.status == "current")
        ).scalars().all()
        assessments = session.execute(
            select(finance.Assessment)
            .where(
                finance.Assessment.application_id == row.id,
                finance.Assessment.status == "current",
            )
        ).scalars().all()
        observed[row.id] = {
            "scenario_id": row.scenario_id,
            "status": row.status,
            "decision": sorted(decision.outcome for decision in decisions) or None,
            "reason_codes": sorted(
                decision.reason_code for decision in decisions if decision.reason_code
            ),
            "fee_total_cents": (
                sum(a.assessed_total_cents for a in assessments) if assessments else None
            ),
        }
    actor = _actor(session, EVALUATOR)
    for application_id, entry in observed.items():
        view = PermitService(session).evaluate(application_id, actor)
        entry["rule_outcome"] = view.outcome
        entry["rule_results"] = [[result.rule_id, result.status] for result in view.results]
    return observed


def _fence_rules(session: Session) -> dict[str, Any]:
    catalog = RuleCatalogService(session)
    observed: dict[str, Any] = {}
    for rule_id, scenario in FENCE_SCENARIOS.items():
        (record,) = build_scenario(scenario)
        inputs = build_inputs(record.submitted_facts)
        rule_set = catalog.resolve("executable", record.permit_type_key, record.received_at)
        results = evaluate(inputs, rule_set)
        schedule = catalog.resolve("fee_schedule", record.permit_type_key, record.received_at)
        fee = calculate_fee(
            schedule.fee_schedule.definition or {},
            to_cents(record.submitted_facts["valuation"]),
            currency=schedule.fee_schedule.currency,
        )
        observed[rule_id] = {
            "scenario": scenario,
            "rule_outcome": overall_status(results),
            "rule_results": [[result.rule_id, result.status] for result in results],
            "fee_total_cents": fee.total_cents,
        }
    return observed


def observe(directory: Path) -> dict[str, Any]:
    """Reset a demo database in ``directory`` and return its outcomes."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / 'outcomes.db'}",
            "ACME_SECRET_KEY": "fixture-outcomes-secret-value",
        },
        key_file=directory / "missing.env",
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
        excluded = lane_tables() | ACTOR_TABLES
        session = factory()
        try:
            counts = {
                table: count
                for table, count in sorted(seeded_row_counts(session).items())
                if table not in excluded
            }
            applications = _applications(session)
            fence = _fence_rules(session)
        finally:
            session.rollback()
            session.close()
    finally:
        factory.dispose()
    return {"seeded_row_counts": counts, "applications": applications, "fence_rules": fence}


@pytest.fixture(scope="module")
def observed(tmp_path_factory) -> dict[str, Any]:
    return observe(tmp_path_factory.mktemp("outcomes"))


@pytest.fixture(scope="module")
def recorded() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_the_seeded_row_counts_are_unchanged(observed, recorded) -> None:
    assert observed["seeded_row_counts"] == recorded["seeded_row_counts"]
    assert not ACTOR_TABLES & set(recorded["seeded_row_counts"])


def test_every_controlled_scenario_keeps_its_outcome(observed, recorded) -> None:
    assert observed["applications"] == recorded["applications"]
    # D10 is an unowned feed with no application; every other scenario has one.
    assert {entry["scenario_id"] for entry in recorded["applications"].values()} == (
        set(SCENARIOS) - {"D10"}
    )


def test_the_fence_rules_keep_their_outcomes(observed, recorded) -> None:
    assert observed["fence_rules"] == recorded["fence_rules"]
    assert recorded["fence_rules"]["DF-1"]["rule_outcome"] == "fail"
    assert recorded["fence_rules"]["DF-2"]["rule_outcome"] == "pass"


def _rewrite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        snapshot = {
            "note": (
                "Outcomes after reset_demo. Regenerate only for a deliberate, reviewed "
                "change: python tests/regression/test_fixture_outcomes_snapshot.py"
            ),
            **observe(Path(directory)),
        }
    SNAPSHOT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    _rewrite()
    sys.exit(0)

#!/usr/bin/env python3
"""Write the replay fixtures of the what-if policy agent (policy 3).

The fixtures of this script are **deterministic, labelled demonstration
fixtures**.  They are not recordings of a Muse answer, they were not produced
by a provider, and they are never presented as one.

Each fixture is written for one exact run or one exact question:

* a briefing or explanation fixture is keyed by the content of a what-if run:
  the hash of its population, the configuration hashes of the baseline and of
  the scenario (without the wall-clock analysis moment, which the run content
  hash includes), the changes and the typed facts;
* a proposal fixture is keyed by the normalized question and the hash of the
  published configuration.

The script re-creates the demonstration runs in a scratch database with a fixed
clock, writes the sentences from the typed facts of those runs (so no figure
is typed by hand), and proves with the real validator that every good fixture
passes and that the deliberately failing ones fail.

Run it after a change of the published rules, the permit types, the synthetic
generator or the engine::

    uv run python scripts/build_policy_assist_fixtures.py

Use ``--check`` to prove that the committed fixtures are the ones the current
rules produce, without writing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from acme_city.auth.context import ActorContext  # noqa: E402
from acme_city.auth.permissions import PermissionResolver  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.fixtures.loader import FixtureBundle  # noqa: E402
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo  # noqa: E402
from acme_city.muse.schemas import (  # noqa: E402
    POLICY_BRIEF_PROMPT_VERSION,
    POLICY_BRIEF_SCHEMA_VERSION,
    POLICY_BRIEF_TASK,
    POLICY_PROPOSE_PROMPT_VERSION,
    POLICY_PROPOSE_SCHEMA_VERSION,
    POLICY_PROPOSE_TASK,
)
from acme_city.persistence.models.governance import DemoEnvironment  # noqa: E402
from acme_city.persistence.session import (  # noqa: E402
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.policy import muse  # noqa: E402
from acme_city.policy import muse_validation as validation  # noqa: E402
from acme_city.policy import views  # noqa: E402
from acme_city.policy.baseline import freeze_baseline  # noqa: E402
from acme_city.policy.service import PolicyService  # noqa: E402

#: The version of the fixture set of this demonstration.
FIXTURE_VERSION = "2026.10.28-1"

#: The date the fixture set was written for, and the fixed clock of the builder.
RECORDED_AT = "2026-10-28T12:00:00Z"
BUILD_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

ADMIN = "persona_city_administrator"

#: The note every fixture carries.
NOTE = (
    "A deterministic, labelled demonstration fixture of the what-if policy agent. It was "
    "written for this demonstration from the typed facts of one run (or the published "
    "configuration for a proposal); it is not a recording of a Muse answer and it is never "
    "presented as one."
)

FENCE_QUESTION = "What if the side and rear yard fence limit were 7 ft?"
NO_PERMIT_QUESTION = "What if no permit were required for a shed?"


# ----------------------------------------------------------------- sentences


def claim(fact: Any) -> dict[str, Any]:
    """Return the claim that repeats one typed fact exactly."""
    return {
        "fact_id": fact.fact_id,
        "value": str(fact.value),
        "unit": fact.unit,
        "direction": fact.direction,
        "population": fact.population,
        "baseline_id": fact.baseline_id,
        "scenario_id": fact.scenario_id,
    }


def rule_ref(sources: dict[tuple[str, str, str], Any], configuration: str, rule_id: str) -> dict[str, Any]:
    """Return the rule_ref that repeats one versioned rule source exactly."""
    for (name, rid, version), source in sorted(sources.items()):
        if name == configuration and rid == rule_id:
            return {
                "rule_id": rid,
                "version": version,
                "citation": source.citation,
                "limit_value": source.limit_value,
                "unit": source.unit,
                "configuration": name,
            }
    raise SystemExit(f"no versioned rule {rule_id!r} in the {configuration} configuration")


def sentence(text: str, facts: list[Any] = (), refs: list[dict[str, Any]] = ()) -> dict[str, Any]:  # type: ignore[assignment]
    return {"text": text, "claims": [claim(f) for f in facts], "rule_refs": list(refs)}


def section(key: str, sentences: list[dict[str, Any]], question: str = "") -> dict[str, Any]:
    return {"section": key, "question": question, "sentences": sentences}


def fence_brief(facts: dict[str, Any], sources: dict[tuple[str, str, str], Any], purpose: str) -> dict[str, Any]:
    """Return the briefing (or explanation) of the 6 to 7 ft fence what-if."""
    f = facts
    df2_before = rule_ref(sources, "baseline", "DF-2")
    df2_after = rule_ref(sources, "scenario", "DF-2")
    df1 = rule_ref(sources, "baseline", "DF-1")
    size, changed = f["population.size"].value, f["cases.changed"].value
    summary = section(
        "summary",
        [
            sentence(
                f"This what-if was tested on synthetic data: {size} generated cases, not real applications.",
                [f["population.size"]],
            ),
            sentence(
                "It raises the side and rear yard fence height limit from "
                f"{df2_before['limit_value']} ft to {df2_after['limit_value']} ft (ACME Code §14-306).",
                [],
                [df2_before, df2_after],
            ),
        ],
    )
    effects = section(
        "key_effects",
        [
            sentence(
                f"{changed} of the {size} cases would get a different result, and every one of them "
                f"moves in the relaxed direction ({f['cases.relaxed'].value} cases).",
                [f["cases.changed"], f["population.size"], f["cases.relaxed"]],
            ),
            sentence(
                f"Recommendations to approve would rise from {f['outcome.approve.baseline'].value} to "
                f"{f['outcome.approve.scenario'].value} cases.",
                [f["outcome.approve.baseline"], f["outcome.approve.scenario"]],
            ),
            sentence(
                f"Recommendations to deny would fall from {f['outcome.deny.baseline'].value} to "
                f"{f['outcome.deny.scenario'].value} cases, which is {f['outcome.deny.change'].value} fewer.",
                [f["outcome.deny.baseline"], f["outcome.deny.scenario"], f["outcome.deny.change"]],
            ),
            sentence(
                f"Cases held for a person are unchanged at {f['holds.scenario'].value}, and cases that need "
                f"information are unchanged at {f['needs.scenario'].value}.",
                [f["holds.scenario"], f["needs.scenario"]],
            ),
        ],
    )
    sections = [summary, effects]
    if purpose == "brief":
        sections += [
            section(
                "risks",
                [
                    sentence(
                        f"{f['safety.count'].value} cases would stop failing the fence height rule; each one is "
                        "listed on the results screen so a person can judge the risk.",
                        [f["safety.count"]],
                    ),
                    sentence(
                        "The engine counts what the rules would recommend; it does not measure how a taller fence "
                        "affects neighbours."
                    ),
                ],
            ),
            section(
                "protected",
                [
                    sentence(
                        "A person still decides every case, and the identity, parcel, credential, finance and "
                        "missing-input safeguards are not changed by this what-if."
                    ),
                    sentence("The front yard limit of ACME Code §14-305 is not part of this what-if.", [], [df1]),
                ],
            ),
            section(
                "question",
                [
                    sentence(
                        f"{changed} of the {size} synthetic cases get a different result.",
                        [f["cases.changed"], f["population.size"]],
                    )
                ],
                "How many cases does this change?",
            ),
            section(
                "question",
                [sentence("No. Holds, missing-information checks and the person who decides stay as they are.")],
                "Does it remove a safeguard?",
            ),
        ]
    return {
        "title": "What-if briefing: side and rear yard fence height limit"
        if purpose == "brief"
        else "Explanation of the fence height what-if",
        "sections": sections,
        "cannot_brief": False,
        "reason": "",
    }


def shed_brief_that_fails(facts: dict[str, Any], sources: dict[tuple[str, str, str], Any]) -> dict[str, Any]:
    """Return a briefing of the shed what-if that deliberately fails validation.

    It says "fewer" for a rise, states a figure no fact carries and names a rule
    through a threshold the versioned rule does not hold.  The screen must show the
    deterministic briefing with a clear label instead.
    """
    f = facts
    sh2 = rule_ref(sources, "scenario", "SH-2")
    wrong_limit = dict(sh2, limit_value="250")
    return {
        "title": "What-if briefing: shed size that carries a condition",
        "sections": [
            section(
                "summary",
                [
                    sentence(
                        f"This what-if was tested on synthetic data: {f['population.size'].value} generated cases.",
                        [f["population.size"]],
                    )
                ],
            ),
            section(
                "key_effects",
                [
                    # Wrong direction: the approve figure rises.
                    sentence(
                        f"{f['outcome.approve.change'].value} fewer cases would be recommended for approval.",
                        [f["outcome.approve.change"]],
                    ),
                    # An uncited figure.
                    sentence("About 40 cases would benefit."),
                ],
            ),
            section(
                "risks",
                [
                    # A rule threshold the versioned rule does not hold.
                    sentence("The shed limit would be 250 sq ft (ACME Code §15-106).", [], [wrong_limit]),
                ],
            ),
            section("protected", [sentence("A person still decides every case.")]),
        ],
        "cannot_brief": False,
        "reason": "",
    }


def proposal(name: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
    blank = {
        "kind": "", "rule_id": "", "limit_value": "", "operator": "", "condition": "",
        "permit_type_key": "", "item_kind": "", "item": "", "action": "", "process_category": "",
        "discretionary": "", "service_target_days": -1, "fee_schedule_id": "",
        "fixed_review_charge_cents": -1, "valuation_multiplier": "", "rationale": "",
    }
    return {
        "name": name,
        "proposals": [{**blank, **change} for change in changes],
        "cannot_propose": False,
        "reason": "",
    }


# ------------------------------------------------------------------ the build


def context_for(session: Any, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def document(task: str, name: str, basis: dict[str, Any], output: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    prompt, schema = (
        (POLICY_BRIEF_PROMPT_VERSION, POLICY_BRIEF_SCHEMA_VERSION)
        if task == POLICY_BRIEF_TASK
        else (POLICY_PROPOSE_PROMPT_VERSION, POLICY_PROPOSE_SCHEMA_VERSION)
    )
    return {
        "fixture_kind": "policy_assist_replay",
        "fixture_version": FIXTURE_VERSION,
        "name": name,
        "note": NOTE,
        "task": task,
        "prompt_version": prompt,
        "schema_version": schema,
        "recorded_at": RECORDED_AT,
        "basis": basis,
        "replay_key": muse.replay_key(task, basis),
        "output": output,
        **extra,
    }


def build_documents() -> dict[str, dict[str, Any]]:
    """Return every fixture, by file name, built in a scratch database with a fixed clock."""
    documents: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        settings = Settings.load(
            environ={
                "ACME_DATABASE_URL": f"sqlite:///{tmp / 'policy-fixtures.db'}",
                "ACME_SECRET_KEY": "policy-fixture-builder-secret-value",
            },
            key_file=tmp / "missing.env",
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
            with transaction(factory) as session:
                actor = context_for(session, ADMIN)
                service = PolicyService(session, now=BUILD_NOW)
                runs: dict[str, Any] = {}
                for key in ("fence_height_7ft", "shed_condition_300"):
                    scenario = service.create_scenario(
                        actor, name=key, suggestion_key=key, expected_version=0
                    )
                    runs[key] = service.run_scenario(
                        actor, scenario.id, expected_version=scenario.version,
                        spec={"kind": "synthetic_year"},
                    )

                def prepare(run: Any) -> tuple[dict[str, Any], dict[Any, Any], list[Any]]:
                    fact_list = muse.muse_facts(run)
                    return (
                        {fact.fact_id: fact for fact in fact_list},
                        validation.rule_sources_of(run.baseline_config, run.proposed_config),
                        fact_list,
                    )

                def verify(output: dict[str, Any], run: Any, fact_list: list[Any], sources: Any,
                           purpose: str, *, must_pass: bool) -> validation.BriefCheck:
                    check = validation.validate_brief(
                        output, facts=fact_list, sources=sources, purpose=purpose,
                        synthetic=bool(run.population_synthetic),
                    )
                    if check.outcome.ok != must_pass:
                        codes = [i.code for i in check.outcome.issues]
                        raise SystemExit(
                            f"a {purpose} fixture {'failed' if must_pass else 'passed'} the validator: {codes}"
                        )
                    return check

                fence = runs["fence_height_7ft"]
                facts, sources, fact_list = prepare(fence)
                for purpose, file_name in (("brief", "fence-7ft-brief.json"), ("explain", "fence-7ft-explain.json")):
                    output = fence_brief(facts, sources, purpose)
                    verify(output, fence, fact_list, sources, purpose, must_pass=True)
                    documents[file_name] = document(
                        POLICY_BRIEF_TASK, file_name[:-5], muse.brief_basis(fence, purpose, fact_list), output,
                        {"purpose": purpose, "expect": "passes_validation",
                         "run_content_hash_at_build": fence.content_hash,
                         "analysis_at_of_build": BUILD_NOW.isoformat()},
                    )

                shed = runs["shed_condition_300"]
                facts, sources, fact_list = prepare(shed)
                output = shed_brief_that_fails(facts, sources)
                check = verify(output, shed, fact_list, sources, "brief", must_pass=False)
                codes = sorted({i.code for i in check.outcome.issues})
                for needed in ("wrong_direction", "uncited_figure", "rule_source_mismatch"):
                    if needed not in codes:
                        raise SystemExit(f"the failing fixture no longer fails with {needed}: {codes}")
                documents["shed-300-brief-fails-validation.json"] = document(
                    POLICY_BRIEF_TASK, "shed-300-brief-fails-validation",
                    muse.brief_basis(shed, "brief", fact_list), output,
                    {"purpose": "brief", "expect": "fails_validation", "expected_issue_codes": codes,
                     "run_content_hash_at_build": shed.content_hash,
                     "analysis_at_of_build": BUILD_NOW.isoformat()},
                )

                baseline = freeze_baseline(session, BUILD_NOW)

                def check_proposal(output: dict[str, Any], *, must_pass: bool) -> validation.ProposalCheck:
                    result = validation.validate_proposal(
                        output, baseline=baseline, describe=lambda r: views.describe_change(r, baseline)
                    )
                    if result.outcome.ok != must_pass:
                        raise SystemExit(
                            "a proposal fixture "
                            f"{'failed' if must_pass else 'passed'} the validator: "
                            f"{[i.message for i in result.outcome.issues]}"
                        )
                    return result

                df2 = next(r for r in baseline.rules if r.rule_id == "DF-2")
                fence_output = proposal(
                    "Raise the side/rear fence height limit from 6 ft to 7 ft",
                    [{
                        "kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7",
                        "rationale": (
                            f"The side and rear yard limit of {df2.citation} would move from "
                            f"{df2.limit_value} to 7."
                        ),
                    }],
                )
                check_proposal(fence_output, must_pass=True)
                documents["propose-fence-7ft.json"] = document(
                    POLICY_PROPOSE_TASK, "propose-fence-7ft", muse.propose_basis(FENCE_QUESTION, baseline),
                    fence_output, {"question": FENCE_QUESTION, "expect": "passes_validation"},
                )
                no_permit_output = proposal(
                    "No permit for sheds",
                    [{"kind": "no_permit_required", "permit_type_key": "shed",
                      "rationale": "Sheds would be handled without the permit step."}],
                )
                check_proposal(no_permit_output, must_pass=False)
                documents["propose-no-permit-shed-unsupported.json"] = document(
                    POLICY_PROPOSE_TASK, "propose-no-permit-shed-unsupported",
                    muse.propose_basis(NO_PERMIT_QUESTION, baseline), no_permit_output,
                    {"question": NO_PERMIT_QUESTION, "expect": "fails_validation"},
                )
        finally:
            factory.dispose()
    return documents


def build_fixtures(output: Path, *, check: bool) -> int:
    """Write (or check) the fixtures of the demonstration set."""
    documents = build_documents()
    for file_name, data in sorted(documents.items()):
        path = output / file_name
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if check:
            if not path.is_file():
                raise SystemExit(f"the fixture {file_name} is missing")
            if path.read_text(encoding="utf-8") != text:
                try:
                    held = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    held = {}
                if held.get("replay_key") != data["replay_key"]:
                    raise SystemExit(
                        f"STALE FIXTURE KEY: {file_name} is keyed {str(held.get('replay_key'))[:12]} but the "
                        f"current rules, configuration or run give {data['replay_key'][:12]}; "
                        "the replay would silently fall back. Rerun this builder."
                    )
                raise SystemExit(f"the fixture {file_name} does not match the current rules and run")
            print(f"unchanged  {file_name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"written    {file_name}")
    if check:
        extra = sorted(p.name for p in output.glob("*.json") if p.name not in documents)
        if extra:
            raise SystemExit(f"fixtures the builder does not produce: {extra}")
    print(f"{len(documents)} fixture(s) of the what-if policy agent")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "fixtures" / "replay" / "policy-assist"),
        help="the directory the fixtures are written to",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="prove that the committed fixtures match the current rules and runs",
    )
    arguments = parser.parse_args(argv)
    return build_fixtures(Path(arguments.output), check=arguments.check)


if __name__ == "__main__":
    raise SystemExit(main())

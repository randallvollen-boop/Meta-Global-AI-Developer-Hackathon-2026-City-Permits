"""The claim-by-claim validation of the what-if agent (policy 3).

Each rule of the validation has a test that a bad answer fails and a good one
passes: the direction of a figure, an uncited figure, the forbidden claims, an
unknown rule number, a rule source that differs from the versioned rule, one
bad paragraph among good ones (the whole response is refused), the schema, the
synthetic label and the proposed changes.
"""
# REQUIRES: AI-02, AI-04, SEC-03
# A what-if briefing or proposal that carries an unsupported claim is refused whole.

from __future__ import annotations

import copy
from typing import Any

import pytest

from policy_helpers import catalogue_baseline

from acme_city.policy.briefing import Fact
from acme_city.policy.muse_validation import (
    RuleSource,
    direction_cues,
    figures_of,
    forbidden_family,
    validate_brief,
    validate_proposal,
)

POP = "Synthetic year (sample data)"
BASE = "baseline aaaaaaaaaaaa"
SCEN = "scenario bbbbbbbbbbbb"


def fact(fid: str, value: Any, direction: str = "none", unit: str = "cases") -> Fact:
    return Fact(fid, fid, value, unit, direction, POP, BASE, SCEN, "test fact")


FACTS = [
    fact("population.size", 600),
    fact("cases.changed", 28),
    fact("outcome.approve.baseline", 306),
    fact("outcome.approve.scenario", 334, "increase"),
    fact("outcome.approve.change", 28, "increase"),
    fact("outcome.deny.baseline", 80),
    fact("outcome.deny.scenario", 52, "decrease"),
    fact("outcome.deny.change", 28, "decrease"),
    fact("holds.scenario", 134, "unchanged"),
    fact("fees.scenario", "1,234.50", "increase", "USD"),
]
BY_ID = {f.fact_id: f for f in FACTS}

SOURCES = {
    ("baseline", "DF-2", "DF-2@1"): RuleSource("baseline", "DF-2", "DF-2@1", "ACME Code §14-306", "6", "", "max", "Fence height"),
    ("scenario", "DF-2", "DF-2@1"): RuleSource("scenario", "DF-2", "DF-2@1", "ACME Code §14-306", "7", "", "max", "Fence height"),
}


def claim(fid: str, **override: Any) -> dict[str, Any]:
    f = BY_ID[fid]
    data = {"fact_id": f.fact_id, "value": str(f.value), "unit": f.unit, "direction": f.direction,
            "population": f.population, "baseline_id": f.baseline_id, "scenario_id": f.scenario_id}
    data.update(override)
    return data


def ref(configuration: str = "baseline", **override: Any) -> dict[str, Any]:
    src = SOURCES[(configuration, "DF-2", "DF-2@1")]
    data = {"rule_id": src.rule_id, "version": src.version, "citation": src.citation,
            "limit_value": src.limit_value, "unit": src.unit, "configuration": configuration}
    data.update(override)
    return data


def sentence(text: str, claims: list[dict[str, Any]] = (), refs: list[dict[str, Any]] = ()) -> dict[str, Any]:  # type: ignore[assignment]
    return {"text": text, "claims": list(claims), "rule_refs": list(refs)}


def section(key: str, *sentences: dict[str, Any], question: str = "") -> dict[str, Any]:
    return {"section": key, "question": question, "sentences": list(sentences)}


def good_output() -> dict[str, Any]:
    return {
        "title": "What-if briefing",
        "sections": [
            section(
                "summary",
                sentence("This what-if was tested on synthetic data: 600 generated cases.", [claim("population.size")]),
                sentence("It raises the fence limit from 6 ft to 7 ft (ACME Code §14-306).", [], [ref("baseline"), ref("scenario")]),
            ),
            section(
                "key_effects",
                sentence("Recommendations to approve would rise from 306 to 334 cases.",
                         [claim("outcome.approve.baseline"), claim("outcome.approve.scenario")]),
                sentence("Recommendations to deny would fall from 80 to 52 cases, which is 28 fewer.",
                         [claim("outcome.deny.baseline"), claim("outcome.deny.scenario"), claim("outcome.deny.change")]),
            ),
            section("risks", sentence("A person judges each case that stops failing the rule.")),
            section("protected", sentence("A person still decides every case.")),
        ],
        "cannot_brief": False,
        "reason": "",
    }


def check(output: dict[str, Any], **kwargs: Any):
    return validate_brief(output, facts=FACTS, sources=SOURCES, purpose=kwargs.pop("purpose", "brief"),
                          synthetic=kwargs.pop("synthetic", True))


def codes(output: dict[str, Any], **kwargs: Any) -> set[str]:
    return {i.code for i in check(output, **kwargs).outcome.issues}


def test_a_good_briefing_passes_and_names_what_it_cited() -> None:
    result = check(good_output())
    assert result.outcome.ok, [i.message for i in result.outcome.issues]
    assert "outcome.deny.change" in result.cited_facts
    assert "baseline:DF-2@DF-2@1" in result.cited_rules


# ------------------------------------------------------------------ direction


def test_a_decrease_word_for_an_increase_fact_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0] = sentence(
        "28 fewer cases would be recommended for approval.", [claim("outcome.approve.change")])
    assert "wrong_direction" in codes(out)


def test_an_increase_word_for_a_decrease_fact_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][1] = sentence(
        "Recommendations to deny would rise by 28 cases.", [claim("outcome.deny.change")])
    assert "wrong_direction" in codes(out)


def test_a_direction_word_with_no_fact_of_that_direction_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0] = sentence("The number of cases would fall.", [])
    assert "wrong_direction" in codes(out)


def test_a_claim_that_states_another_direction_than_its_fact_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][1]["claims"][2] = claim("outcome.deny.change", direction="increase")
    assert "claim_mismatch" in codes(out)


def test_unchanged_needs_an_unchanged_fact() -> None:
    out = good_output()
    out["sections"][1]["sentences"].append(sentence("Cases held for a person are unchanged at 134.", [claim("holds.scenario")]))
    assert check(out).outcome.ok
    out["sections"][1]["sentences"][-1] = sentence("Cases held for a person are unchanged at 306.", [claim("outcome.approve.baseline")])
    assert "wrong_direction" in codes(out)


def test_direction_cues_are_found() -> None:
    assert direction_cues("28 fewer cases") == {"decrease"}
    assert direction_cues("approvals rise and denials fall") == {"increase", "decrease"}
    assert direction_cues("The 600 cases are listed.") == frozenset()


# ------------------------------------------------------------- figures, claims


def test_a_figure_with_no_claim_is_refused() -> None:
    out = good_output()
    out["sections"][2]["sentences"][0] = sentence("About 40 cases would be affected.")
    assert "uncited_figure" in codes(out)


def test_a_figure_that_no_cited_fact_carries_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0] = sentence(
        "Recommendations to approve would rise from 306 to 335 cases.",
        [claim("outcome.approve.baseline"), claim("outcome.approve.scenario")])
    assert "figure_not_supported" in codes(out)


def test_a_spelled_number_is_a_figure() -> None:
    out = good_output()
    out["sections"][2]["sentences"][0] = sentence("About forty cases would be affected.")
    assert figures_of("twelve cases") == (12.0,)
    assert "uncited_figure" in codes(good_with(out, "twelve cases were affected."))


def good_with(out: dict[str, Any], text: str) -> dict[str, Any]:
    out = copy.deepcopy(out)
    out["sections"][2]["sentences"][0] = sentence(text)
    return out


def test_formatting_of_the_same_value_is_accepted() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0] = sentence(
        "Hypothetical assessed fees would rise to 1234.5 USD.", [claim("fees.scenario")])
    assert check(out).outcome.ok
    out["sections"][1]["sentences"][0] = sentence(
        "Hypothetical assessed fees would rise to 1,234.50 USD.", [claim("fees.scenario")])
    assert check(out).outcome.ok


@pytest.mark.parametrize("field,value", [
    ("value", "29"), ("unit", "days"), ("population", "Real applications"),
    ("baseline_id", "baseline cccccccccccc"), ("scenario_id", "scenario dddddddddddd"),
])
def test_every_field_of_a_claim_must_match_its_fact(field: str, value: str) -> None:
    out = good_output()
    out["sections"][1]["sentences"][1]["claims"][2] = claim("outcome.deny.change", **{field: value})
    assert "claim_mismatch" in codes(out)


def test_a_claim_for_an_unknown_fact_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0]["claims"].append(claim("population.size", fact_id="invented.fact"))
    assert "unknown_fact" in codes(out)


def test_a_claim_the_sentence_does_not_state_is_refused() -> None:
    out = good_output()
    out["sections"][1]["sentences"][0]["claims"].append(claim("cases.changed"))
    assert "claim_not_in_sentence" in codes(out)


# ------------------------------------------------------------------ forbidden


@pytest.mark.parametrize("text,family", [
    ("Revenue would rise.", "revenue"),
    ("The change brings in revenues for the City.", "revenue"),
    ("Staff time would be saved.", "staff_time"),
    ("This saves staff time.", "staff_time"),
    ("Processing times would shrink.", "staff_time"),
    ("Throughput improves.", "throughput"),
    ("Reviews would be faster.", "throughput"),
    ("No permit required for a shed.", "no_permit"),
    ("A shed would need no permit required at all.", "no_permit"),
    ("Sheds are exempt from review.", "no_permit"),
    ("Council should adopt the change.", "enact"),
    ("We recommend that the council adopt it.", "enact"),
    ("It would be worth enacting.", "enact"),
    ("Every case will be approved.", "outcome"),
    ("There is no risk.", "risk_free"),
    ("This is legal advice.", "legal"),
])
def test_forbidden_claims_are_refused(text: str, family: str) -> None:
    assert forbidden_family(text) == family
    assert "forbidden_claim" in codes(good_with(good_output(), text))


@pytest.mark.parametrize("text", [
    "The recommendation holds are unchanged.",
    "The engine counts what the rules would recommend.",
    "Fees are hypothetical assessed fees, not money collected.",
    "A person decides every case.",
])
def test_ordinary_words_of_the_domain_are_not_refused(text: str) -> None:
    assert forbidden_family(text) is None


def test_the_title_and_a_question_are_checked_too() -> None:
    out = good_output()
    out["title"] = "Revenue briefing"
    assert "forbidden_claim" in codes(out)
    out = good_output()
    out["title"] = "A 7 ft briefing"
    assert "title_figure" in codes(out)
    out = good_output()
    out["sections"].append(section("question", sentence("A person decides."), question="Will there be revenue?"))
    assert "forbidden_claim" in codes(out)


# ---------------------------------------------------------------- rule numbers


def test_an_unknown_rule_number_is_refused() -> None:
    out = good_output()
    out["sections"][0]["sentences"][1] = sentence(
        "It raises the fence limit under ACME Code §99-999.", [], [ref("baseline")])
    assert "unknown_rule_number" in codes(out)


def test_an_unknown_rule_id_is_refused() -> None:
    out = good_output()
    out["sections"][0]["sentences"][1] = sentence("Rule XX-9 changes.", [], [ref("baseline")])
    assert "unknown_rule_number" in codes(out)


def test_a_rule_source_that_is_not_a_versioned_rule_of_the_run_is_refused() -> None:
    out = good_output()
    out["sections"][0]["sentences"][1]["rule_refs"][0] = ref("baseline", rule_id="ZZ-1")
    assert "unknown_rule" in codes(out)
    out = good_output()
    out["sections"][0]["sentences"][1]["rule_refs"][0] = ref("baseline", version="DF-2@9")
    assert "unknown_rule" in codes(out)


@pytest.mark.parametrize("field,value", [("limit_value", "8"), ("citation", "ACME Code §14-305"), ("unit", "m")])
def test_a_rule_source_must_equal_the_versioned_rule(field: str, value: str) -> None:
    out = good_output()
    out["sections"][0]["sentences"][1]["rule_refs"][1] = ref("scenario", **{field: value})
    assert "rule_source_mismatch" in codes(out)


def test_a_threshold_without_a_rule_source_is_refused() -> None:
    out = good_output()
    out["sections"][0]["sentences"][1] = sentence("It raises the fence limit from 6 ft to 7 ft.")
    assert "uncited_figure" in codes(out)


# -------------------------------------------------- one bad paragraph, schema


def test_one_bad_sentence_refuses_the_whole_response() -> None:
    out = good_output()
    out["sections"][1]["sentences"].append(sentence("Fully 90 cases would benefit."))
    result = check(out)
    assert not result.outcome.ok
    assert len(result.outcome.issues) >= 1
    # Every other sentence was fine; none of them is salvaged.
    assert result.cited_facts == ()


def test_the_schema_is_strict() -> None:
    out = good_output()
    out["extra"] = 1
    assert "schema_invalid" in codes(out)
    out = good_output()
    del out["title"]
    assert "schema_invalid" in codes(out)
    out = good_output()
    out["sections"][0]["sentences"][0]["claims"][0].pop("baseline_id")
    assert "schema_invalid" in codes(out)


def test_the_schema_sent_to_muse_requires_every_field_the_validator_requires() -> None:
    # A live briefing came back without "title" because the strict schema
    # builder dropped the field along with the "title" metadata keyword.
    from acme_city.muse.schemas import TASK_OUTPUT_MODELS, task_schema

    for task, model in TASK_OUTPUT_MODELS.items():
        sent = task_schema(task)
        assert set(sent["properties"]) == set(model.model_fields), task
        assert sorted(sent["required"]) == sorted(model.model_fields), task
    assert "title" in task_schema("policy_brief")["required"]


def test_the_required_sections_depend_on_the_purpose() -> None:
    out = good_output()
    out["sections"] = out["sections"][:2]
    assert "missing_section" in codes(out, purpose="brief")
    assert check(out, purpose="explain").outcome.ok


def test_a_synthetic_population_must_be_called_synthetic() -> None:
    out = good_output()
    out["sections"][0]["sentences"][0] = sentence("This what-if was tested on 600 generated cases.", [claim("population.size")])
    assert "synthetic_not_labelled" in codes(out)
    assert "synthetic_not_labelled" not in codes(out, synthetic=False)


def test_a_refusal_must_use_an_allowed_reason_and_carry_no_sections() -> None:
    declined = {"title": "", "sections": [], "cannot_brief": True, "reason": "needs_a_person"}
    result = check(declined)
    assert result.outcome.ok and result.declined
    assert "invalid_refusal_reason" in codes({**declined, "reason": "because"})
    assert "answer_with_refusal" in codes({**declined, "sections": good_output()["sections"]})


# --------------------------------------------------------------------- proposals


BLANK = {
    "kind": "", "rule_id": "", "limit_value": "", "operator": "", "condition": "", "permit_type_key": "",
    "item_kind": "", "item": "", "action": "", "process_category": "", "discretionary": "",
    "service_target_days": -1, "fee_schedule_id": "", "fixed_review_charge_cents": -1,
    "valuation_multiplier": "", "rationale": "",
}


def proposal(*changes: dict[str, Any], name: str = "A what-if") -> dict[str, Any]:
    return {"name": name, "proposals": [{**BLANK, **c} for c in changes], "cannot_propose": False, "reason": ""}


def verdict(output: dict[str, Any]):
    baseline = catalogue_baseline()
    return validate_proposal(output, baseline=baseline, describe=lambda request: str(request))


FENCE = {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7",
         "rationale": "The side and rear yard limit of ACME Code §14-306 would move from 6 to 7."}


def proposal_codes(output: dict[str, Any]) -> set[str]:
    return {i.code for i in verdict(output).outcome.issues}


def test_a_supported_change_passes_and_is_rebuilt_as_a_request() -> None:
    result = verdict(proposal(FENCE))
    assert result.outcome.ok, [i.message for i in result.outcome.issues]
    assert result.changes == ({"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"},)
    assert result.items[0].ok


@pytest.mark.parametrize("kind", ["no_permit_required", "remove_plan_review", "exempt_type", "invented_kind"])
def test_an_unsupported_kind_refuses_the_whole_response(kind: str) -> None:
    result = verdict(proposal(FENCE, {"kind": kind, "permit_type_key": "shed", "rationale": "Handled differently."}))
    assert not result.outcome.ok
    assert result.items[0].ok and not result.items[1].ok  # each change is judged on its own
    assert "invalid_change" in {i.code for i in result.outcome.issues}


def test_a_conditional_retirement_is_unsupported() -> None:
    result = verdict(proposal({"kind": "rule_retirement", "rule_id": "DF-2", "condition": "only small fences",
                               "rationale": "Retire it for some cases."}))
    assert not result.outcome.ok and "some cases only" in " ".join(i.message for i in result.outcome.issues)


def test_an_unknown_rule_or_a_malformed_change_is_refused() -> None:
    assert not verdict(proposal({**FENCE, "rule_id": "ZZ-9"})).outcome.ok
    assert not verdict(proposal({"kind": "rule_threshold", "rule_id": "DF-2", "rationale": "Nothing to change."})).outcome.ok
    assert not verdict(proposal({"kind": "service_target", "permit_type_key": "deck_fence",
                                 "service_target_days": 0, "rationale": "Instant."})).outcome.ok


def test_a_stray_field_is_refused_not_ignored() -> None:
    assert "invalid_change" in proposal_codes(proposal({**FENCE, "permit_type_key": "shed"}))
    assert "invalid_change" in proposal_codes(proposal({**FENCE, "fixed_review_charge_cents": 5}))


def test_the_rationale_may_not_carry_a_forbidden_claim_or_an_invented_figure_or_section() -> None:
    assert not verdict(proposal({**FENCE, "rationale": "This would save staff time."})).outcome.ok
    assert not verdict(proposal({**FENCE, "rationale": "Around 40 permits a year would change."})).outcome.ok
    assert not verdict(proposal({**FENCE, "rationale": "The limit of ACME Code §99-1 would move."})).outcome.ok
    assert not verdict(proposal({**FENCE, "rationale": ""})).outcome.ok
    assert verdict(proposal(FENCE)).outcome.ok


def test_every_proposal_needs_a_name_and_at_most_five_changes() -> None:
    assert "name_missing" in proposal_codes(proposal(FENCE, name=" "))
    assert "too_many_changes" in proposal_codes(proposal(*([FENCE] * 6)))
    assert "no_changes" in proposal_codes(proposal())


def test_a_refusal_of_a_proposal_uses_an_allowed_reason() -> None:
    declined = {"name": "", "proposals": [], "cannot_propose": True, "reason": "unsupported_change"}
    assert verdict(declined).declined
    assert not verdict({**declined, "reason": "whim"}).outcome.ok
    assert not verdict({**declined, "proposals": proposal(FENCE)["proposals"]}).outcome.ok


def test_the_proposal_schema_is_strict() -> None:
    out = proposal(FENCE)
    out["proposals"][0]["surprise"] = 1
    assert "schema_invalid" in proposal_codes(out)


def test_the_policy_payload_leaves_room_for_reasoning_and_the_briefing() -> None:
    # A live briefing spent 3,290 of a 4,000-token budget on reasoning and was
    # cut off; the policy tasks now reserve more, within the client's ceiling.
    from acme_city.muse.client import MAX_OUTPUT_CEILING, POLICY_MAX_OUTPUT_TOKENS
    from acme_city.policy.muse import build_payload

    payload = build_payload("policy_brief", instructions="i", text="t", model="m")
    assert payload["max_output_tokens"] == POLICY_MAX_OUTPUT_TOKENS
    assert POLICY_MAX_OUTPUT_TOKENS >= 12000
    assert POLICY_MAX_OUTPUT_TOKENS <= MAX_OUTPUT_CEILING


def test_the_rule_sources_name_limit_value_and_unit_separately() -> None:
    # A live briefing copied "max 6" into limit_value because the input joined
    # the operator and the limit in one column.
    import inspect

    from acme_city.policy import muse

    source = inspect.getsource(muse.render_brief_input)
    for field in ("configuration", "rule_id", "version", "citation", "operator", "limit_value", "unit"):
        assert f'f"{field}=' in source, field
    assert '{source.operator} {source.limit_value}' not in source

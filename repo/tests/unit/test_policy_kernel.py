"""The what-if kernels over hand-made frozen cases: scenarios, impact and fees.

These tests need no database.  The baseline is the published part of the
committed catalogue file, and every case is a frozen value, so each expected
number can be worked out by hand from the rule limits.
"""
# REQUIRES: REF-01, PER-02
# The kernels re-score frozen inputs under a frozen baseline and a scenario copy.

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest
from policy_helpers import ANALYSIS_AT, ARRIVAL, catalogue_baseline, fence, shed

from acme_city.finance.calculator import calculate_fee
from acme_city.kernel.findings import FindingSpec
from acme_city.policy.changes import (
    UNSUPPORTED_CONDITIONAL_RETIREMENT,
    UNSUPPORTED_FEE_COMPONENT,
    UNSUPPORTED_NO_PERMIT,
    UNSUPPORTED_PLAN_REVIEW,
    UNSUPPORTED_UNKNOWN,
    ChangeError,
    DiscretionaryChange,
    FeeChange,
    ProcessCategoryChange,
    RequirementChange,
    RuleRetirementChange,
    RuleThresholdChange,
    Scenario,
    ServiceTargetChange,
    apply_scenario,
    build_scenario,
    fence_height_limit_scenario,
    parse_change,
)
from acme_city.policy.fees import TOTAL_LABEL, price_case
from acme_city.policy.impact import compute_impact
from acme_city.policy.kernel import UnknownPermitType, evaluate_case
from acme_city.policy.population import (
    KIND_DECIDED_RANGE,
    KIND_SYNTHETIC_YEAR,
    CaseInput,
    Population,
    PopulationDefinition,
    manual_population,
)

BASE = catalogue_baseline()


def run(cases, changes, baseline=BASE):
    scenario = Scenario("test", tuple(changes))
    result = apply_scenario(baseline, scenario)
    assert result.supported, (result.unsupported, result.issues)
    return compute_impact(manual_population(cases), baseline, result)


# ------------------------------------------------------------ the headline


def test_fence_limit_six_to_seven_changes_exactly_the_cases_between() -> None:
    cases = [fence(f"R{h}", h) for h in (4, 5.5, 6, 6.5, 7, 7.5, 8)]
    cases.append(fence("FRONT-6", 6, location="front"))
    cases.append(fence("FRONT-5", 5, location="front"))
    impact = run(cases, fence_height_limit_scenario().changes)
    moved = {d.case_ref: d.recommendation_transition for d in impact.case_diffs if d.changed}
    assert moved == {"R6.5": "deny->approve", "R7": "deny->approve"}
    # DF-1: the front-yard fence is denied under section 14-305 before and after.
    for ref in ("FRONT-6", "FRONT-5"):
        diff = next(d for d in impact.case_diffs if d.case_ref == ref)
        assert diff.baseline.recommendation == diff.scenario.recommendation
    front6 = next(d for d in impact.case_diffs if d.case_ref == "FRONT-6")
    assert front6.scenario.recommendation == "deny"
    assert front6.scenario.failing_rules() == ("DF-1",)
    # DF-2: a rear-yard fence within the limit is approved.
    r5 = next(d for d in impact.case_diffs if d.case_ref == "R5.5")
    assert r5.scenario.recommendation == "approve"
    assert impact.changed_case_count == 2
    assert dict(impact.by_direction) == {"relaxed": 2}
    assert dict(impact.recommendation_transitions) == {"deny->approve": 2}
    assert impact.rule_transitions_by_type == (("deck_fence", "fail->pass", 2),)


def test_safety_signals_name_every_case_that_stops_failing_and_its_rule() -> None:
    impact = run([fence("A", 6.5), fence("B", 7), fence("C", 9)], fence_height_limit_scenario().changes)
    signals = {(s.case_ref, s.rule_id): s for s in impact.safety_signals}
    assert set(signals) == {("A", "DF-2"), ("B", "DF-2")}
    signal = signals[("A", "DF-2")]
    assert signal.citation == "ACME Code §14-306"
    assert (signal.baseline_limit, signal.scenario_limit) == ("6", "7")
    assert signal.observed_value == "6.5"
    assert signal.rule_retired is False


def test_the_baseline_is_not_changed_by_applying_a_scenario() -> None:
    before = BASE.config_hash
    result = apply_scenario(BASE, fence_height_limit_scenario())
    assert BASE.config_hash == before
    assert result.config is not None
    assert result.config.config_hash != before
    df2 = {r.rule_id: r for r in BASE.rules}["DF-2"]
    assert df2.limit_value == "6"
    scenario_df2 = {r.rule_id: r for r in result.config.rules}["DF-2"]
    assert scenario_df2.limit_value == "7"
    with pytest.raises(dataclasses.FrozenInstanceError):
        df2.limit_value = "9"  # type: ignore[misc]


def test_zero_effects_are_reported_honestly() -> None:
    impact = run([fence("A", 4), fence("B", 5)], fence_height_limit_scenario().changes)
    assert impact.changed_case_count == 0
    assert impact.safety_signals == ()
    assert impact.holds["cleared"] == 0
    assert impact.by_change[0].cases_changed == 0


def test_a_run_is_deterministic_and_hashed_without_ids_or_times() -> None:
    cases = [fence("A", 6.5), fence("B", 5), shed("S", 250)]
    first = run(cases, fence_height_limit_scenario().changes)
    second = run(cases, fence_height_limit_scenario().changes)
    assert first.result_hash == second.result_hash
    assert first.result_hash != run(cases, [RuleThresholdChange("DF-2", "8")]).result_hash
    text = json.dumps(first.canonical())
    assert "created_at" not in text and "run_id" not in text


# ------------------------------------------------------- each change kind


def test_threshold_change_on_a_shed_condition_rule() -> None:
    # SH-2: over 200 sq ft is an approval condition.  Raising it to 300 removes it.
    cases = [shed("S1", 150), shed("S2", 250), shed("S3", 320), shed("S4", 700)]
    base = {c.case_ref: evaluate_case(c, BASE) for c in cases}
    assert [base[r].recommendation for r in ("S1", "S2", "S3", "S4")] == [
        "approve", "approve_with_conditions", "approve_with_conditions", "deny"]
    impact = run(cases, [RuleThresholdChange("SH-2", "300")])
    moved = {d.case_ref: d.recommendation_transition for d in impact.case_diffs if d.changed}
    assert moved == {"S2": "approve_with_conditions->approve"}


def test_retiring_a_rule_removes_its_result_and_is_reported_as_retired() -> None:
    impact = run([fence("A", 6.5)], [RuleRetirementChange("DF-2")])
    (signal,) = impact.safety_signals
    assert signal.rule_retired is True and signal.rule_id == "DF-2"
    assert signal.scenario_status == "retired"
    diff = impact.case_diffs[0]
    assert all(r["rule_id"] != "DF-2" for r in diff.scenario.rule_results)
    # With the only rule that names "side_rear" gone, the evaluator no longer
    # knows that category, so DF-1 cannot decide whether it applies: the case
    # is held for a person rather than approved.  This is the production
    # evaluator's behaviour, reproduced faithfully.
    assert diff.scenario.recommendation == "hold"
    assert diff.scenario.hold_reason == "rule_review"
    assert diff.scenario.rule_results[0]["reason"] == "unknown_category"


def test_adding_and_removing_a_required_document() -> None:
    complete = fence("A", 4)
    no_material = fence("B", 4, documents=["site_plan"])
    base_b = evaluate_case(no_material, BASE)
    assert base_b.missing_documents == ("material_spec",)
    assert base_b.route_status == "needs_information"
    impact = run([complete, no_material], [RequirementChange("deck_fence", "document", "material_spec", "remove")])
    assert impact.needs_information["baseline"] == 1 and impact.needs_information["scenario"] == 0
    assert impact.needs_information["cleared"] == 1
    assert dict((k, n) for _t, k, n in impact.findings_removed) == {"missing_document": 1}
    added = run([complete], [RequirementChange("deck_fence", "field", "fence_material", "add")])
    assert added.needs_information["added"] == 1
    assert dict((k, n) for _t, k, n in added.findings_added) == {"missing_field": 1}


def test_discretionary_to_by_right_clears_only_the_recommendation_hold() -> None:
    case = CaseInput.create(
        case_ref="V1",
        permit_type_key="zoning_variance",
        basis_at=ARRIVAL,
        facts={"parcel_number": "ACME-P-1001", "project_description": "variance"},
        intake_record={"channel": "portal", "applicant_name": "V", "submitted_site_text": "1 A St"},
        documents=[],
        safeguard_blockers=["credential_expired"],
    )
    required = BASE.type_config("zoning_variance")
    assert required is not None and required.discretionary
    before = evaluate_case(case, BASE)
    assert before.recommendation == "hold" and before.hold_reason == "discretionary"
    impact = run([case], [DiscretionaryChange("zoning_variance", False)])
    after = impact.case_diffs[0].scenario
    # The discretionary hold is gone (no published rule remains, so a hold for
    # that reason may replace it), but nothing else about the safeguards moved.
    assert after.hold_reason != "discretionary"
    assert after.safeguards == before.safeguards == ("credential_expired",)
    assert after.human_decision_required is True
    assert after.missing_required_inputs == before.missing_required_inputs
    assert impact.holds["cleared_discretionary"] <= impact.holds["cleared"]


def test_by_right_type_with_rules_skips_the_hold_but_keeps_safeguards() -> None:
    # Take a type that has rules, make it discretionary in the baseline, then
    # make it by-right in the scenario: the hold clears, the safeguards stay.
    seed = dataclasses.replace(
        BASE,
        permit_types=tuple(
            dataclasses.replace(t, discretionary=True) if t.key == "deck_fence" else t
            for t in BASE.permit_types
        ),
    )
    case = fence("A", 5, safeguard_blockers=["site_unresolved"])
    impact = run([case], [DiscretionaryChange("deck_fence", False)], baseline=seed)
    diff = impact.case_diffs[0]
    assert diff.baseline.recommendation == "hold"
    assert diff.scenario.recommendation == "approve"
    assert impact.holds["cleared"] == 1
    assert impact.holds["cleared_discretionary"] == 1
    assert impact.holds["cleared_but_still_blocked_by_safeguards"] == 1
    assert diff.scenario.safeguards == ("site_unresolved",)
    assert diff.scenario.human_decision_required is True


def test_service_target_and_process_category_change_no_case_outcome() -> None:
    cases = [fence("A", 5), fence("B", 6.5), shed("S", 100)]
    impact = run(cases, [ServiceTargetChange("deck_fence", 3), ProcessCategoryChange("deck_fence", "with_plans")])
    assert impact.changed_case_count == 0
    (target,) = impact.service_targets
    assert (target.permit_type_key, target.before_days, target.after_days) == ("deck_fence", 5, 3)
    assert target.cases_in_population == 2
    assert all(not c.models_case_outcomes or c.cases_changed == 0 for c in impact.by_change)


def test_changes_are_counted_one_by_one_and_together() -> None:
    cases = [fence("A", 6.5), shed("S", 250)]
    impact = run(cases, [RuleThresholdChange("DF-2", "7"), RuleThresholdChange("SH-2", "300")])
    by_target = {c.target: c for c in impact.by_change}
    assert by_target["rule:DF-2"].cases_changed == 1
    assert dict(by_target["rule:DF-2"].by_direction) == {"relaxed": 1}
    assert by_target["rule:SH-2"].cases_changed == 1
    assert impact.changed_case_count == 2


def test_a_missing_input_stays_a_review_hold_after_any_change() -> None:
    case = fence("A", 5, facts={"location": ""})
    impact = run([case], fence_height_limit_scenario().changes)
    assert impact.case_diffs[0].scenario.recommendation == "hold"
    assert impact.case_diffs[0].scenario.hold_reason == "rule_review"


# ------------------------------------------------- unsupported and invalid


@pytest.mark.parametrize(
    ("request_", "code"),
    [
        ({"kind": "no_permit_required", "permit_type_key": "shed"}, UNSUPPORTED_NO_PERMIT),
        ({"kind": "conditional_plan_review_removal", "permit_type_key": "shed", "below": "200"},
         UNSUPPORTED_PLAN_REVIEW),
        ({"kind": "rule_retirement", "rule_id": "SH-1", "when": {"shed_area_sqft": "<100"}},
         UNSUPPORTED_CONDITIONAL_RETIREMENT),
        ({"kind": "fee", "fee_schedule_id": "fee_commercial_demo", "expedite_surcharge": 5},
         UNSUPPORTED_FEE_COMPONENT),
        ({"kind": "teleport"}, UNSUPPORTED_UNKNOWN),
    ],
)
def test_unsupported_changes_return_an_explicit_response(request_, code) -> None:
    change = parse_change(request_)
    result = apply_scenario(BASE, Scenario("u", (change,)))
    assert result.supported is False and result.config is None
    (response,) = result.unsupported
    assert response.code == code and response.supported is False
    assert "not supported" in response.message
    with pytest.raises(ValueError, match="refused"):
        compute_impact(manual_population([fence("A", 5)]), BASE, result)


def test_a_mixed_scenario_is_refused_atomically() -> None:
    scenario = build_scenario("mixed", [
        {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"},
        {"kind": "no_permit_required", "permit_type_key": "shed"},
    ])
    result = apply_scenario(BASE, scenario)
    assert result.config is None and result.applied == ()
    assert [u.change_index for u in result.unsupported] == [1]


@pytest.mark.parametrize(
    "change",
    [
        RuleThresholdChange("NOPE-1", "7"),
        RuleThresholdChange("DF-2", "seven"),
        RuleThresholdChange("DF-2", "-1"),
        RuleThresholdChange("DF-2", "7", operator="sideways"),
        RuleRetirementChange("CT-2-nope"),
        RequirementChange("deck_fence", "document", "site_plan", "add"),
        RequirementChange("deck_fence", "document", "unheard_of", "remove"),
        RequirementChange("not_a_type", "field", "x_field", "add"),
        ProcessCategoryChange("shed", "sideways"),
        ServiceTargetChange("shed", 0),
        ServiceTargetChange("shed", 4000),
        FeeChange("fee_commercial_demo", valuation_multiplier="-1"),
        FeeChange("fee_commercial_demo", fixed_review_charge_cents=-5),
        FeeChange("no_such_schedule", fixed_review_charge_cents=5),
    ],
)
def test_invalid_changes_are_issues_not_partial_applications(change) -> None:
    good = RuleThresholdChange("SH-1", "700")
    result = apply_scenario(BASE, Scenario("bad", (good, change)))
    assert result.config is None and result.applied == ()
    assert result.issues and result.issues[0].change_index == 1


def test_two_changes_to_one_target_conflict() -> None:
    result = apply_scenario(BASE, Scenario("c", (RuleThresholdChange("DF-2", "7"), RuleRetirementChange("DF-2"))))
    assert result.config is None
    assert result.issues[0].code == "conflicting_change"


def test_malformed_requests_raise_change_errors() -> None:
    with pytest.raises(ChangeError):
        build_scenario("", [{"kind": "rule_retirement", "rule_id": "DF-2"}])
    with pytest.raises(ChangeError):
        build_scenario("x", [])
    with pytest.raises(ChangeError):
        parse_change({"kind": "rule_threshold", "rule_id": "DF-2"})
    with pytest.raises(ChangeError):
        parse_change({"kind": "requirement", "permit_type_key": "shed", "item_kind": "field",
                      "item": "Bad Name", "action": "add"})


# --------------------------------------------------------------------- fees


def test_fee_change_uses_exact_rounding_and_lists_unpriceable_cases() -> None:
    cases = [
        fence("A", 5, facts={"valuation": "3000.00"}),
        fence("B", 5, facts={"valuation": "12345.67"}),
        shed("S", 100, facts={"valuation": "999.99"}),
        fence("NOVAL", 5, facts={"valuation": None}),
        fence("BADVAL", 5, facts={"valuation": "lots"}),
    ]
    impact = run(cases, [FeeChange("fee_commercial_demo", valuation_multiplier="0.0015")])
    fees = impact.fees
    assert fees is not None
    assert fees.label == TOTAL_LABEL == "hypothetical assessed fees"
    assert fees.priced_count == 3
    assert {(ref, reason) for ref, _key, reason in fees.unpriceable} == {
        ("NOVAL", "no_valuation"), ("BADVAL", "invalid_valuation")}
    # by hand: 10000 + round-half-up(valuation_cents * multiplier)
    expect_before = (10000 + 300) + (10000 + 1235) + (10000 + 100)
    expect_after = (10000 + 450) + (10000 + 1852) + (10000 + 150)
    assert fees.baseline_total_cents == expect_before
    assert fees.scenario_total_cents == expect_after
    assert fees.delta_cents == expect_after - expect_before
    assert "revenue" not in json.dumps(fees.to_dict()).lower()


def test_fee_kernel_matches_the_production_calculator_to_the_cent() -> None:
    config = apply_scenario(BASE, Scenario("f", (FeeChange("fee_commercial_demo", 12000, "0.00125"),))).config
    assert config is not None
    for cents in (0, 1, 399, 400, 401, 1234567, 99999999):
        valuation = f"{cents // 100}.{cents % 100:02d}"
        case = fence("X", 5, facts={"valuation": valuation})
        priced = price_case(case, config)
        direct = calculate_fee(
            {"fixed_review_charge_cents": 12000, "valuation_multiplier": "0.00125"}, cents)
        assert priced.total_cents == direct.total_cents
        assert (priced.fixed_cents, priced.variable_cents) == (
            direct.lines[0].amount_cents, direct.lines[1].amount_cents)


def test_changed_schedule_lists_every_type_that_shares_it() -> None:
    impact = run([fence("A", 5), shed("S", 100)], [FeeChange("fee_commercial_demo", 15000)])
    fees = impact.fees
    assert fees is not None
    assert len(fees.types_sharing_changed_schedule) == len(BASE.permit_types)
    assert fees.types_priced_by_changed_schedule == ("deck_fence", "shed")
    assert fees.changed_case_count == 2


def test_no_fee_section_when_no_fee_changed() -> None:
    assert run([fence("A", 5)], fence_height_limit_scenario().changes).fees is None


def test_a_case_with_no_schedule_in_force_on_its_date_is_unpriceable() -> None:
    early = dataclasses.replace(fence("EARLY", 5), basis_at=datetime(2025, 1, 1, tzinfo=UTC))
    assert price_case(early, BASE).reason == "no_fee_schedule_in_force"


# -------------------------------------------- no staff-time or revenue claims


def test_the_result_makes_no_staff_time_or_revenue_claim() -> None:
    impact = run([fence("A", 6.5), shed("S", 250)], [
        RuleThresholdChange("DF-2", "7"), ServiceTargetChange("deck_fence", 3),
        FeeChange("fee_commercial_demo", valuation_multiplier="0.002")])
    text = json.dumps(impact.summary()).lower() + json.dumps(impact.notes).lower()
    for forbidden in ("staff", "throughput", "time_saved", "time saved", "revenue", "saving",
                      "person-day", "workload"):
        assert forbidden not in text, forbidden
    assert set(impact.summary()) >= {"holds", "needs_information", "service_targets", "fees"}


# ---------------------------------------------------------- the population


def test_population_validation_and_labels() -> None:
    a, b = fence("A", 5), fence("A", 6)
    assert manual_population([a, b]).validate(BASE) == ["duplicate case reference 'A'"]
    ghost = dataclasses.replace(a, permit_type_key="nope")
    assert "unknown permit type" in manual_population([ghost]).validate(BASE)[0]
    synthetic = Population(PopulationDefinition(kind=KIND_SYNTHETIC_YEAR, synthetic=False, seed=1), (a,))
    assert synthetic.validate(BASE) == ["a synthetic year must be labelled synthetic"]
    ok = Population(PopulationDefinition(kind=KIND_SYNTHETIC_YEAR, synthetic=True, seed=1,
                                         generator_version="g1", distributions_version="d1"), (a,))
    assert ok.validate(BASE) == []
    historical = Population(PopulationDefinition(kind=KIND_DECIDED_RANGE), (a,))
    assert historical.definition.retrospective
    assert "retrospective re-scoring" in historical.definition.display_label
    assert ok.population_hash != Population(ok.definition, (b,)).population_hash
    with pytest.raises(UnknownPermitType):
        evaluate_case(ghost, BASE)


def test_an_invalid_population_cannot_be_run() -> None:
    scenario = apply_scenario(BASE, fence_height_limit_scenario())
    with pytest.raises(ValueError, match="duplicate case reference"):
        compute_impact(manual_population([fence("A", 5), fence("A", 6)]), BASE, scenario)


def test_a_scenario_built_on_another_baseline_is_refused() -> None:
    other = catalogue_baseline(datetime(2026, 12, 1, tzinfo=UTC))
    scenario = apply_scenario(other, fence_height_limit_scenario())
    with pytest.raises(ValueError, match="different baseline"):
        compute_impact(manual_population([fence("A", 5)]), BASE, scenario)


def test_carried_findings_and_the_duplicate_lookup_route_the_case() -> None:
    carried = FindingSpec("conflict", "Nothing in the official address list matches 'x'.",
                          rule="ACME Code §13-703", severity="block")
    held = fence("A", 5, carried_findings=[carried])
    dup = fence("B", 5, duplicate_of=("app_1", "SYN-APP-001"))
    one, two = evaluate_case(held, BASE), evaluate_case(dup, BASE)
    assert one.route_status == "needs_information" and carried in one.findings
    assert two.route_status == "needs_information"
    assert [f.finding_type for f in two.findings] == ["duplicate"]
    assert two.findings[0].related_application_id == "app_1"


def test_wrong_type_inactive_type_and_missing_fee_schedule_findings() -> None:
    wrong = fence("A", 5)
    wrong = dataclasses.replace(
        wrong, intake_record=tuple(sorted(dict(wrong.intake_record, permit_type_key="shed").items())))
    outcome = evaluate_case(wrong, BASE)
    assert [f.finding_type for f in outcome.findings] == ["wrong_type"]
    inactive = dataclasses.replace(
        BASE, permit_types=tuple(
            dataclasses.replace(t, active=False, fee_schedule_key=None) if t.key == "deck_fence" else t
            for t in BASE.permit_types))
    kinds = sorted(f.finding_type for f in evaluate_case(fence("B", 5), inactive).findings)
    assert kinds == ["conflict", "fee"]


def test_document_quality_flags_become_the_same_findings_production_records() -> None:
    case = fence("A", 5, documents=[("site_plan", ["unreadable"]), ("material_spec", ["rotated", "duplicate_page"])])
    kinds = [(f.finding_type, f.severity) for f in evaluate_case(case, BASE).findings]
    assert kinds == [("unreadable", "block"), ("judgment", "review"), ("duplicate", "review")]


def test_analysis_moment_selects_rules_and_case_basis_selects_for_parity() -> None:
    late = dataclasses.replace(
        BASE, rules=tuple(
            dataclasses.replace(r, effective_from=datetime(2026, 9, 1, tzinfo=UTC))
            if r.rule_id == "DF-2" else r for r in BASE.rules))
    case = fence("A", 6.5)
    assert evaluate_case(case, late).recommendation == "deny"
    at_case = evaluate_case(case, late, rules_at="case")  # DF-2 is not yet in force then
    assert all(r["rule_id"] != "DF-2" for r in at_case.rule_results)
    assert at_case.recommendation != "deny"
    assert ANALYSIS_AT > datetime(2026, 9, 1, tzinfo=UTC)

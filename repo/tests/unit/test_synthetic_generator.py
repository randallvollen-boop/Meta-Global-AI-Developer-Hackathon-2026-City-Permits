"""The shared synthetic-year generator: bounded, deterministic, dated, spread.

P3policy reuses this generator, so the tests pin its public API: explicit
bounded ``seed`` and ``count``, versioned distributions in config, twelve
months of dated arrivals and values on both sides of every threshold.
"""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from acme_city.portal_intake.scenarios import (
    PERMIT_TYPE_KEYS,
    SyntheticCase,
    generate_synthetic_year,
    load_distributions,
)

SEED = 4242
COUNT = 1500


@pytest.fixture(scope="module")
def year():
    return generate_synthetic_year(seed=SEED, count=COUNT)


def test_the_same_seed_and_count_build_the_same_year(year) -> None:
    again = generate_synthetic_year(seed=SEED, count=COUNT)
    assert again == year
    assert [case.number for case in again.cases] == [case.number for case in year.cases]


def test_a_different_seed_builds_a_different_year(year) -> None:
    other = generate_synthetic_year(seed=SEED + 1, count=COUNT)
    assert other.cases != year.cases


def test_the_generator_is_a_pure_function_of_its_arguments(year) -> None:
    # Generating something else in between changes nothing: no hidden state.
    generate_synthetic_year(seed=1, count=5)
    assert generate_synthetic_year(seed=SEED, count=COUNT) == year


@pytest.mark.parametrize(
    ("seed", "count"),
    [(-1, 10), (2**31, 10), (1, 0), (1, 2001), (1.5, 10), (1, 2.5), (True, 10), (1, False)],
)
def test_seed_and_count_are_bounded(seed, count) -> None:
    with pytest.raises(ValueError):
        generate_synthetic_year(seed=seed, count=count)


def test_the_bounds_come_from_the_versioned_config() -> None:
    config = load_distributions()
    assert config["distribution_version"] == "1"
    assert config["population_id"] == "synthetic-year-v1"
    limits = config["limits"]
    assert generate_synthetic_year(seed=limits["max_seed"], count=limits["min_count"]).count == 1
    assert generate_synthetic_year(seed=0, count=limits["max_count"]).count == limits["max_count"]


def test_the_distributions_are_versioned_and_drive_the_output() -> None:
    config = load_distributions()
    config["district_weights"] = {"R-1": 1}
    config["type_weights"] = {"R-1": {"shed": 1}}
    custom = generate_synthetic_year(seed=1, count=40, distributions=config)
    assert {case.permit_type_key for case in custom.cases} == {"shed"}
    assert {case.district for case in custom.cases} == {"R-1"}
    assert custom.distribution_version == "1"


def test_cases_cover_twelve_months_of_dated_arrivals(year) -> None:
    months = {case.arrived_at.strftime("%Y-%m") for case in year.cases}
    assert len(months) >= 12
    assert min(case.arrived_at for case in year.cases) >= year.window_start
    assert max(case.arrived_at for case in year.cases) <= year.window_end
    assert (year.window_end - year.window_start).days == 365
    ordered = [case.arrived_at for case in year.cases]
    assert ordered == sorted(ordered)
    assert len({case.number for case in year.cases}) == COUNT


def test_the_cases_use_all_seventeen_types_across_the_districts(year) -> None:
    assert {case.permit_type_key for case in year.cases} == set(PERMIT_TYPE_KEYS)
    assert {case.district for case in year.cases} == {"R-1", "R-2", "C-2"}


def test_decision_and_issuance_dates_follow_each_lifecycle(year) -> None:
    for case in year.cases:
        if case.decided_at is not None:
            assert case.decided_at >= case.arrived_at
            assert case.decided_at <= year.window_end
            assert case.outcome in {"approved", "denied"}
        if case.issued_at is not None:
            assert case.decided_at is not None and case.outcome == "approved"
            assert case.issued_at >= case.decided_at
            assert case.issued_at <= year.window_end
            assert case.permit_number and case.status == "issued"
        else:
            assert case.permit_number is None
        if case.outcome == "denied":
            assert case.denial_reason_code and case.issued_at is None
        if case.status in {"withdrawn", "returned", "archived"}:
            assert case.decided_at is None and case.outcome is None
    statuses = Counter(case.status for case in year.cases)
    assert statuses["issued"] > 0 and statuses["denied"] > 0
    assert statuses["withdrawn"] + statuses["returned"] > 0


def test_conditions_waivers_and_denials_appear_in_plausible_proportions(year) -> None:
    decided = [case for case in year.cases if case.outcome]
    denied = [case for case in decided if case.outcome == "denied"]
    with_conditions = [case for case in decided if case.conditions]
    waived = [case for case in decided if case.waivers]
    assert 0.05 < len(denied) / len(decided) < 0.45
    assert 0.05 < len(with_conditions) / len(decided) < 0.6
    assert 0 < len(waived) < len(decided) * 0.2
    for case in waived:
        assert case.outcome == "approved"  # a waiver never clears a denial


def fences(year: object) -> list[SyntheticCase]:
    return [case for case in year.cases if case.facts.get("structure_kind") == "fence"]


def test_fence_heights_straddle_every_threshold_in_both_yards(year) -> None:
    for location in ("front", "side_rear"):
        heights = {
            case.facts["height_ft"] for case in fences(year) if case.facts["location"] == location
        }
        assert any(h < 6 for h in heights), (location, heights)
        assert any(h == 6 for h in heights), (location, heights)
        assert any(6 < h < 7 for h in heights), (location, heights)
        assert any(h == 7 for h in heights), (location, heights)
        assert any(h > 7 for h in heights), (location, heights)
    front = {c.facts["height_ft"] for c in fences(year) if c.facts["location"] == "front"}
    assert min(front) < 4 and 4 in front and max(front) > 4


def test_fence_outcomes_follow_the_published_limits(year) -> None:
    for case in fences(year):
        limit = 4 if case.facts["location"] == "front" else 6
        if case.status in {"withdrawn", "returned", "archived", "submitted", "under_review"}:
            continue
        assert (case.outcome == "denied") == (case.facts["height_ft"] > limit)


def test_shed_areas_straddle_the_200_and_600_sq_ft_thresholds(year) -> None:
    areas = {case.facts["shed_area_sqft"] for case in year.cases if case.permit_type_key == "shed"}
    assert any(a < 200 for a in areas) and any(a == 200 for a in areas) and any(a > 200 for a in areas)
    assert any(a <= 600 for a in areas) and any(a > 600 for a in areas)


def test_variances_concentrate_in_one_district_and_a_few_parcels(year) -> None:
    variances = [c for c in year.cases if c.permit_type_key == "zoning_variance"]
    by_district = Counter(c.district for c in variances)
    top_district, top_count = by_district.most_common(1)[0]
    assert top_district == "R-2" and top_count / len(variances) > 0.7
    parcels = Counter(c.parcel_number for c in variances if c.district == "R-2")
    assert sum(n for _, n in parcels.most_common(5)) / sum(parcels.values()) > 0.6
    assert all("variance" in c.exception_kinds for c in variances)


def test_residential_types_sit_in_residential_districts_and_commercial_in_commercial(year) -> None:
    for case in year.cases:
        if case.permit_type_key in {"sign", "patio", "change_occupancy", "fire_alarm", "com_ti"}:
            assert case.district == "C-2"
            assert case.business_name and case.business_category
        if case.permit_type_key in {"deck_fence", "shed"}:
            assert case.district in {"R-1", "R-2"}
            assert case.business_name is None


def test_restaurants_and_bars_are_a_visible_share_of_commercial_permits(year) -> None:
    commercial = [c for c in year.cases if c.business_category]
    dining = [c for c in commercial if c.business_category in {"restaurant", "bar"}]
    assert len(dining) / len(commercial) > 0.35
    assert {c.business_category for c in commercial} == {"restaurant", "bar", "retail", "office", "other"}


def test_a_generated_case_holds_no_contact_detail_or_person_in_its_text(year) -> None:
    for case in year.cases:
        blob = json.dumps(case.facts) + case.description
        assert "@" not in blob
        assert case.applicant_name.split()[0] not in case.description
        assert case.number.startswith("SYNTH-")
        assert "(synthetic)" in case.description or case.permit_type_key == "zoning_variance"


def test_the_generator_reads_only_committed_files() -> None:
    source = (Path(__file__).resolve().parents[2] / "src/acme_city/portal_intake/scenarios.py").read_text()
    section = source[source.index("The synthetic year."):]
    for forbidden in ("import sqlalchemy", "utc_now", "datetime.now", "requests", "httpx", "MuseService"):
        assert forbidden not in section


def test_default_scenarios_keep_their_names_and_defaults() -> None:
    from acme_city.portal_intake.scenarios import SCENARIO_NAMES, build_scenario

    assert "random" in SCENARIO_NAMES
    first = build_scenario("random", count=3)
    assert first == build_scenario("random", count=3)
    assert len(first) == 3

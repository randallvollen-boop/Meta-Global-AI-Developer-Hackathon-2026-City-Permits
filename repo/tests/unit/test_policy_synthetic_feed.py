"""The synthetic-year feed adapts the shared generator; it is not a generator."""
# REQUIRES: PER-02
# The population is deterministic for a seed and a count, labelled synthetic,
# and built from the shared generator.

from __future__ import annotations

import pytest
from policy_helpers import catalogue_baseline

from acme_city.policy.changes import apply_scenario, fence_height_limit_scenario
from acme_city.policy.impact import compute_impact
from acme_city.policy.population import KIND_SYNTHETIC_YEAR, PopulationFeed
from acme_city.policy.synthetic_feed import (
    SYNTHETIC_GENERATOR_VERSION,
    SYNTHETIC_LABEL,
    SyntheticFilter,
    SyntheticYearFeed,
)
from acme_city.portal_intake.scenarios import generate_synthetic_year


def test_the_feed_satisfies_the_population_feed_contract() -> None:
    feed: PopulationFeed = SyntheticYearFeed()
    population = feed.build(seed=7, count=120)
    definition = population.definition
    assert definition.kind == KIND_SYNTHETIC_YEAR and definition.synthetic is True
    assert definition.seed == 7
    assert definition.generator_version == SYNTHETIC_GENERATOR_VERSION
    assert definition.display_label == SYNTHETIC_LABEL == "Synthetic year (sample data)"
    assert population.size == 120
    assert population.validate(catalogue_baseline()) == []


def test_the_same_seed_and_count_give_the_same_population_hash() -> None:
    first = SyntheticYearFeed().build(seed=11, count=150)
    again = SyntheticYearFeed().build(seed=11, count=150)
    other_seed = SyntheticYearFeed().build(seed=12, count=150)
    other_count = SyntheticYearFeed().build(seed=11, count=151)
    assert first.population_hash == again.population_hash
    assert first.population_hash not in {other_seed.population_hash, other_count.population_hash}


def test_the_cases_are_the_shared_generators_cases_not_a_second_generator() -> None:
    year = generate_synthetic_year(seed=21, count=90)
    population = SyntheticYearFeed().build(seed=21, count=90)
    assert [c.case_ref for c in population.cases] == [c.number for c in year.cases]
    assert [c.permit_type_key for c in population.cases] == [c.permit_type_key for c in year.cases]
    assert [c.basis_at for c in population.cases] == [c.arrived_at for c in year.cases]
    for case, source in zip(population.cases, year.cases, strict=True):
        assert dict(case.facts) == source.facts


def test_the_fence_heights_straddle_the_changed_limit() -> None:
    baseline = catalogue_baseline()
    population = SyntheticYearFeed().build(seed=20261028, count=600)
    result = compute_impact(population, baseline, apply_scenario(baseline, fence_height_limit_scenario()))
    heights = sorted(
        {c.facts_map["height_ft"] for c in population.cases
         if c.facts_map.get("structure_kind") == "fence" and c.facts_map.get("location") == "side_rear"}
    )
    assert min(heights) < 6 and max(heights) > 7, "both sides of the 6 ft and 7 ft limits"
    assert result.changed_case_count > 0
    assert all(d.direction == "relaxed" for d in result.case_diffs if d.changed)


def test_a_narrowed_population_is_a_subset_and_says_so() -> None:
    full = SyntheticYearFeed().build(seed=5, count=300)
    narrowed = SyntheticYearFeed(filters=SyntheticFilter(permit_type="shed")).build(seed=5, count=300)
    assert 0 < narrowed.size < full.size
    assert {c.permit_type_key for c in narrowed.cases} == {"shed"}
    assert "narrowed to type shed" in narrowed.definition.display_label
    assert narrowed.definition.synthetic is True


def test_the_bounds_of_the_generator_are_kept() -> None:
    with pytest.raises(ValueError):
        SyntheticYearFeed().build(seed=1, count=0)
    with pytest.raises(ValueError):
        SyntheticYearFeed().build(seed=-1, count=10)
    with pytest.raises(ValueError):
        SyntheticYearFeed().build(seed=1, count=10**6)

"""Fixture validation tests.

These tests read the committed configuration and fixture documents and prove
that the bundle is coherent, fictional and free of evaluator truth.
"""

from __future__ import annotations

import json

import pytest

from acme_city.fixtures.loader import REPO_ROOT, FixtureBundle, canonical_json
from acme_city.fixtures.schemas import (
    ActorCatalog,
    BasePopulation,
    ContractCatalog,
    DemoConfig,
    DomainCatalog,
    PermissionCatalog,
    PolicyCatalog,
    RuleCatalog,
    SourceVariations,
)

CONFIG_DIR = REPO_ROOT / "config"
FIXTURE_DIR = REPO_ROOT / "fixtures"
RUNTIME_PACKAGE = REPO_ROOT / "src" / "acme_city"

BUSINESS_APPROVAL_PERMISSIONS = {
    "permit.decide",
    "permit.issue",
    "finance.allocation.confirm",
    "registry.crosswalk.decide",
    "rule.version.publish",
    "governance.authority_policy.publish",
}


@pytest.fixture(scope="module")
def bundle() -> FixtureBundle:
    return FixtureBundle.load()


def test_configuration_documents_validate() -> None:
    PermissionCatalog.model_validate(json.loads((CONFIG_DIR / "permissions.json").read_text()))
    ActorCatalog.model_validate(json.loads((CONFIG_DIR / "actors.json").read_text()))
    DomainCatalog.model_validate(json.loads((CONFIG_DIR / "domains.json").read_text()))
    ContractCatalog.model_validate(json.loads((CONFIG_DIR / "source_contracts.json").read_text()))
    PolicyCatalog.model_validate(json.loads((CONFIG_DIR / "authority_policies.json").read_text()))
    RuleCatalog.model_validate(json.loads((CONFIG_DIR / "rules_and_fees.json").read_text()))
    DemoConfig.model_validate(json.loads((CONFIG_DIR / "demo.json").read_text()))
    BasePopulation.model_validate(json.loads((FIXTURE_DIR / "base_population.json").read_text()))
    SourceVariations.model_validate(json.loads((FIXTURE_DIR / "source_variations.json").read_text()))


def test_bundle_loads_and_validates(bundle: FixtureBundle) -> None:
    assert bundle.fixture_version
    assert bundle.demo.fixture_version == bundle.fixture_version


def test_expected_configuration_inventory(bundle: FixtureBundle) -> None:
    assert len(bundle.actors.roles) == 17
    assert len(bundle.actors.personas) == 5
    assert len(bundle.actors.service_identities) == 17
    assert len(bundle.domains.domains) == 11
    assert len(bundle.domains.steward_queues) == 10
    assert len(bundle.policies.authority_policies) == 19
    assert len(bundle.rules.permit_types) == 17
    assert len(bundle.demo.reason_codes) == 12


def test_exactly_five_selectable_personas(bundle: FixtureBundle) -> None:
    labels = [persona.label for persona in bundle.actors.personas]
    assert labels == [
        "Applicant",
        "Data Steward",
        "Permit Reviewer",
        "City Administrator",
        "Agent Operator",
    ]
    assert all(persona.selectable for persona in bundle.actors.personas)
    assert all(not identity.selectable for identity in bundle.actors.service_identities)


def test_every_actor_carries_explicit_grants(bundle: FixtureBundle) -> None:
    for actor in bundle.all_actors:
        assert actor.grants, f"{actor.actor_id} has no explicit grant"
        for grant in actor.grants:
            assert grant.permission_id


def test_administrator_role_holds_no_business_approval_permission(
    bundle: FixtureBundle,
) -> None:
    administrator_role = next(
        role for role in bundle.actors.roles if role.role_id == "administrator"
    )
    assert set(administrator_role.permission_ids) & BUSINESS_APPROVAL_PERMISSIONS == set()


def test_reviewer_authority_belongs_to_the_permit_reviewer_persona(
    bundle: FixtureBundle,
) -> None:
    reviewer = next(
        persona for persona in bundle.actors.personas if persona.actor_id == "persona_permit_reviewer"
    )
    granted = {grant.permission_id for grant in reviewer.grants}
    assert "permit.decide" in granted
    assert "permit.issue" in granted
    assert "finance.allocation.confirm" not in granted

    administrator = next(
        persona
        for persona in bundle.actors.personas
        if persona.actor_id == "persona_city_administrator"
    )
    administrator_grants = {grant.permission_id for grant in administrator.grants}
    assert "permit.decide" not in administrator_grants
    assert "permit.issue" not in administrator_grants
    assert "finance.allocation.confirm" in administrator_grants


def test_data_owner_holds_no_source_write_permission(bundle: FixtureBundle) -> None:
    owner = next(
        identity
        for identity in bundle.actors.service_identities
        if identity.actor_id == "service_owner_building_safety"
    )
    granted = {grant.permission_id for grant in owner.grants}
    assert "source.record.update" not in granted
    assert "permit.decide" not in granted
    assert "finance.allocation.confirm" not in granted


def test_every_queue_has_a_primary_delegate_escalation_and_target(
    bundle: FixtureBundle,
) -> None:
    for queue in bundle.domains.steward_queues:
        assert queue.primary_actor_id, f"{queue.queue_id} has no primary steward"
        assert queue.delegate_actor_id, f"{queue.queue_id} has no delegate"
        assert queue.escalation_actor_id, f"{queue.queue_id} has no escalation owner"
        target = queue.first_review_target
        assert target.get("quantity") == 1
        assert target.get("unit") == "business_day"
        assert target.get("service_promise") is False


def test_permit_configurations_and_baseline_rules_are_preserved(bundle: FixtureBundle) -> None:
    permit_types = {permit_type.key for permit_type in bundle.rules.permit_types}
    assert permit_types == {
        "res_building",
        "deck_fence",
        "com_ti",
        "sign",
        "row_encroachment",
        "patio",
        "shed",
        "pod",
        "hvac",
        "water_heater",
        "residential_electric",
        "fire_alarm",
        "change_occupancy",
        "site_plan_review",
        "rezoning",
        "zoning_variance",
        "certificate_appropriateness",
    }
    baseline = {
        rule.rule_id for rule in bundle.rules.rules if rule.source_mapping.get("baseline_rule_id")
    }
    assert len(baseline) == 27


def test_each_executable_rule_has_exactly_one_citation(bundle: FixtureBundle) -> None:
    by_rule: dict[str, set[str]] = {}
    for rule in bundle.rules.rules:
        by_rule.setdefault(rule.rule_id, set()).add(rule.citation)
    for rule_id, citations in by_rule.items():
        assert len(citations) == 1, f"rule {rule_id} carries more than one citation"
        assert all(citation.strip() for citation in citations)


def test_rule_source_mappings_are_recorded(bundle: FixtureBundle) -> None:
    for rule in bundle.rules.rules:
        mapping = rule.source_mapping
        assert mapping.get("baseline_rule_id")
        assert mapping.get("citation_selected")
        assert mapping.get("citation_count") == 1


def test_fee_schedule_uses_exact_minor_units_and_one_rounding(bundle: FixtureBundle) -> None:
    published = [
        schedule
        for schedule in bundle.rules.fee_schedules
        if schedule.status == "published"
    ]
    assert published
    definition = published[0].definition
    assert definition["fixed_review_charge_cents"] == 10000
    assert definition["valuation_multiplier"] == "0.001"
    assert definition["rounding"] == "ROUND_HALF_UP"
    assert definition["rounding_scope"] == "variable_component_once"
    assert definition["version_basis"] == "initial_submitted_at"
    assert definition["example_total_cents"] == 15000


def test_all_eleven_scenarios_have_starting_conditions(bundle: FixtureBundle) -> None:
    scenarios = {scenario.scenario_id: scenario for scenario in bundle.demo.scenarios}
    assert set(scenarios) == {f"D{index:02d}" for index in range(1, 12)}
    population = bundle.base_population
    known_records: set[str] = set()
    for party in population.parties:
        known_records.add(party.party_id)
    for credential in population.credentials:
        known_records.add(credential.credential_id)
    for account in population.finance_accounts:
        known_records.add(account.account_id)
    for application in population.applications:
        known_records.add(application.application_id)
    for payment in population.payments:
        known_records.add(payment.payment_id)
    for parcel in population.parcels:
        known_records.add(parcel.parcel_id)
    for address in population.addresses:
        known_records.add(address.address_id)
    for contact in population.party_contacts:
        known_records.add(contact.contact_id)
    for permit_row in population.permits:
        known_records.add(permit_row.permit_id)
    for assessment in population.assessments:
        known_records.add(assessment.assessment_id)
    source_record_ids = {
        variation.source_record_id for variation in bundle.source_variations.source_variations
    }
    for scenario_id, scenario in scenarios.items():
        assert scenario.condition
        assert scenario.related_records
        for record in scenario.related_records:
            assert record in known_records or record in source_record_ids, (
                f"{scenario_id} references an unknown record: {record}"
            )


def test_d01_starts_with_unresolved_links_and_an_unallocated_payment(
    bundle: FixtureBundle,
) -> None:
    d01_related = {
        record
        for scenario in bundle.demo.scenarios
        if scenario.scenario_id == "D01"
        for record in scenario.related_records
    }
    assert "app_synth_001" in d01_related

    application = next(
        app
        for app in bundle.base_population.applications
        if app.application_id == "app_synth_001"
    )
    assert application.status == "submitted"
    assert application.submitted_facts["submitted_site_text"] == "400 Lantern Row, Suite 2, ACME City"

    account = next(
        item
        for item in bundle.base_population.finance_accounts
        if item.account_id == "facct_cedarline_legacy"
    )
    assert account.link_status == "unlinked"
    assert account.party_id is None

    payment = next(
        item
        for item in bundle.base_population.payments
        if item.payment_id == "payment_d01_settled"
    )
    assert payment.settlement_status == "settled"
    assert payment.amount_cents == 15000
    allocations = [
        allocation
        for allocation in bundle.base_population.allocations
        if allocation.payment_id == payment.payment_id
    ]
    assert allocations == []


def test_d02_false_friend_stays_a_separate_party(bundle: FixtureBundle) -> None:
    false_friend = next(
        party
        for party in bundle.base_population.parties
        if party.party_id == "party_false_friend"
    )
    cedarline = next(
        party for party in bundle.base_population.parties if party.party_id == "party_cedarline"
    )
    assert false_friend.party_id != cedarline.party_id
    assert false_friend.display_name != cedarline.display_name
    units = {
        address.unit_number
        for address in bundle.base_population.addresses
        if address.address_id in {"address_400_lantern_unit_2", "address_400_lantern_unit_5"}
    }
    assert units == {"2", "5"}


def test_d04_leaves_the_parcel_unresolved(bundle: FixtureBundle) -> None:
    site = next(
        item
        for item in bundle.base_population.application_sites
        if item.application_id == "app_d04"
    )
    assert site.parcel_id is None
    assert site.resolution_status == "unresolved"
    parcel_numbers = {parcel.source_parcel_number for parcel in bundle.base_population.parcels}
    assert "ACME-P-9999" not in parcel_numbers


def test_d03_credential_expired_before_the_decision_date(bundle: FixtureBundle) -> None:
    credential = next(
        item
        for item in bundle.base_population.credentials
        if item.credential_id == "cred_contractor_halcyon"
    )
    assert credential.status == "expired"
    assert credential.valid_to is not None
    assert credential.valid_to.year == 2026
    assert credential.valid_to.month == 5


def test_d10_feed_is_staged_without_a_registered_contract(bundle: FixtureBundle) -> None:
    staged = [
        variation
        for variation in bundle.source_variations.source_variations
        if variation.record_status == "staged"
    ]
    assert staged
    registered_datasets = {
        contract.dataset_key for contract in bundle.contracts.source_contracts
    }
    for variation in staged:
        assert variation.source_dataset_id not in registered_datasets


def test_source_variations_keep_separate_source_effective_and_receipt_times(
    bundle: FixtureBundle,
) -> None:
    for variation in bundle.source_variations.source_variations:
        assert variation.ingested_at is not None
        assert variation.source_record_version
        assert variation.source_updated_at is not None or variation.effective_from is None


def test_evaluator_truth_is_absent_from_runtime_fixture_objects(bundle: FixtureBundle) -> None:
    serialized = canonical_json(
        {
            "actors": bundle.actors.model_dump(mode="json"),
            "permissions": bundle.permissions.model_dump(mode="json"),
            "domains": bundle.domains.model_dump(mode="json"),
            "contracts": bundle.contracts.model_dump(mode="json"),
            "policies": bundle.policies.model_dump(mode="json"),
            "rules": bundle.rules.model_dump(mode="json"),
            "demo": bundle.demo.model_dump(mode="json"),
            "base_population": bundle.base_population.model_dump(mode="json"),
            "source_variations": bundle.source_variations.model_dump(mode="json"),
        }
    )
    assert "evaluator_truth" not in serialized
    assert "truth_" not in serialized
    assert "expected_disposition" not in serialized
    assert "expected_links" not in serialized


def test_no_runtime_module_references_the_evaluator_truth_file() -> None:
    offenders: list[str] = []
    for path in sorted(RUNTIME_PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "evaluator_truth" in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == [], f"runtime modules reference the evaluator truth file: {offenders}"


def test_every_record_is_fictional() -> None:
    population = json.loads((FIXTURE_DIR / "base_population.json").read_text())
    serialized = canonical_json(population)
    assert "@example.invalid" in serialized
    for contact in population["party_contacts"]:
        if contact["contact_type"] == "email":
            assert contact["value"].endswith("example.invalid")
        if contact["contact_type"] == "phone":
            assert contact["value"].startswith("+1-555-01")
    assert "ACME City" in serialized

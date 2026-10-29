"""Fixture bundle loading and validation.

The loader reads the committed configuration and fixture documents, validates
them, and prepares the deterministic rows the reset writes.  It deliberately
never reads the evaluator truth file: that file belongs to an evaluator, not to
a runtime service.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acme_city.core.errors import ValidationError
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

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIRNAME = "config"
FIXTURE_DIRNAME = "fixtures"


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text used for hashing and comparison."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(payload: dict[str, Any]) -> str:
    """Return the SHA-256 hash of a raw source payload."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"fixture document is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"fixture document is not valid JSON: {path.name}") from exc


@dataclass(frozen=True)
class FixtureBundle:
    """The validated fixture and configuration documents for one run."""

    fixture_version: str
    root: Path
    demo: DemoConfig
    actors: ActorCatalog
    permissions: PermissionCatalog
    domains: DomainCatalog
    contracts: ContractCatalog
    policies: PolicyCatalog
    rules: RuleCatalog
    base_population: BasePopulation
    source_variations: SourceVariations
    source_snapshots: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | str | None = None) -> FixtureBundle:
        """Load and validate the fixture bundle rooted at ``path``.

        Args:
            path: The repository root that holds ``config/`` and ``fixtures/``.
                Defaults to the installed source tree.
        """
        root = Path(path) if path is not None else REPO_ROOT
        config_dir = root / CONFIG_DIRNAME
        fixture_dir = root / FIXTURE_DIRNAME

        demo = DemoConfig.model_validate(_read_json(config_dir / "demo.json"))
        actors = ActorCatalog.model_validate(_read_json(config_dir / "actors.json"))
        permissions = PermissionCatalog.model_validate(_read_json(config_dir / "permissions.json"))
        domains = DomainCatalog.model_validate(_read_json(config_dir / "domains.json"))
        contracts = ContractCatalog.model_validate(_read_json(config_dir / "source_contracts.json"))
        policies = PolicyCatalog.model_validate(_read_json(config_dir / "authority_policies.json"))
        rules = RuleCatalog.model_validate(_read_json(config_dir / "rules_and_fees.json"))
        base_population = BasePopulation.model_validate(_read_json(fixture_dir / "base_population.json"))
        variations = SourceVariations.model_validate(_read_json(fixture_dir / "source_variations.json"))

        bundle = cls(
            fixture_version=demo.fixture_version,
            root=root,
            demo=demo,
            actors=actors,
            permissions=permissions,
            domains=domains,
            contracts=contracts,
            policies=policies,
            rules=rules,
            base_population=base_population,
            source_variations=variations,
        )
        bundle.validate()
        return bundle

    # ------------------------------------------------------------------ checks

    def validate(self) -> None:
        """Check that the bundle is internally coherent."""
        problems: list[str] = []

        if self.demo.fixture_version != self.base_population.fixture_version:
            problems.append("the demo configuration and the base population declare different versions")
        if self.demo.fixture_version != self.source_variations.fixture_version:
            problems.append("the demo configuration and the source variations declare different versions")

        permission_ids = {entry.permission_id for entry in self.permissions.permissions}
        role_ids = {role.role_id for role in self.actors.roles}
        actor_ids = {actor.actor_id for actor in self.all_actors}
        domain_ids = {domain.domain_id for domain in self.domains.domains}
        queue_ids = {queue.queue_id for queue in self.domains.steward_queues}
        policy_ids = {policy.policy_id for policy in self.policies.authority_policies}

        for role in self.actors.roles:
            unknown = set(role.permission_ids) - permission_ids
            if unknown:
                problems.append(f"role {role.role_id} references unknown permissions: {sorted(unknown)}")
        for role_id, grants in self.permissions.role_grants.items():
            if role_id not in role_ids:
                problems.append(f"role grants reference an unknown role: {role_id}")
            unknown = set(grants) - permission_ids
            if unknown:
                problems.append(f"role {role_id} grants unknown permissions: {sorted(unknown)}")

        if len(self.actors.personas) != 5:
            problems.append(
                f"expected exactly five selectable personas, found {len(self.actors.personas)}"
            )
        for persona in self.actors.personas:
            if not persona.selectable:
                problems.append(f"persona {persona.actor_id} is not selectable")
            unknown_roles = set(persona.source_role_ids) - role_ids
            if unknown_roles:
                problems.append(
                    f"persona {persona.actor_id} references unknown roles: {sorted(unknown_roles)}"
                )
        for identity in self.actors.service_identities:
            if identity.selectable:
                problems.append(
                    f"service identity {identity.actor_id} must not be selectable"
                )
            unknown_roles = set(identity.role_ids) - role_ids
            if unknown_roles:
                problems.append(
                    f"service identity {identity.actor_id} references unknown roles: "
                    f"{sorted(unknown_roles)}"
                )
        for actor in self.all_actors:
            unknown_domains = set(actor.domain_scope) - domain_ids
            if unknown_domains:
                problems.append(f"actor {actor.actor_id} references unknown domains: {sorted(unknown_domains)}")
            for grant in actor.grants:
                if grant.permission_id not in permission_ids:
                    problems.append(
                        f"actor {actor.actor_id} grants an unknown permission: {grant.permission_id}"
                    )
                unknown = set(grant.domains) - domain_ids
                if unknown:
                    problems.append(
                        f"actor {actor.actor_id} grants an unknown domain: {sorted(unknown)}"
                    )

        for domain in self.domains.domains:
            if domain.steward_queue_id and domain.steward_queue_id not in queue_ids:
                problems.append(
                    f"domain {domain.domain_id} references an unknown queue: {domain.steward_queue_id}"
                )
            if domain.accountable_owner_actor_id and domain.accountable_owner_actor_id not in actor_ids:
                problems.append(
                    f"domain {domain.domain_id} references an unknown owner actor"
                )
        for queue in self.domains.steward_queues:
            if queue.domain_id not in domain_ids:
                problems.append(f"queue {queue.queue_id} references an unknown domain")
            for field_name in ("primary_actor_id", "delegate_actor_id", "escalation_actor_id"):
                value = getattr(queue, field_name)
                if value and value not in actor_ids:
                    problems.append(f"queue {queue.queue_id} references an unknown {field_name}")

        for contract in self.contracts.source_contracts:
            if contract.domain_id and contract.domain_id not in domain_ids:
                problems.append(f"contract {contract.contract_id} references an unknown domain")
            if contract.authority_policy_id and contract.authority_policy_id not in policy_ids:
                problems.append(f"contract {contract.contract_id} references an unknown authority policy")
            if contract.steward_queue_id and contract.steward_queue_id not in queue_ids:
                problems.append(f"contract {contract.contract_id} references an unknown steward queue")

        for policy in self.policies.authority_policies:
            if policy.domain_id and policy.domain_id not in domain_ids:
                problems.append(f"authority policy {policy.policy_id} references an unknown domain")

        permit_type_keys = {permit_type.key for permit_type in self.rules.permit_types}
        for rule in self.rules.rules:
            if rule.permit_type and rule.permit_type not in permit_type_keys:
                problems.append(f"rule {rule.rule_id} references an unknown permit type")
            if not rule.citation:
                problems.append(f"rule {rule.rule_id} has no citation")
        citations: dict[str, str] = {}
        for rule in self.rules.rules:
            previous = citations.get(rule.rule_id)
            if previous is not None and previous != rule.citation:
                problems.append(f"rule {rule.rule_id} has more than one citation")
            citations[rule.rule_id] = rule.citation

        party_ids = {party.party_id for party in self.base_population.parties}
        for contact in self.base_population.party_contacts:
            if contact.party_id not in party_ids:
                problems.append(f"contact {contact.contact_id} references an unknown party")
        for alias in self.base_population.party_aliases:
            if alias.party_id not in party_ids:
                problems.append(f"alias {alias.alias_id} references an unknown party")
        for credential in self.base_population.credentials:
            if credential.holder_party_id not in party_ids:
                problems.append(f"credential {credential.credential_id} references an unknown holder")
        for account in self.base_population.finance_accounts:
            if account.party_id and account.party_id not in party_ids:
                problems.append(f"account {account.account_id} references an unknown party")

        application_ids = {app.application_id for app in self.base_population.applications}
        for app in self.base_population.applications:
            if app.permit_type not in permit_type_keys:
                problems.append(f"application {app.application_id} references an unknown permit type")
            if app.applicant_party_id and app.applicant_party_id not in party_ids:
                problems.append(f"application {app.application_id} references an unknown applicant party")
        for member in self.base_population.application_parties:
            if member.application_id not in application_ids:
                problems.append(f"application party {member.application_party_id} references an unknown application")
            if member.party_id not in party_ids:
                problems.append(f"application party {member.application_party_id} references an unknown party")
        for site in self.base_population.application_sites:
            if site.application_id not in application_ids:
                problems.append(f"application site {site.application_site_id} references an unknown application")
        for revision in self.base_population.application_revisions:
            if revision.application_id not in application_ids:
                problems.append(f"application revision {revision.revision_id} references an unknown application")

        payment_ids = {payment.payment_id for payment in self.base_population.payments}
        for event in self.base_population.payment_events:
            if event.payment_id not in payment_ids:
                problems.append(f"payment event {event.event_id} references an unknown payment")

        scenario_ids = {scenario.scenario_id for scenario in self.demo.scenarios}
        if len(scenario_ids) != 11:
            problems.append(f"expected 11 controlled scenarios, found {len(scenario_ids)}")

        if problems:
            raise ValidationError(
                "the fixture bundle is not coherent: " + "; ".join(problems[:10]),
                problems=problems,
            )

    # ------------------------------------------------------------------ helpers

    @property
    def all_actors(self) -> list[Any]:
        """Return every seeded identity: the personas and the service identities."""
        return [*self.actors.personas, *self.actors.service_identities]

    def source_snapshot_rows(self) -> list[dict[str, Any]]:
        """Return the deterministic source snapshot rows for the seeded variations."""
        rows: list[dict[str, Any]] = []
        for index, variation in enumerate(self.source_variations.source_variations, start=1):
            rows.append(
                {
                    "source_snapshot_id": f"snap_{variation.source_system_id}_{variation.source_record_id}_v{variation.source_record_version}",
                    "source_system_id": variation.source_system_id,
                    "source_dataset_id": variation.source_dataset_id,
                    "source_record_id": variation.source_record_id,
                    "source_record_version": variation.source_record_version,
                    "source_updated_at": variation.source_updated_at,
                    "effective_from": variation.effective_from,
                    "effective_to": variation.effective_to,
                    "ingested_at": variation.ingested_at,
                    "payload_hash": payload_hash(variation.payload),
                    "raw_payload": variation.payload,
                    "record_status": variation.record_status,
                    "scenario_id": variation.scenario_id,
                    "correlation_id": f"corr_seed_{index:04d}",
                }
            )
        return rows


__all__ = ["FixtureBundle", "REPO_ROOT", "canonical_json", "payload_hash"]

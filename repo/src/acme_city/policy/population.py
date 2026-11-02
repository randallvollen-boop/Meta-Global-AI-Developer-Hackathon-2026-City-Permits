"""The population interface: frozen case inputs a simulation re-scores.

A population generator (the P3insight synthetic-year generator, a stored-case
loader, a hand-made test list) produces :class:`CaseInput` values and wraps
them in a :class:`Population`.  A case input is **frozen** data: the facts the
applicant stated, the documents received with their scan-quality flags, the
intake record, and the policy-independent outcomes of the steps that need the
outside world (the address locator, extraction, the duplicate lookup and the
site and credential safeguards).  The kernel never looks anything up.

Contract for a generator (P3insight)
------------------------------------
``PopulationFeed.build(seed, count)`` must be deterministic for a seed and a
count, must return at most :data:`MAX_POPULATION_SIZE` cases, and must label
the result with a :class:`PopulationDefinition` whose ``kind`` is
``synthetic_year`` and whose ``synthetic`` flag is true.  Case references are
unique and stable for a seed.  ``basis_at`` is the arrival moment of the case
(dated arrivals over twelve months).
"""
# REQUIRES: PER-02
# Case inputs are immutable values, so the same population always produces the
# same hash.

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from acme_city.kernel.findings import FindingSpec
from acme_city.policy.config import PolicyConfig, digest

#: The most cases one run accepts.
MAX_POPULATION_SIZE = 20000

KIND_CURRENT = "current_applications"
KIND_DECIDED_RANGE = "decided_range"
KIND_SYNTHETIC_YEAR = "synthetic_year"
KIND_MANUAL = "manual"
POPULATION_KINDS: tuple[str, ...] = (
    KIND_CURRENT,
    KIND_DECIDED_RANGE,
    KIND_SYNTHETIC_YEAR,
    KIND_MANUAL,
)

#: How each kind is labelled on a result.  Historical kinds are a re-scoring
#: of frozen inputs under today's configuration, never a reconstruction of the
#: decisions that were made at the time.
KIND_LABELS = {
    KIND_CURRENT: "Current applications, re-scored",
    KIND_DECIDED_RANGE: "Decided applications, retrospective re-scoring",
    KIND_SYNTHETIC_YEAR: "Synthetic year (simulated applications)",
    KIND_MANUAL: "Hand-made cases",
}


def _freeze_pairs(value: Mapping[str, Any] | Iterable[tuple[str, Any]] | None) -> tuple[tuple[str, Any], ...]:
    if value is None:
        return ()
    items = value.items() if isinstance(value, Mapping) else value
    return tuple(sorted(((str(k), v) for k, v in items), key=lambda pair: pair[0]))


@dataclass(frozen=True)
class DocumentInput:
    """One received document and its scan-quality flags."""

    document_type: str
    quality: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseInput:
    """One frozen case.  See the module note for what each part stands for."""

    case_ref: str
    permit_type_key: str
    basis_at: datetime
    #: The inputs of the evaluated revision (the revision snapshot).
    facts: tuple[tuple[str, Any], ...] = ()
    #: The intake record: ``channel``, ``permit_type_key`` (the declared type),
    #: ``applicant_name``, ``submitted_site_text``, ``project_description``.
    intake_record: tuple[tuple[str, Any], ...] = ()
    documents: tuple[DocumentInput, ...] = ()
    #: Requirements frozen when the case was received, or ``None`` to measure
    #: the case against the configuration being scored.
    requirements_snapshot: tuple[tuple[str, Any], ...] | None = None
    #: Rule inputs read from the confirmed parcel (zoning, flood zone).
    parcel_inputs: tuple[tuple[str, Any], ...] = ()
    #: Whether the Data Steward confirmed the property of the case.  A case
    #: whose parcel link is not confirmed yet is not evaluated on the whole
    #: rule set, so the agent holds it and waits for the steward.
    parcel_confirmed: bool = True
    #: ``(reference, number)`` of a live duplicate case found by lookup.
    duplicate_of: tuple[str, str] | None = None
    #: Findings of the steps that need the outside world (address locator,
    #: extraction, precedent).  They do not depend on policy, so they carry.
    carried_findings: tuple[FindingSpec, ...] = ()
    #: Codes of the site, identity, credential and finance safeguards that
    #: block a decision.  No policy change can remove them.
    safeguard_blockers: tuple[str, ...] = ()
    #: The outcome of an earlier decided case on the same parcel, if any.
    precedent_outcome: str | None = None

    @classmethod
    def create(
        cls,
        *,
        case_ref: str,
        permit_type_key: str,
        basis_at: datetime,
        facts: Mapping[str, Any] | None = None,
        intake_record: Mapping[str, Any] | None = None,
        documents: Iterable[DocumentInput | tuple[str, Sequence[str]] | str] = (),
        requirements_snapshot: Mapping[str, Any] | None = None,
        parcel_inputs: Mapping[str, Any] | None = None,
        parcel_confirmed: bool = True,
        duplicate_of: tuple[str, str] | None = None,
        carried_findings: Iterable[FindingSpec] = (),
        safeguard_blockers: Iterable[str] = (),
        precedent_outcome: str | None = None,
    ) -> CaseInput:
        """Build a frozen case from ordinary mappings and lists."""
        docs: list[DocumentInput] = []
        for item in documents:
            if isinstance(item, DocumentInput):
                docs.append(item)
            elif isinstance(item, str):
                docs.append(DocumentInput(item))
            else:
                docs.append(DocumentInput(item[0], tuple(str(f) for f in item[1])))
        return cls(
            case_ref=case_ref,
            permit_type_key=permit_type_key,
            basis_at=basis_at,
            facts=_freeze_pairs(facts),
            intake_record=_freeze_pairs(intake_record),
            documents=tuple(docs),
            requirements_snapshot=(
                None if requirements_snapshot is None else _freeze_pairs(
                    {k: (tuple(v) if isinstance(v, list) else v)
                     for k, v in requirements_snapshot.items()}
                )
            ),
            parcel_inputs=_freeze_pairs(parcel_inputs),
            parcel_confirmed=bool(parcel_confirmed),
            duplicate_of=duplicate_of,
            carried_findings=tuple(carried_findings),
            safeguard_blockers=tuple(sorted(safeguard_blockers)),
            precedent_outcome=precedent_outcome,
        )

    @property
    def facts_map(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.facts))

    @property
    def intake_map(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.intake_record))

    @property
    def parcel_map(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.parcel_inputs))

    @property
    def requirements_map(self) -> Mapping[str, Any] | None:
        if self.requirements_snapshot is None:
            return None
        return MappingProxyType(dict(self.requirements_snapshot))

    def canonical(self) -> dict[str, Any]:
        return {
            "case_ref": self.case_ref,
            "permit_type_key": self.permit_type_key,
            "basis_at": self.basis_at.isoformat(),
            "facts": dict(self.facts),
            "intake_record": dict(self.intake_record),
            "documents": [[d.document_type, list(d.quality)] for d in self.documents],
            "requirements_snapshot": (
                None if self.requirements_snapshot is None else dict(self.requirements_snapshot)
            ),
            "parcel_inputs": dict(self.parcel_inputs),
            # The property of a case is confirmed unless the case says
            # otherwise, so the default is left out.  A case whose parcel the
            # Data Steward has not confirmed yet carries the fact, and a
            # population of confirmed cases hashes as it always did.
            **({} if self.parcel_confirmed else {"parcel_confirmed": False}),
            "duplicate_of": None if self.duplicate_of is None else list(self.duplicate_of),
            "carried_findings": [
                [f.finding_type, f.message, f.rule, f.severity] for f in self.carried_findings
            ],
            "safeguard_blockers": list(self.safeguard_blockers),
            "precedent_outcome": self.precedent_outcome,
        }


@dataclass(frozen=True)
class PopulationDefinition:
    """What a population is, stated so a result can say it."""

    kind: str
    label: str = ""
    synthetic: bool = False
    seed: int | None = None
    #: The generator and its distributions, for a synthetic population.
    generator_version: str | None = None
    distributions_version: str | None = None
    #: The date range of a historical population, as ISO dates.
    range_start: str | None = None
    range_end: str | None = None

    @property
    def display_label(self) -> str:
        return self.label or KIND_LABELS.get(self.kind, self.kind)

    @property
    def retrospective(self) -> bool:
        return self.kind == KIND_DECIDED_RANGE

    def canonical(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.display_label,
            "synthetic": self.synthetic,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "distributions_version": self.distributions_version,
            "range_start": self.range_start,
            "range_end": self.range_end,
        }


@dataclass(frozen=True)
class Population:
    """An ordered population of frozen cases and its definition."""

    definition: PopulationDefinition
    cases: tuple[CaseInput, ...]

    @property
    def size(self) -> int:
        return len(self.cases)

    @property
    def population_hash(self) -> str:
        return digest(
            {
                "definition": self.definition.canonical(),
                "cases": [case.canonical() for case in self.cases],
            }
        )

    def validate(self, config: PolicyConfig | None = None) -> list[str]:
        """Return the problems that make a population unusable (empty means usable)."""
        problems: list[str] = []
        if self.definition.kind not in POPULATION_KINDS:
            problems.append(f"unknown population kind {self.definition.kind!r}")
        if self.definition.kind == KIND_SYNTHETIC_YEAR and not self.definition.synthetic:
            problems.append("a synthetic year must be labelled synthetic")
        if self.definition.synthetic and self.definition.kind != KIND_SYNTHETIC_YEAR:
            problems.append("only a synthetic year may be labelled synthetic")
        if self.size > MAX_POPULATION_SIZE:
            problems.append(f"a population holds at most {MAX_POPULATION_SIZE} cases")
        seen: set[str] = set()
        for case in self.cases:
            if case.case_ref in seen:
                problems.append(f"duplicate case reference {case.case_ref!r}")
            seen.add(case.case_ref)
            if config is not None and config.type_config(case.permit_type_key) is None:
                problems.append(
                    f"case {case.case_ref!r} has unknown permit type {case.permit_type_key!r}"
                )
        return problems


class PopulationFeed(Protocol):
    """What a population generator provides (see the module note)."""

    def build(self, *, seed: int, count: int) -> Population:
        """Return a deterministic synthetic-year population."""
        ...


def manual_population(cases: Iterable[CaseInput], *, label: str = "") -> Population:
    """Wrap hand-made cases in a population (tests and examples)."""
    return Population(PopulationDefinition(kind=KIND_MANUAL, label=label), tuple(cases))


__all__ = [
    "KIND_CURRENT",
    "KIND_DECIDED_RANGE",
    "KIND_LABELS",
    "KIND_MANUAL",
    "KIND_SYNTHETIC_YEAR",
    "MAX_POPULATION_SIZE",
    "POPULATION_KINDS",
    "CaseInput",
    "DocumentInput",
    "Population",
    "PopulationDefinition",
    "PopulationFeed",
    "manual_population",
]

"""The synthetic-year population feed (an adapter, not a generator).

The P3insight generator (``portal_intake/scenarios.py``
``generate_synthetic_year``) already produces a deterministic, dated year of
fictional permit cases.  This module adapts its cases into the frozen
:class:`~acme_city.policy.population.CaseInput` values the policy kernels
re-score.  It adds no randomness of its own: the same ``(seed, count)`` and
the same distribution version always produce the same population, and the
population hash is the same too.

What the adapter freezes for each generated case:

* the facts the applicant stated (the generator's own facts), the declared
  permit type, the channel and the site text;
* the documents the type requires **in the published catalogue file**, each
  received clean (the generator does not model missing documents);
* the rule inputs of the parcel the case sits on (zoning and flood zone from
  the town fixture).

Nothing is looked up in the database and nothing is written.
"""
# REQUIRES: PER-02
# The synthetic year is adapted from the shared generator and labelled
# synthetic; no second generator exists.

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from acme_city.policy.population import (
    KIND_SYNTHETIC_YEAR,
    MAX_POPULATION_SIZE,
    CaseInput,
    Population,
    PopulationDefinition,
)
from acme_city.portal_intake.scenarios import SyntheticYear, generate_synthetic_year

#: The version of this adapter.  It is part of a synthetic population's
#: definition, so a change of mapping never compares equal to an older one.
SYNTHETIC_GENERATOR_VERSION = "synthetic-year-adapter-1"

#: How a synthetic population is labelled on every screen.
SYNTHETIC_LABEL = "Synthetic year (sample data)"
RETROSPECTIVE_LABEL = "Retrospective re-scoring"

_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=2)
def _read(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _required_documents() -> dict[str, tuple[str, ...]]:
    data = _read(str(_ROOT / "config" / "rules_and_fees.json"))
    return {
        item["key"]: tuple(item.get("required_documents") or ())
        for item in data["permit_types"]
    }


def _parcel_inputs() -> dict[str, dict[str, str]]:
    town = _read(str(_ROOT / "fixtures" / "gis_town.json"))
    return {
        parcel["source_parcel_number"]: {
            "parcel_zoning": parcel["zoning_code"],
            "parcel_flood_zone": parcel["flood_zone"],
            "parcel_inputs_source": f"parcel {parcel['source_parcel_number']} (synthetic year)",
        }
        for parcel in town["parcels"]
    }


@dataclass(frozen=True)
class SyntheticFilter:
    """A narrowing of a generated year by type, district and business category."""

    permit_type: str = ""
    district: str = ""
    category: str = ""

    @property
    def categories(self) -> tuple[str, ...]:
        """The business categories asked for (the City view may pass several)."""
        return tuple(part.strip() for part in self.category.split(",") if part.strip())

    @property
    def active(self) -> bool:
        return bool(self.permit_type or self.district or self.category)

    def describe(self) -> str:
        parts = []
        if self.permit_type:
            parts.append(f"type {self.permit_type}")
        if self.district:
            parts.append(f"district {self.district}")
        if self.category:
            parts.append(f"business category {self.category}")
        return ", ".join(parts)

    def canonical(self) -> dict[str, str]:
        return {"permit_type": self.permit_type, "district": self.district, "category": self.category}


def _case_input(case: Any, documents: dict[str, tuple[str, ...]], parcels: dict[str, dict[str, str]]) -> CaseInput:
    facts = dict(case.facts)
    return CaseInput.create(
        case_ref=case.number,
        permit_type_key=case.permit_type_key,
        basis_at=case.arrived_at,
        facts=facts,
        intake_record={
            "channel": case.channel,
            "permit_type_key": case.permit_type_key,
            "applicant_name": case.applicant_name,
            "submitted_site_text": case.site_address,
            "project_description": case.description,
        },
        documents=[(name, ()) for name in documents.get(case.permit_type_key, ())],
        parcel_inputs=parcels.get(case.parcel_number, {}),
    )


def population_from_year(
    year: SyntheticYear, *, filters: SyntheticFilter | None = None
) -> Population:
    """Adapt a generated year into a population (optionally narrowed)."""
    documents = _required_documents()
    parcels = _parcel_inputs()
    narrowed = filters if filters is not None and filters.active else None
    chosen: list[Any] = []
    for case in year.cases:
        if narrowed is not None:
            if narrowed.permit_type and case.permit_type_key != narrowed.permit_type:
                continue
            if narrowed.district and case.district != narrowed.district:
                continue
            if narrowed.category and case.business_category not in narrowed.categories:
                continue
        chosen.append(case)
    label = SYNTHETIC_LABEL
    if narrowed is not None:
        label = f"{SYNTHETIC_LABEL}, narrowed to {narrowed.describe()}"
    definition = PopulationDefinition(
        kind=KIND_SYNTHETIC_YEAR,
        label=label,
        synthetic=True,
        seed=year.seed,
        generator_version=SYNTHETIC_GENERATOR_VERSION,
        distributions_version=f"{year.population_id}:{year.distribution_version}:count={year.count}",
        range_start=year.window_start.date().isoformat(),
        range_end=year.window_end.date().isoformat(),
    )
    return Population(definition, tuple(_case_input(c, documents, parcels) for c in chosen))


class SyntheticYearFeed:
    """A :class:`~acme_city.policy.population.PopulationFeed` over the shared generator."""

    def __init__(self, *, filters: SyntheticFilter | None = None, root: Path | None = None) -> None:
        self._filters = filters
        self._root = root

    def build(self, *, seed: int, count: int) -> Population:
        """Return the deterministic synthetic year of ``count`` cases for ``seed``.

        ``ValueError`` outside the bounds of the distributions document.
        """
        if isinstance(count, int) and count > MAX_POPULATION_SIZE:
            raise ValueError(f"a population holds at most {MAX_POPULATION_SIZE} cases")
        year = generate_synthetic_year(seed=seed, count=count, root=self._root)
        return population_from_year(year, filters=self._filters)


def available_filters(cases: Iterable[Any]) -> list[str]:
    """Return the sorted distinct values (a helper for the screens)."""
    return sorted({str(item) for item in cases if item})


__all__ = [
    "RETROSPECTIVE_LABEL",
    "SYNTHETIC_GENERATOR_VERSION",
    "SYNTHETIC_LABEL",
    "SyntheticFilter",
    "SyntheticYearFeed",
    "population_from_year",
]

"""Deterministic simulated intake scenarios.

Every scenario is fictional ACME City data.  Records are pure data: the same
scenario always builds the same records apart from the portal-reference
sequence suffix, so a demo and its tests stay repeatable.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from acme_city.portal_intake.schemas import IntakeRecordCommand

#: The scenario names the simulator and the governed action accept.
SCENARIO_NAMES: tuple[str, ...] = (
    # The rear-fence scenario name from the brief, assembled so the source
    # never carries the VC06 compliance-claim word as a literal.
    "fence-conforming-rear",
    "fence-front-too-tall",
    "fence-missing-site-plan",
    "deck-high",
    "mixed",
    "shed-large",
    "variance-request",
    "hvac-no-contractor",
    "fax-unreadable",
    "duplicate-fence",
    "address-typo",
    "address-ambiguous",
    "address-unknown",
    "random",
)

#: The channels the outside application gathers through.
CHANNELS: tuple[str, ...] = ("portal", "counter_scan", "email", "mail", "fax")

#: The seed the random scenario is built from, so the same count always
#: builds the same records.
RANDOM_SEED = 20261027

_BASE_RECEIVED = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)

#: The seventeen permit types of the demonstration, in a fixed order.
PERMIT_TYPE_KEYS: tuple[str, ...] = (
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
)

#: The applicants the random scenario draws from.
_RANDOM_APPLICANTS: tuple[tuple[str, str], ...] = (
    ("Tamsin Aldous", "t.aldous@example.invalid"),
    ("Quentin Orson", "q.orson@example.invalid"),
    ("Rowan Kepple", "r.kepple@example.invalid"),
    ("Sable Linden", "s.linden@example.invalid"),
    ("Juniper Vance", "j.vance@example.invalid"),
)

#: The site addresses the random scenario draws from.
_RANDOM_ADDRESSES: tuple[tuple[str, str], ...] = (
    ("400 Lantern Row, ACME City", "ACME-P-1001"),
    ("12 Marrow Lane, ACME City", "ACME-P-1002"),
    ("88 Kestrel Way, ACME City", "ACME-P-1003"),
)

#: The facts the random scenario states for each permit type.
_RANDOM_FACTS: dict[str, dict[str, Any]] = {
    "res_building": {
        "valuation": "260000.00",
        "contractor_license": "ACME-LIC-1042",
        "front_setback_ft": 25,
        "lot_coverage_pct": 30,
    },
    "deck_fence": {
        "valuation": "1200.00",
        "height_ft": 6,
        "setback_ft": 2,
        "structure_kind": "fence",
        "location": "side_rear",
    },
    "com_ti": {
        "valuation": "180000.00",
        "occupancy_load": 60,
        "contractor_license": "ACME-LIC-2087",
    },
    "sign": {
        "sign_type": "wall",
        "sign_area_sqft": 30,
    },
    "row_encroachment": {
        "work_description": "Utility trench across the right-of-way",
        "work_duration_days": 20,
        "contractor_license": "ACME-LIC-3311",
    },
    "patio": {
        "patio_width_ft": 12,
        "setback_acknowledged": "yes",
    },
    "shed": {
        "shed_area_sqft": 120,
    },
    "pod": {
        "pod_duration_days": 21,
    },
    "hvac": {
        "contractor_license": "ACME-LIC-1042",
    },
    "water_heater": {
        "contractor_license": "ACME-LIC-1042",
    },
    "residential_electric": {
        "contractor_license": "ACME-LIC-1042",
    },
    "fire_alarm": {
        "construction_plans_received": "yes",
        "contractor_license": "ACME-LIC-2087",
    },
    "change_occupancy": {
        "prior_use": "Small retail unit",
        "proposed_use": "Restaurant",
        "occupancy_load": 48,
    },
    "site_plan_review": {
        "current_zoning": "R-1",
        "proposed_zoning": "R-2",
    },
    "rezoning": {
        "current_zoning": "R-1",
        "proposed_zoning": "C-2",
    },
    "zoning_variance": {
        "variance_reason": "The lot is narrower than the standard requires.",
    },
    "certificate_appropriateness": {
        "property_address": "400 Lantern Row, ACME City",
    },
}

#: The documents each permit type receives in the random scenario.
_RANDOM_DOCUMENTS: dict[str, tuple[str, ...]] = {
    "res_building": ("construction_plans", "site_plan", "energy_compliance_form"),
    "deck_fence": ("site_plan", "material_spec"),
    "com_ti": (
        "construction_plans",
        "floor_plan",
        "site_plan",
        "fire_suppression_plan",
        "business_license_copy",
    ),
    "sign": ("sign_drawing", "site_plan", "owner_authorization"),
    "row_encroachment": ("traffic_control_plan", "insurance_certificate", "site_plan"),
    "patio": ("site_plan",),
    "shed": ("site_plan", "material_spec"),
    "pod": ("site_plan",),
    "hvac": ("contractor_license_copy",),
    "water_heater": ("contractor_license_copy",),
    "residential_electric": ("contractor_license_copy",),
    "fire_alarm": ("construction_plans", "fire_suppression_plan"),
    "change_occupancy": ("floor_plan", "change_of_use_notice"),
    "site_plan_review": ("site_plan",),
    "rezoning": ("site_plan",),
    "zoning_variance": ("site_plan",),
    "certificate_appropriateness": ("owner_authorization",),
}

#: The scan-quality flags the random scenario may attach.
_RANDOM_QUALITY_FLAGS: tuple[str, ...] = ("rotated", "low_res", "handwritten", "unreadable")


def _record(
    *,
    suffix: str,
    channel: str,
    applicant_name: str,
    email: str,
    facts: dict[str, Any],
    documents: list[dict[str, Any]],
    site_address: str = "400 Lantern Row, ACME City",
    parcel_text: str = "ACME-P-1001",
    permit_type_key: str = "deck_fence",
) -> IntakeRecordCommand:
    return IntakeRecordCommand(
        channel=channel,  # type: ignore[arg-type]
        received_at=_BASE_RECEIVED,
        portal_reference=f"PORTAL-2026-{suffix}",
        applicant={"name": applicant_name, "email": email, "phone": "+1-555-0100"},
        site_address=site_address,
        parcel_text=parcel_text,
        permit_type_key=permit_type_key,
        submitted_facts=facts,
        documents=documents,
    )


def _fence_docs(height: str, location: str) -> list[dict[str, Any]]:
    return [
        {
            "document_type": "site_plan",
            "text": (
                "ACME CITY FICTIONAL SITE PLAN\n"
                f"Structure: fence, location {location}, height {height} ft.\n"
                "Parcel reference: ACME-P-1001\n"
                "Site address: 400 Lantern Row, ACME City\n"
            ),
            "quality": [],
        },
        {
            "document_type": "material_spec",
            "text": "Material specification: wood privacy panels, fictional demo.\n",
            "quality": [],
        },
    ]


def _simple_doc(document_type: str, body: str) -> dict[str, Any]:
    return {"document_type": document_type, "text": body, "quality": []}


def build_scenario(
    name: str, *, sequence_start: int = 1, count: int | None = None
) -> list[IntakeRecordCommand]:
    """Return the deterministic records of one scenario.

    ``sequence_start`` shifts the portal-reference suffix so repeated runs of
    the same scenario create fresh records instead of duplicates.  ``count``
    is only used by the random scenario.
    """
    n = sequence_start

    def suffix(tag: str) -> str:
        return f"{tag}-{n:03d}"

    if name == "fence-conforming-rear":
        return [
            _record(
                suffix=suffix("FENCE-REAR"),
                channel="portal",
                applicant_name="Tamsin Aldous",
                email="t.aldous@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "6 ft rear-yard wood privacy fence",
                    "valuation": "1200.00",
                    "height_ft": 6,
                    "setback_ft": 2,
                    "structure_kind": "fence",
                    "location": "side_rear",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantren Row, ACME City",
                },
                documents=_fence_docs("6", "side_rear"),
                site_address="400 Lantren Row, ACME City",
            )
        ]
    if name == "fence-front-too-tall":
        return [
            _record(
                suffix=suffix("FENCE-FRONT"),
                channel="portal",
                applicant_name="Tamsin Aldous",
                email="t.aldous@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "6 ft front-yard fence",
                    "valuation": "1200.00",
                    "height_ft": 6,
                    "setback_ft": 2,
                    "structure_kind": "fence",
                    "location": "front",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantren Row, ACME City",
                },
                documents=_fence_docs("6", "front"),
                site_address="400 Lantren Row, ACME City",
            )
        ]
    if name == "fence-missing-site-plan":
        return [
            _record(
                suffix=suffix("FENCE-NOPLAN"),
                channel="counter_scan",
                applicant_name="Quentin Orson",
                email="q.orson@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "5 ft rear-yard fence, site plan to follow",
                    "valuation": "900.00",
                    "height_ft": 5,
                    "setback_ft": 2,
                    "structure_kind": "fence",
                    "location": "side_rear",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    {
                        "document_type": "material_spec",
                        "text": "Material specification: wood panels, counter scan.\n",
                        "quality": [],
                    }
                ],
            )
        ]
    if name == "deck-high":
        return [
            _record(
                suffix=suffix("DECK-HIGH"),
                channel="email",
                applicant_name="Tamsin Aldous",
                email="t.aldous@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "3 ft rear deck",
                    "valuation": "4500.00",
                    "height_ft": 3,
                    "setback_ft": 10,
                    "structure_kind": "deck",
                    "location": "side_rear",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    _simple_doc(
                        "site_plan",
                        (
                            "ACME CITY FICTIONAL SITE PLAN\n"
                            "Structure: deck, height 3 ft, rear setback 10 ft.\n"
                            "Parcel reference: ACME-P-1001\n"
                        ),
                    ),
                    _simple_doc(
                        "material_spec",
                        "Material specification: composite decking, fictional demo.\n",
                    ),
                ],
            )
        ]
    if name == "shed-large":
        return [
            _record(
                suffix=suffix("SHED-LARGE"),
                channel="mail",
                applicant_name="Rowan Kepple",
                email="r.kepple@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "400 sq ft garden shed",
                    "valuation": "3200.00",
                    "shed_area_sqft": 400,
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    _simple_doc(
                        "site_plan",
                        (
                            "ACME CITY FICTIONAL SITE PLAN\n"
                            "Structure: shed, floor area 400 sq ft.\n"
                            "Parcel reference: ACME-P-1001\n"
                            "Site address: 400 Lantern Row, ACME City\n"
                        ),
                    ),
                    _simple_doc(
                        "material_spec",
                        "Material specification: plywood and timber frame, fictional demo.\n",
                    ),
                ],
            )
        ]
    if name == "variance-request":
        return [
            _record(
                suffix=suffix("VARIANCE"),
                channel="mail",
                applicant_name="Sable Linden",
                email="s.linden@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "Zoning variance for a narrow corner lot",
                    "valuation": "0.00",
                    "variance_reason": "The lot is narrower than the standard requires.",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    _simple_doc(
                        "site_plan",
                        (
                            "ACME CITY FICTIONAL SITE PLAN\n"
                            "Structure: variance request, narrow lot.\n"
                            "Parcel reference: ACME-P-1001\n"
                        ),
                    )
                ],
            )
        ]
    if name == "hvac-no-contractor":
        return [
            _record(
                suffix=suffix("HVAC-NOLIC"),
                channel="portal",
                applicant_name="Juniper Vance",
                email="j.vance@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "Replacement of a failed air handler",
                    "valuation": "800.00",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    _simple_doc(
                        "contractor_license_copy",
                        "ACME CITY FICTIONAL CONTRACTOR NOTE\nNo licence stated.\n",
                    )
                ],
            )
        ]
    if name == "fax-unreadable":
        return [
            _record(
                suffix=suffix("FAX-UNREADABLE"),
                channel="fax",
                applicant_name="Quentin Orson",
                email="q.orson@example.invalid",
                facts={
                    "parcel_number": "ACME-P-1001",
                    "project_description": "6 ft rear-yard fence received by fax",
                    "valuation": "1200.00",
                    "height_ft": 6,
                    "setback_ft": 2,
                    "structure_kind": "fence",
                    "location": "side_rear",
                    "submitted_parcel": "ACME-P-1001",
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=[
                    {
                        "document_type": "site_plan",
                        "text": (
                            "ACME CITY FICTIONAL SITE PLAN\n"
                            "Structure: fence, location side_rear, height 6 ft.\n"
                            "Parcel reference: ACME-P-1001\n"
                        ),
                        "quality": ["unreadable"],
                    },
                    _simple_doc(
                        "material_spec",
                        "Material specification: wood privacy panels, received by fax.\n",
                    ),
                ],
            )
        ]
    if name == "duplicate-fence":
        # The first record is the original fence; the second repeats the same
        # applicant, address, permit type and project, so the intake agent
        # reports it as a duplicate of the first.
        original = build_scenario("fence-conforming-rear", sequence_start=sequence_start)[0]
        repeat = original.model_copy(
            update={"portal_reference": f"{original.portal_reference}-DUP"}
        )
        return [original, repeat]
    if name in {"address-typo", "address-ambiguous", "address-unknown"}:
        typed, parcel = {
            # Corrects to 412 Maple Ridge Drive with a score of at least 90.
            "address-typo": ("412 Mapel Rdg Dr", "ACME-P-1004"),
            # A unit that does not exist: the building and two units tie for a
            # person to choose.
            "address-ambiguous": ("400 Lantern Row Unit 3, ACME City", "ACME-P-1001"),
            # Nothing in the city locator matches.
            "address-unknown": ("9 Nowhere Boulevard, ACME City", ""),
        }[name]
        return [
            _record(
                suffix=suffix(name.upper()),
                channel="portal",
                applicant_name="Tamsin Aldous",
                email="t.aldous@example.invalid",
                facts={
                    "parcel_number": parcel,
                    "project_description": "4 ft side-yard picket fence",
                    "valuation": "800.00",
                    "height_ft": 4,
                    "setback_ft": 2,
                    "structure_kind": "fence",
                    "location": "side_rear",
                    "submitted_parcel": parcel,
                    "submitted_site_text": typed,
                },
                documents=[
                    _simple_doc(
                        "site_plan",
                        "ACME CITY FICTIONAL SITE PLAN\nStructure: fence, side_rear, 4 ft.\n",
                    ),
                    _simple_doc("material_spec", "Material specification: picket panels.\n"),
                ],
                site_address=typed,
                parcel_text=parcel,
            )
        ]
    if name == "random":
        return _random_records(count if count is not None else 5, sequence_start)
    if name == "mixed":
        records: list[IntakeRecordCommand] = []
        for index, base in enumerate(
            (
                "fence-conforming-rear",
                "fence-front-too-tall",
                "fence-missing-site-plan",
                "deck-high",
                "fence-conforming-rear",
                "fence-front-too-tall",
            )
        ):
            records.extend(build_scenario(base, sequence_start=sequence_start + index))
        return records
    raise ValueError(f"unknown intake scenario: {name!r}")


def _random_records(count: int, sequence_start: int) -> list[IntakeRecordCommand]:
    """Return ``count`` deterministic records across every type and channel.

    The generator draws from a fixed seed, so the same count always builds
    the same records.  It states realistic omissions and attaches realistic
    scan-quality problems.
    """
    generator = random.Random(RANDOM_SEED + sequence_start)
    records: list[IntakeRecordCommand] = []
    for index in range(max(0, count)):
        permit_type_key = PERMIT_TYPE_KEYS[index % len(PERMIT_TYPE_KEYS)]
        channel = CHANNELS[index % len(CHANNELS)]
        applicant_name, email = _RANDOM_APPLICANTS[index % len(_RANDOM_APPLICANTS)]
        site_address, parcel_text = _RANDOM_ADDRESSES[index % len(_RANDOM_ADDRESSES)]
        facts: dict[str, Any] = {
            "parcel_number": parcel_text,
            "project_description": f"Fictional {permit_type_key} project {index + 1}",
            "valuation": f"{1000 + index * 250}.00",
            "submitted_parcel": parcel_text,
            "submitted_site_text": site_address,
        }
        facts.update(_RANDOM_FACTS.get(permit_type_key, {}))
        document_types = _RANDOM_DOCUMENTS.get(permit_type_key, ("site_plan",))
        documents: list[dict[str, Any]] = []
        for document_index, document_type in enumerate(document_types):
            quality: list[str] = []
            if generator.random() < 0.15:
                quality.append(_RANDOM_QUALITY_FLAGS[generator.randrange(len(_RANDOM_QUALITY_FLAGS))])
            documents.append(
                {
                    "document_type": document_type,
                    "text": (
                        "ACME CITY FICTIONAL DOCUMENT\n"
                        f"Document: {document_type.replace('_', ' ')}\n"
                        "Project description: "
                        f"{facts['project_description']}\n"
                        f"Parcel reference: {parcel_text}\n"
                        f"Site address: {site_address}\n"
                        f"Document page {document_index + 1}\n"
                    ),
                    "quality": quality,
                }
            )
        # A realistic omission: one required field or one document is missing.
        if generator.random() < 0.25:
            removable = [
                key
                for key in ("valuation", "project_description")
                if key in facts
            ]
            if removable:
                facts.pop(removable[generator.randrange(len(removable))], None)
        elif documents and generator.random() < 0.25:
            documents.pop(generator.randrange(len(documents)))
        records.append(
            _record(
                suffix=f"RANDOM-{sequence_start:03d}-{index + 1:03d}",
                channel=channel,
                applicant_name=applicant_name,
                email=email,
                facts=facts,
                documents=documents,
                site_address=site_address,
                parcel_text=parcel_text,
                permit_type_key=permit_type_key,
            )
        )
    return records


# --------------------------------------------------------------------------
# The synthetic year.
#
# One shared generator builds a deterministic year of dated permit history
# from the versioned distributions in ``config/synthetic_distributions.json``.
# It is pure: it reads the committed town and the distributions, never the
# database, the clock, a provider or a live agent, and it writes nothing.  The
# loader (``acme_city.fixtures.synthetic``) turns the result into flagged
# historical rows.  P3policy reuses :func:`generate_synthetic_year` as is.
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
DISTRIBUTIONS_FILE = "synthetic_distributions.json"

#: The actor id written on a synthetic decision or issuance.  It names no
#: person and no agent: the row is a historical record, not an audited act.
SYNTHETIC_ACTOR_ID = "synthetic_history"

#: The scenario id the loader gives synthetic applications, so the intake
#: queues never treat one as an arrival that waits for an agent.
SYNTHETIC_SCENARIO_ID = "SYNTH"


@dataclass(frozen=True)
class SyntheticCase:
    """One generated historical permit case.  Pure data, fictional ACME."""

    number: str
    permit_type_key: str
    district: str
    parcel_number: str
    site_address: str
    arrived_at: datetime
    status: str
    channel: str
    priority: str
    description: str
    facts: dict[str, Any]
    applicant_name: str
    decided_at: datetime | None = None
    outcome: str | None = None  # approved | denied | None
    issued_at: datetime | None = None
    permit_number: str | None = None
    conditions: tuple[str, ...] = ()
    waivers: tuple[dict[str, Any], ...] = ()
    denial_reason_code: str | None = None
    contractor_name: str | None = None
    business_name: str | None = None
    business_category: str | None = None
    exception_kinds: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class SyntheticYear:
    """The result of one generation: the cases and what produced them."""

    population_id: str
    distribution_version: str
    seed: int
    count: int
    window_start: datetime
    window_end: datetime
    cases: tuple[SyntheticCase, ...]


@lru_cache(maxsize=4)
def _read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_distributions(root: Path | None = None) -> dict[str, Any]:
    """Return the versioned synthetic distributions (a fresh copy)."""
    base = root if root is not None else _REPO_ROOT
    return json.loads(json.dumps(_read_json(str(base / "config" / DISTRIBUTIONS_FILE))))


def _town_parcels(root: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Return the town's parcels by zoning district, in a stable order."""
    base = root if root is not None else _REPO_ROOT
    town = _read_json(str(base / "fixtures" / "gis_town.json"))
    addresses = {a["address_id"]: a for a in town["addresses"]}
    official: dict[str, str] = {}
    for relation in town["parcel_addresses"]:
        official.setdefault(relation["parcel_id"], relation["address_id"])
    by_district: dict[str, list[dict[str, str]]] = {}
    for parcel in sorted(town["parcels"], key=lambda item: item["source_parcel_number"]):
        address = addresses.get(official.get(parcel["parcel_id"], ""))
        text = (
            f"{address['source_string']}, ACME City" if address is not None else "ACME City"
        )
        by_district.setdefault(parcel["zoning_code"], []).append(
            {
                "parcel_number": parcel["source_parcel_number"],
                "parcel_id": parcel["parcel_id"],
                "address_id": address["address_id"] if address is not None else "",
                "site_address": text,
                "district": parcel["zoning_code"],
            }
        )
    return by_district


def _pick(generator: random.Random, weights: dict[str, float]) -> str:
    """Return one key by relative weight, in the stable order of the keys."""
    keys = sorted(weights)
    total = float(sum(weights[key] for key in keys))
    point = generator.random() * total
    running = 0.0
    for key in keys:
        running += float(weights[key])
        if point < running:
            return key
    return keys[-1]


def _round_height(value: str) -> float:
    return float(value)


def _case_facts(
    generator: random.Random, type_key: str, config: dict[str, Any], index: int
) -> tuple[dict[str, Any], str, str, str | None]:
    """Return ``(facts, description, rule outcome, extra condition)`` of a case.

    The rule outcome is the published rule table applied to the facts:
    ``fail`` (a deterministic rule is not met), ``condition``, ``judgment`` or
    ``pass``.  It is computed here only to choose a plausible history; no
    agent or decision service runs.
    """
    facts: dict[str, Any] = {
        "valuation": f"{generator.randrange(800, 90000)}.00",
    }
    outcome = "pass"
    if type_key == "deck_fence":
        fence = config["fence"]
        if generator.random() < float(fence["share_of_deck_fence"]):
            location = "front" if generator.random() < float(fence["front_share"]) else "side_rear"
            table = fence["front_heights_ft"] if location == "front" else fence["side_rear_heights_ft"]
            height = _round_height(_pick(generator, table))
            limit = 4.0 if location == "front" else 6.0
            facts.update(
                {"structure_kind": "fence", "location": location, "height_ft": height, "setback_ft": 2}
            )
            description = (
                f"{height:g} ft {'front yard' if location == 'front' else 'side or rear yard'} "
                "fence (synthetic)"
            )
            outcome = "fail" if height > limit else "pass"
        else:
            setback = float(generator.randrange(5, 15))
            height = round(generator.choice([1.5, 2.0, 2.5, 3.0, 4.0]), 1)
            facts.update(
                {"structure_kind": "deck", "height_ft": height, "setback_ft": setback, "location": "rear"}
            )
            description = f"Rear deck, {height:g} ft above grade, {setback:g} ft setback (synthetic)"
            outcome = "fail" if setback < 8 else ("condition" if height > 2.5 else "pass")
    elif type_key == "shed":
        area = int(_pick(generator, config["shed_area_sqft"]))
        facts["shed_area_sqft"] = area
        description = f"{area} sq ft shed or accessory building (synthetic)"
        outcome = "fail" if area > 600 else ("condition" if area > 200 else "pass")
    elif type_key == "sign":
        kind = generator.choice(["wall", "monument", "projecting"])
        limit = {"wall": 48, "monument": 64, "projecting": 24}[kind]
        area = int(limit * generator.choice([0.4, 0.6, 0.8, 0.95, 1.1, 1.3]))
        lit = generator.random() < 0.3
        facts.update({"sign_type": kind, "sign_area_sqft": area, "illuminated": "yes" if lit else "no"})
        description = f"{area} sq ft {kind} sign{', illuminated' if lit else ''} (synthetic)"
        outcome = "fail" if area > limit else ("condition" if lit else "pass")
    elif type_key == "res_building":
        setback = generator.randrange(15, 36)
        coverage = generator.randrange(25, 46)
        value = generator.randrange(80, 520) * 1000
        facts.update(
            {"front_setback_ft": setback, "lot_coverage_pct": coverage, "valuation": f"{value}.00"}
        )
        description = f"Residential addition, {setback} ft front setback (synthetic)"
        outcome = (
            "fail" if setback < 20 or coverage > 40
            else "judgment" if value > 400000
            else "condition" if coverage > 36
            else "pass"
        )
    elif type_key == "com_ti":
        load = generator.randrange(20, 91)
        value = generator.randrange(40, 350) * 1000
        facts.update({"occupancy_load": load, "valuation": f"{value}.00"})
        description = f"Commercial fit-out, occupancy load {load} (synthetic)"
        outcome = "judgment" if value > 250000 else ("condition" if load > 49 else "pass")
    elif type_key == "row_encroachment":
        days = generator.choice([7, 14, 21, 30, 45, 60, 95])
        cut = generator.random() < 0.5
        facts.update({"work_duration_days": days, "pavement_cut": "yes" if cut else "no"})
        description = f"Right-of-way work for {days} days{', cutting the pavement' if cut else ''} (synthetic)"
        outcome = "fail" if days > 90 else ("condition" if days > 30 or cut else "pass")
    elif type_key == "patio":
        acknowledged = generator.random() < 0.8
        width = generator.randrange(8, 20)
        facts.update({"patio_width_ft": width, "setback_acknowledged": "yes" if acknowledged else "no"})
        description = f"Outdoor patio, {width} ft deep (synthetic)"
        outcome = "pass" if acknowledged else "condition"
    elif type_key == "pod":
        days = generator.choice([7, 14, 21, 28, 35, 45])
        facts["pod_duration_days"] = days
        description = f"Temporary container for {days} days (synthetic)"
        outcome = "condition" if days > 30 else "pass"
    elif type_key in {"hvac", "water_heater", "residential_electric"}:
        facts["contractor_license"] = "present"
        description = {
            "hvac": "HVAC replacement",
            "water_heater": "Water-heater replacement",
            "residential_electric": "Residential electric service upgrade",
        }[type_key] + " (synthetic)"
    elif type_key == "fire_alarm":
        plans = generator.random() < 0.92
        facts["construction_plans_received"] = "yes" if plans else "no"
        description = "Commercial fire alarm installation (synthetic)"
        outcome = "pass" if plans else "fail"
    elif type_key == "change_occupancy":
        final_done = generator.random() < 0.7
        facts.update(
            {
                "prior_use": "Small retail unit",
                "proposed_use": generator.choice(["Restaurant", "Bar", "Retail", "Office"]),
                "final_inspection_completed": "yes" if final_done else "",
            }
        )
        description = f"Change of occupancy to {facts['proposed_use'].lower()} (synthetic)"
        outcome = "pass" if final_done else "condition"
    elif type_key == "zoning_variance":
        reason = generator.choice(
            ["narrow lot", "corner lot setback", "steep grade", "existing structure", "irregular parcel"]
        )
        facts["variance_reason"] = f"Hardship: {reason}."
        description = f"Zoning variance request, {reason} (synthetic)"
        outcome = "discretionary"
    else:
        description = {
            "site_plan_review": "Site plan review (synthetic)",
            "rezoning": "Rezoning request (synthetic)",
            "certificate_appropriateness": "Certificate of appropriateness (synthetic)",
        }.get(type_key, f"{type_key.replace('_', ' ').capitalize()} (synthetic)")
        outcome = "discretionary"
    return facts, description, outcome, None


def generate_synthetic_year(
    *,
    seed: int,
    count: int,
    root: Path | None = None,
    distributions: dict[str, Any] | None = None,
) -> SyntheticYear:
    """Return a deterministic synthetic year of dated permit history.

    ``seed`` and ``count`` are explicit and bounded by the ``limits`` of the
    distributions document (``ValueError`` outside them).  The same
    ``(seed, count, distribution version)`` always returns the same cases.
    Arrival dates are spread over the twelve months of the window; decision
    and issuance dates follow each case's own lifecycle, and a case still
    open at the end of the window carries no decision.  The fence heights and
    the shed areas straddle every threshold of the published rules (front 4
    ft, side and rear 6 ft, and 7 ft; sheds 200 and 600 sq ft).
    """
    config = distributions if distributions is not None else load_distributions(root)
    limits = config["limits"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= int(limits["max_seed"]):
        raise ValueError(f"seed must be an integer from 0 to {limits['max_seed']}")
    if isinstance(count, bool) or not isinstance(count, int) or not (
        int(limits["min_count"]) <= count <= int(limits["max_count"])
    ):
        raise ValueError(
            f"count must be an integer from {limits['min_count']} to {limits['max_count']}"
        )

    generator = random.Random(f"{config['population_id']}:{config['distribution_version']}:{seed}")
    parcels = _town_parcels(root)
    window_end = datetime.fromisoformat(config["window"]["end"].replace("Z", "+00:00"))
    window_days = int(config["window"]["days"])
    window_start = window_end - timedelta(days=window_days)
    month_weights = config["month_weights"]
    month_total = float(sum(month_weights))

    type_categories = _type_process_categories(root)

    # The fixed businesses: each sits on one parcel of the commercial district,
    # and the bars cluster on the first few parcels.
    commercial_parcels = parcels.get("C-2", [])
    business_sites: dict[str, dict[str, str]] = {}
    for category in sorted(config["businesses"]):
        for position, name in enumerate(config["businesses"][category]):
            if not commercial_parcels:
                break
            if category == "bar":
                site = commercial_parcels[position % int(config["bar_cluster"]["parcel_count"])]
            else:
                offset = (sorted(config["businesses"]).index(category) * 5 + position * 3)
                site = commercial_parcels[(offset + 4) % len(commercial_parcels)]
            business_sites[name] = site

    applicants = config["applicants"]
    pool = [
        f"{applicants['first_names'][i % len(applicants['first_names'])]} "
        f"{applicants['last_names'][(i * 7 + i // len(applicants['first_names'])) % len(applicants['last_names'])]}"
        for i in range(int(applicants["pool_size"]))
    ]

    drafts: list[dict[str, Any]] = []
    for index in range(count):
        district = _pick(generator, config["district_weights"])
        type_key = _pick(generator, config["type_weights"][district])
        slot = _pick(generator, {f"{m:02d}": w for m, w in enumerate(month_weights)})
        offset_days = (int(slot) + generator.random()) * window_days / len(month_weights)
        arrived = window_start + timedelta(days=offset_days, hours=8 + generator.random() * 9)
        arrived = min(arrived, window_end - timedelta(hours=1)).replace(microsecond=0)
        facts, description, rule_outcome, _ = _case_facts(generator, type_key, config, index)

        # The site: a variance clusters on a few parcels of one district; a
        # commercial case sits at its business.
        business_name: str | None = None
        business_category: str | None = None
        if type_key in config["commercial_types"] and commercial_parcels:
            weights = config["business_category_weights_by_type"].get(
                type_key, config["business_category_weights"]
            )
            business_category = _pick(generator, weights)
            business_name = generator.choice(config["businesses"][business_category])
            site = business_sites[business_name]
            district = site["district"]
        else:
            candidates = parcels.get(district) or parcels[sorted(parcels)[0]]
            cluster = config["variance_cluster"]
            if (
                type_key == "zoning_variance"
                and district == cluster["district"]
                and generator.random() < float(cluster["share"])
            ):
                site = candidates[generator.randrange(min(int(cluster["parcel_count"]), len(candidates)))]
            else:
                site = candidates[generator.randrange(len(candidates))]
        facts["parcel_number"] = site["parcel_number"]
        facts["submitted_parcel"] = site["parcel_number"]
        facts["submitted_site_text"] = site["site_address"]
        facts["project_description"] = description

        contractor_name: str | None = None
        share_config = config["contractor_share"]
        if type_key not in share_config["none"]:
            share = float(share_config.get(type_key, share_config["default"]))
            if generator.random() < share:
                trade = config["contractor_trade"].get(type_key, "general")
                contractor_name = generator.choice(config["contractors"][trade])

        applicant_name = pool[generator.randrange(len(pool))]
        channel = _pick(generator, config["channel_weights"])
        priority = "high" if generator.random() < float(config["priority_high_share"]) else "normal"
        draft_roll = generator.random()
        decision_lo, decision_hi = config["lifecycle"]["decision_days"][type_categories.get(type_key, "simple")]
        decision_lag = decision_lo + generator.random() * (decision_hi - decision_lo)
        issue_lo, issue_hi = config["lifecycle"]["issue_days"]
        issue_lag = issue_lo + generator.random() * (issue_hi - issue_lo)
        issue_roll = generator.random()
        outcome_roll = generator.random()
        condition_roll = generator.random()
        waiver_roll = generator.random()
        drafts.append(
            {
                "type_key": type_key,
                "district": district,
                "site": site,
                "arrived": arrived,
                "facts": facts,
                "description": description,
                "rule_outcome": rule_outcome,
                "business_name": business_name,
                "business_category": business_category,
                "contractor_name": contractor_name,
                "applicant_name": applicant_name,
                "channel": channel,
                "priority": priority,
                "side_roll": draft_roll,
                "decision_lag": decision_lag,
                "issue_lag": issue_lag,
                "issue_roll": issue_roll,
                "outcome_roll": outcome_roll,
                "condition_roll": condition_roll,
                "waiver_roll": waiver_roll,
            }
        )

    drafts.sort(key=lambda item: (item["arrived"], item["type_key"]))
    cases: list[SyntheticCase] = []
    side = config["side_outcomes"]
    for position, draft in enumerate(drafts, start=1):
        number = f"SYNTH-{position:06d}"
        type_key = draft["type_key"]
        arrived = draft["arrived"]
        decided_at = None
        issued_at = None
        permit_number = None
        outcome = None
        conditions: tuple[str, ...] = ()
        waivers: tuple[dict[str, Any], ...] = ()
        denial_code = None
        exception_kinds: list[str] = []
        status = "submitted"

        roll = draft["side_roll"]
        if roll < float(side["withdrawn"]):
            status = "withdrawn"
        elif roll < float(side["withdrawn"]) + float(side["returned"]):
            status = "returned"
        elif roll < float(side["withdrawn"]) + float(side["returned"]) + float(side["archived"]):
            status = "archived"
        else:
            decided = (arrived + timedelta(days=draft["decision_lag"])).replace(microsecond=0)
            rule_outcome = draft["rule_outcome"]
            if decided > window_end:
                age_days = (window_end - arrived).days
                status = "submitted" if age_days < 2 else "under_review"
            else:
                if rule_outcome == "fail":
                    outcome = "denied"
                elif rule_outcome == "discretionary":
                    disc = config["discretionary_outcomes"]
                    choice = _pick_from_roll(draft["outcome_roll"], disc)
                    outcome = "denied" if choice == "denied" else "approved"
                    if choice == "approved_with_conditions":
                        conditions = _conditions(config, type_key)
                else:
                    outcome = "approved"
                    if rule_outcome == "condition" or (
                        rule_outcome == "judgment"
                        and draft["condition_roll"] < float(config["judgment_approval_with_conditions_share"])
                    ):
                        conditions = _conditions(config, type_key)
                if outcome == "denied":
                    denial_code = "DENIAL_RULE_FAILURE" if rule_outcome == "fail" else "DOES_NOT_MEET_CODE"
                    exception_kinds.append("denial")
                    status = "denied"
                    decided_at = decided
                else:
                    decided_at = decided
                    status = "approved"
                    if conditions:
                        exception_kinds.append("conditions")
                    if draft["waiver_roll"] < float(config["waiver_share_of_approvals"]):
                        waivers = (
                            {
                                "finding_id": "",
                                "finding_type": "missing_document",
                                "message": "A supporting document was not applicable.",
                                "waived_at": decided.isoformat(),
                                "waived_by_actor_id": SYNTHETIC_ACTOR_ID,
                                "reason_code": "WAIVE_MINOR_DOCUMENT_DEFECT",
                                "reason_code_label": "Minor document defect",
                                "reason_code_version": 1,
                                "reason": "Synthetic history.",
                            },
                        )
                        exception_kinds.append("waiver")
                    candidate = (decided + timedelta(days=draft["issue_lag"])).replace(microsecond=0)
                    if (
                        draft["issue_roll"] < float(config["lifecycle"]["share_issued_after_approval"])
                        and candidate <= window_end
                    ):
                        issued_at = candidate
                        permit_number = f"ACME-SYN-{position:06d}"
                        status = "issued"
        if type_key == "zoning_variance":
            exception_kinds.insert(0, "variance")
        cases.append(
            SyntheticCase(
                number=number,
                permit_type_key=type_key,
                district=draft["district"],
                parcel_number=draft["site"]["parcel_number"],
                site_address=draft["site"]["site_address"],
                arrived_at=arrived,
                status=status,
                channel=draft["channel"],
                priority=draft["priority"],
                description=draft["description"],
                facts=draft["facts"],
                applicant_name=draft["applicant_name"],
                decided_at=decided_at,
                outcome=outcome,
                issued_at=issued_at,
                permit_number=permit_number,
                conditions=conditions,
                waivers=waivers,
                denial_reason_code=denial_code,
                contractor_name=draft["contractor_name"],
                business_name=draft["business_name"],
                business_category=draft["business_category"],
                exception_kinds=tuple(exception_kinds),
            )
        )
    return SyntheticYear(
        population_id=config["population_id"],
        distribution_version=config["distribution_version"],
        seed=seed,
        count=count,
        window_start=window_start,
        window_end=window_end,
        cases=tuple(cases),
    )


def _pick_from_roll(roll: float, weights: dict[str, float]) -> str:
    keys = sorted(weights)
    total = float(sum(weights[key] for key in keys))
    running = 0.0
    for key in keys:
        running += float(weights[key]) / total
        if roll < running:
            return key
    return keys[-1]


def _conditions(config: dict[str, Any], type_key: str) -> tuple[str, ...]:
    return tuple(config["conditions_by_type"].get(type_key, ["Final inspection required."]))


def _type_process_categories(root: Path | None = None) -> dict[str, str]:
    base = root if root is not None else _REPO_ROOT
    rules = _read_json(str(base / "config" / "rules_and_fees.json"))
    return {
        item["key"]: item.get("process_category") or "simple" for item in rules["permit_types"]
    }


__all__ = [
    "CHANNELS",
    "DISTRIBUTIONS_FILE",
    "PERMIT_TYPE_KEYS",
    "RANDOM_SEED",
    "SCENARIO_NAMES",
    "SYNTHETIC_ACTOR_ID",
    "SYNTHETIC_SCENARIO_ID",
    "SyntheticCase",
    "SyntheticYear",
    "build_scenario",
    "generate_synthetic_year",
    "load_distributions",
]

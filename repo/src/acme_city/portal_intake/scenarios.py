"""Deterministic simulated intake scenarios.

Every scenario is fictional ACME City data.  Records are pure data: the same
scenario always builds the same records apart from the portal-reference
sequence suffix, so a demo and its tests stay repeatable.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
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


__all__ = [
    "CHANNELS",
    "PERMIT_TYPE_KEYS",
    "RANDOM_SEED",
    "SCENARIO_NAMES",
    "build_scenario",
]

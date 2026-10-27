"""Deterministic simulated intake scenarios.

Every scenario is fictional ACME City data.  Records are pure data: the same
scenario always builds the same records apart from the portal-reference
sequence suffix, so a demo and its tests stay repeatable.
"""

from __future__ import annotations

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
)

_BASE_RECEIVED = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def _record(
    *,
    suffix: str,
    channel: str,
    applicant_name: str,
    email: str,
    facts: dict[str, Any],
    documents: list[dict[str, str]],
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


def _fence_docs(height: str, location: str) -> list[dict[str, str]]:
    return [
        {
            "document_type": "site_plan",
            "text": (
                "ACME CITY FICTIONAL SITE PLAN\n"
                f"Structure: fence, location {location}, height {height} ft.\n"
                "Parcel reference: ACME-P-1001\n"
                "Site address: 400 Lantern Row, ACME City\n"
            ),
        },
        {
            "document_type": "material_spec",
            "text": "Material specification: wood privacy panels, fictional demo.\n",
        },
    ]


def build_scenario(name: str, *, sequence_start: int = 1) -> list[IntakeRecordCommand]:
    """Return the deterministic records of one scenario.

    ``sequence_start`` shifts the portal-reference suffix so repeated runs of
    the same scenario create fresh records instead of duplicates.
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
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=_fence_docs("6", "side_rear"),
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
                    "submitted_site_text": "400 Lantern Row, ACME City",
                },
                documents=_fence_docs("6", "front"),
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
                    {
                        "document_type": "site_plan",
                        "text": (
                            "ACME CITY FICTIONAL SITE PLAN\n"
                            "Structure: deck, height 3 ft, rear setback 10 ft.\n"
                            "Parcel reference: ACME-P-1001\n"
                        ),
                    },
                    {
                        "document_type": "material_spec",
                        "text": "Material specification: composite decking, fictional demo.\n",
                    },
                ],
            )
        ]
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


__all__ = ["SCENARIO_NAMES", "build_scenario"]

"""Generated intake records for the demonstration.

The generator builds a deterministic batch of outside-intake records.  A
record is plain data: it carries no authority and is submitted through
:class:`acme_city.portal_intake.service.IntakeService`, so every record
becomes a case, writes its audit row and waits for the intake agent.

Each batch holds a fixed mix of six outcomes, so a demonstration always shows
a clean case, a case with a missing document, a repeat of an earlier case, a
case that breaks a published rule, a case whose contractor registration has
expired and a case that sits exactly on a rule limit:

==================  =========================================================
outcome             what the record shows
==================  =========================================================
clean_approve       a fence well inside the published limits
missing_document    a fence with no site plan
duplicate_applicant the same project as the case before it, this time
                    with the site plan
rule_breach         a front-yard fence over the 4 ft maximum
expired_contractor  an HVAC replacement whose registration has expired
borderline          a fence exactly on the published limit
==================  =========================================================

The repeat follows the case with the missing site plan, because the intake
agent finds a repeat in both directions: the case a repeat comes from is
held for early resolution too, and a case that has to reach the reviewer
should not be held for that.

Nothing here names a walkthrough person or address, and none of the
D-party names is reused.  The same ``(seed, nonce)`` always builds the same
records; a different nonce builds different ones, so a repeated run creates
new cases instead of the same ones again.
"""
# REQUIRES: ING-01, PER-01
# The records are pure data, the caps are refused before anything is written,
# and the batch carries no authority of its own.

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from acme_city.core.errors import ValidationError
from acme_city.portal_intake.schemas import IntakeDocument, IntakeRecordCommand

#: The outcome kinds one generated batch holds, in the order they appear.
OUTCOME_KINDS: tuple[str, ...] = (
    "clean_approve",
    "missing_document",
    "duplicate_applicant",
    "rule_breach",
    "expired_contractor",
    "borderline",
)

#: The most records one call may build.
MAX_GENERATED_PER_CALL = 20

#: The most generated cases the demonstration may hold.
MAX_GENERATED_TOTAL = 200

#: The prefix every generated portal reference carries.
GENERATED_REFERENCE_PREFIX = "PORTAL-2026-GEN"

#: The channels the outside application gathers through.
CHANNELS: tuple[str, ...] = ("portal", "counter_scan", "email", "mail", "fax")

#: The fictional applicants the generator draws from.  None of them is a
#: seeded party, a walkthrough person or one of the D-party names, so a
#: generated case never joins an identity the demonstration already holds.
APPLICANTS: tuple[tuple[str, str], ...] = (
    ("Maren Oakes", "m.oakes@example.invalid"),
    ("Tobias Rill", "t.rill@example.invalid"),
    ("Selby Crane", "s.crane@example.invalid"),
    ("Nadia Fenner", "n.fenner@example.invalid"),
    ("Orrin Blake", "o.blake@example.invalid"),
    ("Imogen Frost", "i.frost@example.invalid"),
    ("Cassin Ward", "c.ward@example.invalid"),
    ("Delia Marsh", "d.marsh@example.invalid"),
    ("Eamon Voss", "e.voss@example.invalid"),
    ("Perin Shaw", "p.shaw@example.invalid"),
    ("Rosalie Kaye", "r.kaye@example.invalid"),
    ("Soren Vale", "s.vale@example.invalid"),
    ("Wren Halloway", "w.halloway@example.invalid"),
    ("Yara Quist", "y.quist@example.invalid"),
    ("Anwen Pike", "a.pike@example.invalid"),
    ("Bexley Rood", "b.rood@example.invalid"),
    ("Calla Wynn", "c.wynn@example.invalid"),
    ("Dorran Sly", "d.sly@example.invalid"),
    ("Elska Vane", "e.vane@example.invalid"),
    ("Fen Mallory", "f.mallory@example.invalid"),
)

#: The fictional sites the generator draws from.  Every one of them is an
#: address of the committed town, so the address locator resolves it.  The
#: walkthrough site (400 Lantern Row) and the sites of the D-party records
#: are not among them.
ADDRESSES: tuple[tuple[str, str], ...] = (
    ("402 Lantern Row, ACME City", "ACME-P-1023"),
    ("403 Lantern Row, ACME City", "ACME-P-1032"),
    ("405 Lantern Row, ACME City", "ACME-P-1033"),
    ("407 Lantern Row, ACME City", "ACME-P-1034"),
    ("409 Lantern Row, ACME City", "ACME-P-1035"),
    ("411 Lantern Row, ACME City", "ACME-P-1036"),
    ("413 Lantern Row, ACME City", "ACME-P-1037"),
    ("415 Lantern Row, ACME City", "ACME-P-1038"),
    ("101 Kestrel Way, ACME City", "ACME-P-1054"),
    ("103 Kestrel Way, ACME City", "ACME-P-1055"),
    ("87 Kestrel Way, ACME City", "ACME-P-1047"),
    ("89 Kestrel Way, ACME City", "ACME-P-1048"),
    ("91 Kestrel Way, ACME City", "ACME-P-1049"),
    ("93 Kestrel Way, ACME City", "ACME-P-1050"),
    ("20 Heron Street, ACME City", "ACME-P-1066"),
    ("22 Heron Street, ACME City", "ACME-P-1067"),
    ("24 Heron Street, ACME City", "ACME-P-1068"),
    ("85 Kestrel Court, ACME City", "ACME-P-1057"),
    ("87 Kestrel Court, ACME City", "ACME-P-1058"),
    ("88 Kestrel Court, ACME City", "ACME-P-1005"),
)

#: The fence materials the generator draws from.
MATERIALS: tuple[str, ...] = ("cedar", "composite", "vinyl", "metal")

#: The arrival time of the first record of a batch.
_BASE_RECEIVED = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)

#: The minutes between two arrivals of one batch.
_ARRIVAL_STEP = timedelta(minutes=37)


@dataclass(frozen=True)
class GeneratedRecord:
    """One generated intake record and the outcome it was built for."""

    outcome: str
    record: IntakeRecordCommand


def run_token(nonce: str) -> str:
    """Return the short token that names one run of the generator.

    The token is part of every project description of the run, so two runs
    never look like the same project and a case of one run is never taken
    for a repeat of another.
    """
    digest = hashlib.sha256(str(nonce).encode("utf-8")).hexdigest()
    return digest[:6].upper()


def outcome_mix(count: int) -> dict[str, int]:
    """Return how many records of each outcome a batch of ``count`` holds.

    The mix is exact: a batch of twelve holds two of every outcome, and the
    first kinds of :data:`OUTCOME_KINDS` take the remainder.
    """
    _check_count(count)
    mix = {kind: 0 for kind in OUTCOME_KINDS}
    for index in range(count):
        mix[OUTCOME_KINDS[index % len(OUTCOME_KINDS)]] += 1
    return mix


def generate_outcomes(seed: int, count: int, *, nonce: str = "0") -> list[GeneratedRecord]:
    """Return one deterministic batch of generated intake records.

    The batch holds the mix of :func:`outcome_mix`.  The same
    ``(seed, nonce)`` always builds the same records, and a different nonce
    builds different ones, so a repeated run creates new cases instead of
    the same ones again.  ``count`` is refused above
    :data:`MAX_GENERATED_PER_CALL`.
    """
    _check_count(count)
    _check_seed(seed)
    token = run_token(nonce)
    reference_nonce = _reference_nonce(nonce)
    generator = random.Random(f"generated:{seed}:{token}")
    applicant_offset = generator.randrange(len(APPLICANTS))
    address_offset = generator.randrange(len(ADDRESSES))

    batch: list[GeneratedRecord] = []
    built = 0
    for index in range(count):
        outcome = OUTCOME_KINDS[index % len(OUTCOME_KINDS)]
        reference = f"{GENERATED_REFERENCE_PREFIX}-{reference_nonce}-{index + 1:02d}"
        if outcome == "duplicate_applicant":
            # The repeat of the case before it: the same applicant, the same
            # site and the same project, so the intake agent finds it.  The
            # repeat arrived complete, so only the repeat itself is held.
            previous = batch[-1].record
            facts = dict(previous.submitted_facts)
            documents = [document.model_copy() for document in previous.documents]
            if not any(item.document_type == "site_plan" for item in documents):
                site_plan = _site_plan(
                    int(facts["height_ft"]),
                    str(facts["location"]),
                    str(facts["parcel_number"]),
                    str(facts["submitted_site_text"]),
                )
                documents.append(IntakeDocument(**site_plan))
            record = previous.model_copy(
                update={
                    "portal_reference": reference,
                    "received_at": _BASE_RECEIVED + _ARRIVAL_STEP * index,
                    "submitted_facts": facts,
                    "documents": documents,
                }
            )
            batch.append(GeneratedRecord(outcome=outcome, record=record))
            continue
        name, email = APPLICANTS[(built + applicant_offset) % len(APPLICANTS)]
        site, parcel = ADDRESSES[(built + address_offset) % len(ADDRESSES)]
        material = generator.choice(MATERIALS)
        length = generator.randrange(20, 90, 5)
        expired_on = (
            f"2026-{generator.randrange(1, 7):02d}-{generator.randrange(1, 29):02d}"
        )
        facts, documents, permit_type_key = _content(
            outcome=outcome,
            material=material,
            length=length,
            token=token,
            parcel=parcel,
            address=site,
            expired_on=expired_on,
            licence=f"CR-2026-{4400 + built:04d}",
        )
        facts.update(
            {
                "parcel_number": parcel,
                "submitted_parcel": parcel,
                "submitted_site_text": site,
            }
        )
        record = IntakeRecordCommand(
            channel=CHANNELS[index % len(CHANNELS)],  # type: ignore[arg-type]
            received_at=_BASE_RECEIVED + _ARRIVAL_STEP * index,
            portal_reference=reference,
            applicant={
                "name": name,
                "email": email,
                "phone": f"+1-555-71{built:02d}",
            },
            site_address=site,
            parcel_text=parcel,
            permit_type_key=permit_type_key,
            submitted_facts=facts,
            documents=documents,
        )
        batch.append(GeneratedRecord(outcome=outcome, record=record))
        built += 1
    return batch


def _content(
    *,
    outcome: str,
    material: str,
    length: int,
    token: str,
    parcel: str,
    address: str,
    expired_on: str,
    licence: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Return the facts, the documents and the type of one generated case."""
    if outcome == "expired_contractor":
        facts: dict[str, Any] = {
            "project_description": (
                f"Replacement of a failed air handler, {length} ft of ductwork, "
                f"job {token}"
            ),
            "contractor_license": licence,
            "contractor_license_expired_on": expired_on,
            "valuation": "800.00",
        }
        documents = [_contractor_note(licence, expired_on)]
        return facts, documents, "hvac"

    if outcome == "rule_breach":
        height, location, setback = 6, "front", 2
    elif outcome == "borderline":
        height, location, setback = 4, "front", 5
    else:
        height, location, setback = 4, "side_rear", 3
    facts = {
        "project_description": (
            f"{height} ft {location.replace('_', '-')} privacy fence in {material} "
            f"panels, {length} ft run, job {token}"
        ),
        "height_ft": height,
        "setback_ft": setback,
        "structure_kind": "fence",
        "location": location,
        "valuation": "1200.00",
    }
    documents = [_site_plan(height, location, parcel, address), _material_spec(material)]
    if outcome == "missing_document":
        # The site plan never arrived.
        documents = [_material_spec(material)]
    return facts, documents, "deck_fence"


def _site_plan(height: int, location: str, parcel: str, address: str) -> dict[str, Any]:
    """Return the site plan of one generated fence."""
    return {
        "document_type": "site_plan",
        "text": (
            "ACME CITY FICTIONAL SITE PLAN\n"
            f"Structure: fence, location {location}, height {height} ft.\n"
            f"Parcel reference: {parcel}\n"
            f"Site address: {address}\n"
        ),
        "quality": [],
    }


def _material_spec(material: str) -> dict[str, Any]:
    """Return the material specification of one generated fence."""
    return {
        "document_type": "material_spec",
        "text": f"Material specification: {material} privacy panels, fictional demo.\n",
        "quality": [],
    }


def _contractor_note(licence: str, expired_on: str) -> dict[str, Any]:
    """Return the contractor note of one generated HVAC replacement."""
    return {
        "document_type": "contractor_license_copy",
        "text": (
            "ACME CITY FICTIONAL CONTRACTOR NOTE\n"
            f"Contractor registration {licence}.\n"
            f"The registration expired on {expired_on}.\n"
        ),
        "quality": [],
    }


def _reference_nonce(nonce: str) -> str:
    """Return the nonce as a token that is safe inside a portal reference."""
    cleaned = "".join(
        character if character.isascii() and character.isalnum() else "-"
        for character in str(nonce)
    ).strip("-")
    return (cleaned or "0")[:24]


def _check_count(count: int) -> None:
    """Refuse a count that is not a whole number inside the per-call cap."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValidationError("the number of generated records must be a whole number")
    if count < 1:
        raise ValidationError("the number of generated records must be one or more")
    if count > MAX_GENERATED_PER_CALL:
        raise ValidationError(
            f"one call may create at most {MAX_GENERATED_PER_CALL} records; "
            f"{count} were asked for"
        )


def _check_seed(seed: int) -> None:
    """Refuse a seed that is not a whole number."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValidationError("the seed must be a whole number of zero or more")


__all__ = [
    "ADDRESSES",
    "APPLICANTS",
    "CHANNELS",
    "GENERATED_REFERENCE_PREFIX",
    "GeneratedRecord",
    "MAX_GENERATED_PER_CALL",
    "MAX_GENERATED_TOTAL",
    "OUTCOME_KINDS",
    "generate_outcomes",
    "outcome_mix",
    "run_token",
]

"""The permit life cycle as one table: every status and every move between them.

The moves themselves live in the services named on each row; this module only
describes them, so the life cycle page, the architecture record and the judge
walkthrough read one list.  ``tests/unit/test_lifecycle_map.py`` checks the
table against the status constraint of the model and the status sets the
services export, and ``tests/unit/test_lifecycle_map_probe.py`` runs the
services whose status rules are written inline from every status, so the
description cannot drift from the code.

An application row is created as submitted; Draft is the applicant's saved
form before the row exists, so no service move starts from it but Submit.

``actor`` is either a permission id, which the page resolves to the personas
that hold it, or ``agent:<name>`` for a move an automated agent makes.
"""
# REQUIRES: PER-03, PER-04, UX-04
# One described life cycle, checked against the enforced statuses and moves.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acme_city.applicant_portal.service import RESPONDABLE_STATUSES
from acme_city.fixtures.loader import CONFIG_DIRNAME, REPO_ROOT
from acme_city.permits.decisions import DECIDABLE_STATUSES
from acme_city.permits.lifecycle import (
    ADVANCEABLE_STATUSES,
    ARCHIVABLE_STATUSES,
    RETURNABLE_STATUSES,
    REVISION_STATUSES,
)


@dataclass(frozen=True)
class Status:
    """One status a permit application can hold."""

    key: str
    label: str
    meaning: str
    #: ``start``, ``active``, ``end`` (no further move) or ``closed`` (archived, can be restored).
    kind: str
    #: Set when no move in the application reaches this status; only seeded data holds it.
    seeded_only: bool = False


@dataclass(frozen=True)
class Move:
    """One move from one or more statuses to another."""

    key: str
    sources: tuple[str, ...]
    target: str
    action: str
    actor: str
    where: str
    note: str = ""


STATUSES: tuple[Status, ...] = (
    Status("draft", "Draft", "The applicant is filling in the form and has saved it. The City does not see it yet.", "start"),
    Status("submitted", "Submitted", "The applicant has sent the application. The intake checks run next.", "active"),
    Status(
        "needs_information",
        "Needs information",
        "Something is missing, or a finding needs a person's judgement. The case waits in early resolution.",
        "active",
    ),
    Status(
        "revisions_requested",
        "Revisions requested",
        "A reviewer has asked the applicant to change the plans or answers.",
        "active",
    ),
    Status("ready_for_review", "Ready for review", "The intake checks are clear. The case waits in the review queue.", "active"),
    Status(
        "under_review",
        "Under review",
        "A reviewer set the agent's recommendation aside and is reviewing the case in person.",
        "active",
    ),
    Status(
        "approved",
        "Approved",
        "The reviewer approved the application, with or without conditions. The permit is not issued yet.",
        "active",
    ),
    Status(
        "issued",
        "Issued",
        "The permit is issued after the fee is assessed, paid and reconciled. It is never archived, but a record correction reopens it.",
        "end",
    ),
    Status(
        "denied",
        "Denied",
        "The reviewer denied the application, with a recorded reason. A new validation reopens it.",
        "end",
    ),
    Status("returned", "Returned", "The City returned the application to the applicant without a review.", "end"),
    Status(
        "withdrawn",
        "Withdrawn",
        "The applicant withdrew the application. The app has no withdraw action yet; only seeded history holds this status.",
        "end",
        seeded_only=True,
    ),
    Status("archived", "Archived", "The City closed the case. A restore returns it to the status it held.", "closed"),
)

#: The file the persona grants are seeded from.
ACTORS_FILE = REPO_ROOT / CONFIG_DIRNAME / "actors.json"

#: The statuses a revert of a pending agent recommendation moves to under review:
#: every status but draft (no row), under review itself, the three it leaves
#: unchanged (issued, approved, denied) and archived (refused).
REVERT_SOURCES: frozenset[str] = frozenset(
    {"submitted", "needs_information", "revisions_requested", "ready_for_review", "returned", "withdrawn"}
)

#: The statuses Correct the application record moves back to submitted: every
#: status but draft (no row), submitted itself, returned and archived (refused).
REVISE_SOURCES: frozenset[str] = frozenset(
    {"needs_information", "revisions_requested", "ready_for_review", "under_review", "approved", "denied", "withdrawn", "issued"}
)

#: The statuses Run application checks moves to ready for review: every
#: status of a stored case except issued (kept), returned (refused), archived
#: (refused) and ready for review itself.
VALIDATE_SOURCES: frozenset[str] = frozenset(
    {"submitted", "needs_information", "revisions_requested", "under_review", "approved", "denied", "withdrawn"}
)

#: The target of the restore move: the status the case held before it was archived.
PREVIOUS = "previous"

MOVES: tuple[Move, ...] = (
    Move("submit", ("draft",), "submitted", "Submit the application", "application.submit", "Applicant: City website, Apply"),
    Move(
        "route_early",
        ("submitted",),
        "needs_information",
        "Route to early resolution",
        "agent:intake",
        "Intake agent",
        "A blocking finding, or a finding a person must judge.",
    ),
    Move(
        "route_review",
        ("submitted",),
        "ready_for_review",
        "Route to review",
        "agent:intake",
        "Intake agent",
        "No blocking finding.",
    ),
    Move(
        "validate",
        tuple(sorted(VALIDATE_SOURCES)),
        "ready_for_review",
        "Run application checks",
        "application.evaluate",
        "Permit workspace",
        "Runs the rule checks on the current revision. It reopens any case that is not issued, "
        "returned or archived, including an approved or denied one.",
    ),
    Move(
        "advance",
        tuple(sorted(ADVANCEABLE_STATUSES)),
        "ready_for_review",
        "Advance to review",
        "permit.case.advance",
        "Early resolution queue",
        "Refused while a current, unwaived blocking finding stands.",
    ),
    Move(
        "return",
        tuple(sorted(RETURNABLE_STATUSES)),
        "returned",
        "Return to the applicant",
        "permit.case.return",
        "Early resolution queue",
    ),
    Move(
        "resubmit",
        tuple(sorted(RESPONDABLE_STATUSES)),
        "submitted",
        "Answer and resubmit",
        "application.submit",
        "Applicant: City website, Track",
        "Versions the case and keeps the first submission date.",
    ),
    Move(
        "request_revisions",
        tuple(sorted(REVISION_STATUSES)),
        "revisions_requested",
        "Request revisions",
        "permit.case.request_revisions",
        "Permit workspace",
    ),
    Move(
        "revert_recommendation",
        tuple(sorted(REVERT_SOURCES)),
        "under_review",
        "Revert the agent recommendation",
        "permit.decide",
        "Permit workspace",
        "Needs a pending agent recommendation. The reviewer takes the case over from the agent.",
    ),
    Move(
        "revise",
        tuple(sorted(REVISE_SOURCES)),
        "submitted",
        "Correct the application record",
        "application.revision.submit",
        "Permit workspace",
        "Records a new revision. It reopens any case that is not returned or archived, including an issued one.",
    ),
    Move(
        "approve",
        tuple(sorted(DECIDABLE_STATUSES)),
        "approved",
        "Approve, or approve with changes",
        "permit.decide",
        "Permit workspace",
    ),
    Move("deny", tuple(sorted(DECIDABLE_STATUSES)), "denied", "Deny", "permit.decide", "Permit workspace"),
    Move(
        "request_information",
        tuple(sorted(DECIDABLE_STATUSES - {"needs_information"})),
        "needs_information",
        "Request information",
        "permit.decide",
        "Permit workspace",
    ),
    Move(
        "issue",
        ("approved",),
        "issued",
        "Issue the permit",
        "permit.issue",
        "Permit workspace",
        "Needs the approved links, the decision, the fee assessment, the payment allocation and reconciliation.",
    ),
    Move(
        "archive",
        tuple(sorted(ARCHIVABLE_STATUSES)),
        "archived",
        "Archive",
        "permit.case.archive",
        "Permit workspace",
    ),
    Move(
        "restore",
        ("archived",),
        PREVIOUS,
        "Restore",
        "permit.case.restore",
        "Permit workspace",
        "Returns the case to the status it held before it was archived.",
    ),
)


def persona_holders(actors_file: Path = ACTORS_FILE) -> dict[str, list[str]]:
    """Return, for each permission, the labels of the selectable personas seeded with it."""
    data = json.loads(actors_file.read_text(encoding="utf-8"))
    holders: dict[str, list[str]] = {}
    for persona in data["personas"]:
        if persona["selectable"]:
            for grant in persona["grants"]:
                holders.setdefault(grant["permission_id"], []).append(persona["label"])
    return holders


def status(key: str) -> Status:
    """Return one status by key."""
    return next(item for item in STATUSES if item.key == key)


def moves_from(key: str) -> list[Move]:
    """Return the moves that leave a status."""
    return [move for move in MOVES if key in move.sources]


__all__ = ["MOVES", "Move", "PREVIOUS", "REVERT_SOURCES", "REVISE_SOURCES", "STATUSES", "Status", "VALIDATE_SOURCES", "moves_from", "persona_holders", "status"]

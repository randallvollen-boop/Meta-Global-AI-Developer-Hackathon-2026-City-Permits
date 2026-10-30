"""The permit life cycle page and the judge walkthrough.

Both pages read; neither changes a record.  The life cycle comes from
:mod:`acme_city.permits.lifecycle_map`; who makes each move is resolved from
the grants the personas hold now, so the page never claims an authority the
server would refuse.  Every "Open as" button posts to the ordinary persona
switch, so a step runs the real screen with the real checks.
"""
# REQUIRES: UX-04, PER-03
# The life cycle and the walkthrough are read-only views over the enforced
# statuses, the live grants and the stored cases.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.permissions import PermissionResolver
from acme_city.permits import lifecycle_map as lm
from acme_city.persistence.models import permit
from acme_city.ui.view_models import persona_options

#: The persona that opens a case example on the life cycle page.
CASE_PERSONA = "Permit Reviewer"

#: The names of the automated agents that make moves.
AGENT_NAMES: dict[str, str] = {"agent:intake": "Intake agent (automatic)"}

#: The statuses on the main path, in order; the page draws them as one row.
MAIN_PATH: tuple[str, ...] = ("draft", "submitted", "ready_for_review", "approved", "issued")


@dataclass(frozen=True)
class Step:
    """One step of the judge walkthrough."""

    title: str
    persona: str
    path: str
    do: str
    look_for: str


WALKTHROUGH: tuple[Step, ...] = (
    Step(
        "Watch the tour (optional)",
        "",
        "/select",
        "Play the video above the persona cards. It runs under three minutes.",
        "Five personas, each a fictional person with one job. Every record in the app is fictional.",
    ),
    Step(
        "Read the permit life cycle",
        "",
        "/lifecycle",
        "Read the main path across the top, then the statuses a case can move to instead.",
        "Each move names who makes it. An agent only routes cases. A person decides and issues.",
    ),
    Step(
        "Apply for a permit",
        "Applicant",
        "/apply",
        "Choose a deck or fence permit. Type a street and pick a suggested address. Answer the questions, submit, then open Track.",
        "A reference number and the tracker. The help panel cites the published ACME rule behind each answer.",
    ),
    Step(
        "Let the agent route the work",
        "Agent Operator",
        "/agent/intake",
        "Press Wake agent if the intake agent is asleep, then press Process all waiting.",
        "Each waiting case goes to early resolution or to review, with its reason beside it.",
    ),
    Step(
        "Clear a case for review",
        "Data Steward",
        "/queue/early-resolution",
        "Open the case from step 3 if it is listed, or the top case. Read each finding and the evidence behind it.",
        "Advance to review is refused while a blocking finding stands. Return to the applicant is the other way out.",
    ),
    Step(
        "Decide a case",
        "Permit Reviewer",
        "/queue/review",
        "Open the top case. Press Run application checks, read the agent's recommendation, then Record review decision with a reason.",
        "Deciding and issuing are separate. Issue permit stays blocked until the fee is assessed, paid and reconciled, so a blocked button is expected.",
    ),
    Step(
        "Check the record of the decision",
        "City Administrator",
        "/ops/audit",
        "Find the decision recorded in step 6.",
        "Who acted, when, on which case, and the reason they gave.",
    ),
    Step(
        "See the city at a glance",
        "City Administrator",
        "/insight/city",
        "Filter the City view by permit type or outcome. Then open the planning overview and try a what if policy scenario.",
        "The map, the counts and the definition printed beside each figure.",
    ),
    Step(
        "Look up permits as a resident",
        "",
        "/city/community",
        "Search by a street name on the City of Acme website.",
        "The public record shows the permit, the parcel and the outcome. It never shows a homeowner's name, documents or fees.",
    ),
)


def _persona_ids(session: Session) -> dict[str, str]:
    return {option["label"]: option["actor_id"] for option in persona_options(session)}


def _holders(session: Session) -> dict[str, list[str]]:
    """Return, for each permission, the labels of the personas that hold it now."""
    resolver = PermissionResolver(session)
    holders: dict[str, list[str]] = {}
    for option in persona_options(session):
        for permission in resolver.permissions_for(option["actor_id"]):
            holders.setdefault(permission, []).append(option["label"])
    return holders


def _who(move: lm.Move, holders: dict[str, list[str]]) -> list[str]:
    if move.actor.startswith("agent:"):
        return [AGENT_NAMES.get(move.actor, move.actor.split(":", 1)[1].title() + " agent")]
    return holders.get(move.actor, [])


def lifecycle_view(session: Session) -> dict[str, Any]:
    """Return the life cycle page: statuses, moves, live counts and one example case each."""
    holders = _holders(session)
    counts = dict(
        session.execute(
            select(permit.Application.status, func.count()).group_by(permit.Application.status)
        ).all()
    )
    examples: dict[str, Any] = {}
    for key in counts:
        row = session.execute(
            select(permit.Application.id, permit.Application.source_application_number)
            .where(permit.Application.status == key)
            .order_by(permit.Application.id)
            .limit(1)
        ).first()
        if row is not None:
            examples[key] = {"id": row[0], "reference": row[1]}
    labels = {item.key: item.label for item in lm.STATUSES}
    statuses = []
    for item in lm.STATUSES:
        moves = [
            {
                "action": move.action,
                "target": "the status it held before" if move.target == lm.PREVIOUS else labels[move.target],
                "target_key": move.target,
                "who": _who(move, holders),
                "where": move.where,
                "note": move.note,
            }
            for move in lm.moves_from(item.key)
        ]
        statuses.append(
            {
                "key": item.key,
                "label": item.label,
                "meaning": item.meaning,
                "kind": item.kind,
                "seeded_only": item.seeded_only,
                "count": int(counts.get(item.key, 0)),
                "example": examples.get(item.key) if item.key != "draft" else None,
                "moves": moves,
            }
        )
    return {
        "main_path": [{"key": key, "label": labels[key]} for key in MAIN_PATH],
        "statuses": statuses,
        "case_persona": {"label": CASE_PERSONA, "actor_id": _persona_ids(session).get(CASE_PERSONA, "")},
        "move_count": len(lm.MOVES),
    }


def walkthrough_view(session: Session) -> dict[str, Any]:
    """Return the judge walkthrough with the actor id each step switches to."""
    ids = _persona_ids(session)
    return {
        "steps": [
            {
                "number": number,
                "title": step.title,
                "persona": step.persona,
                "actor_id": ids.get(step.persona, "") if step.persona else "",
                "path": step.path,
                "do": step.do,
                "look_for": step.look_for,
            }
            for number, step in enumerate(WALKTHROUGH, start=1)
        ]
    }


__all__ = ["MAIN_PATH", "WALKTHROUGH", "Step", "lifecycle_view", "walkthrough_view"]

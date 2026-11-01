"""The permit life cycle page and the judge walkthrough.

Both pages read; neither changes a record.  The life cycle comes from
:mod:`acme_city.permits.lifecycle_map`; who makes each move comes from the
grants the personas are seeded with, the same list the architecture page uses.  Every "Open as" button posts to the ordinary persona
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
        "Open the video below the persona cards and play it. It runs under three minutes.",
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
        "Choose Residential deck or fence. Keep the applicant name already filled in. Type 400 Lantern Row and pick the suggested address. Answer the questions, for example a 6 ft fence in the side or rear yard, 2 ft from the property line. Attach a small .txt file for each of the two required documents, tick the certification, press Submit application, then press Track application. Submit once: a second application for the same project at the same address is flagged as a duplicate. To see early resolution later, submit a second application at another address, such as 100 Kestrel Way, and tick Sent to the City separately for one document instead of attaching it.",
        "A reference number such as SYN-APP-614, and a tracker that lists both documents as received. The assistant opens over the page and cites the published ACME rule behind each answer.",
    ),
    Step(
        "Let the agent route the work",
        "Agent Operator",
        "/agent/intake",
        "Press Wake agent. The page shows it awake straight away. Then press Process next 20, or Process one beside your case. Open All runs, and press View run on the row for your case. Then go back to Agents, click Steward assistant under Agent status, and press Wake agent there too, so the Data Steward can ask it for recommendations.",
        "The run shows Completed, and its Router line under Processing steps says Ready for review in the Building area. A case with a blocking finding, such as a missing document, goes to early resolution instead, and the Router line gives that reason.",
    ),
    Step(
        "Clear a case for review",
        "Data Steward",
        "/steward",
        "In Data issues, press Prepare recommendations. The steward assistant gives each task it works on (up to 20 per press) a High, Review or Held pill and a one-line reason. Open the Check the property issue that names your case reference. Press Start under Approve parcel link for that reference, write a decision note and submit it. Then open the Check the person identity issue from the ACME ePermit Portal source, press Start under Confirm link to Demo Applicant, write a decision note and submit it.",
        "The assistant only proposes: Accept recommendation and Accept all high-confidence (N), which shows the exact list first, record the decision in your name. Without these two approvals the Permit Reviewer cannot approve the case: the decision is refused with the blockers parcel_link_unapproved and identity_link_unapproved. A case that arrives with a blocking finding, such as a second application with a missing document, waits in Early resolution instead (/queue/early-resolution). There Advance to review is off until the finding is cleared, and Return to the applicant is the other way out.",
    ),
    Step(
        "Decide a case",
        "Permit Reviewer",
        "/queue/review",
        "Open the case from step 3. On the People & property tab, press Start under Confirm parcel and submit it. The page updates in place and keeps your tab. On the Review tab, press Start under Run application checks and submit it: the rule results appear and the decision form is offered. Press Start under Record review decision, choose Approve, write a rationale and submit it. Then try Issue permit.",
        "Deciding and issuing are separate. After the approval, Issue permit is refused (the permit may not be issued yet) until the fee is assessed, paid and reconciled on the Reconciliation screen, so a refusal is expected.",
    ),
    Step(
        "Check the record of the decision",
        "City Administrator",
        "/ops/audit",
        "Choose Recorded permit decision in the Action filter and press Apply filters, then press View details on the top row.",
        "The actor, the time, the decision record and, under References, the case the decision belongs to, named by its reference (SYN-APP-nnn, the number from step 3). A denial also shows its reason code under Recorded detail. The written rationale is on the case page, not in the audit log.",
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


def _who(move: lm.Move, holders: dict[str, list[str]]) -> list[str]:
    if move.actor.startswith("agent:"):
        return [AGENT_NAMES.get(move.actor, move.actor.split(":", 1)[1].title() + " agent")]
    return holders.get(move.actor, [])


def lifecycle_view(session: Session) -> dict[str, Any]:
    """Return the life cycle page: statuses, moves, live counts and one example case each."""
    holders = lm.persona_holders()
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

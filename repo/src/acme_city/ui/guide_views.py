"""The permit life cycle page and the judge walkthrough.

Both pages read; neither changes a record.  The life cycle comes from
:mod:`acme_city.permits.lifecycle_map`; who makes each move comes from the
grants the personas are seeded with, the same list the architecture page uses.  Every "Open as" button posts to the ordinary persona
switch, so a step runs the real screen with the real checks.

The walkthrough is a set of paths.  Each path is one journey with its own
steps, its own guided tour and its own card on the landing.  The paths are
the only source of the written steps: the submission copy of the walkthrough
is generated from them and a test fails when the two drift apart.
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

#: The case of the café path when no judge has made a copy of it.
DEFAULT_CASE_ID = "app_synth_001"

#: The placeholder in a step path that stands for the case of the café path.
CASE_PLACEHOLDER = "{case}"


@dataclass(frozen=True)
class Step:
    """One step of one path of the judge walkthrough."""

    title: str
    persona: str
    path: str
    do: str
    look_for: str
    why: str = ""


@dataclass(frozen=True)
class Path:
    """One path through the application, with its own steps and its own tour."""

    key: str
    title: str
    one_line: str
    minutes: int
    steps: tuple[Step, ...]
    story: str = ""


#: The paths of the walkthrough, in the order the page and the landing
#: list them. Apply as a resident, then Get the café open, then Run the
#: city. Before you start stays last in this list. The walkthrough draws
#: it as one row above the three tracks.
PATHS: tuple[Path, ...] = (
    Path(
        key="resident",
        title="Apply as a resident",
        one_line=(
            "A resident applies for a fence, checks the application before it "
            "is sent and follows it through the City."
        ),
        story=(
            "A resident at 400 Lantern Row wants a fence for the back yard. "
            "The case starts on Apply, before a form is filled, because the "
            "permit and the documents are not known yet."
        ),
        minutes=4,
        steps=(
            Step(
                "Apply for a permit",
                "Applicant",
                "/apply",
                "Choose Residential deck or fence, press Use a sample address and "
                "pick 400 Lantern Row, answer the questions for a 4 ft fence in "
                "the side or rear yard, attach a file for each of the two required "
                "documents, and tick the certification.",
                "The form asks only the questions that project needs, and the "
                "assistant names the published rule behind each answer.",
                "We are here because the resident asks Muse which fence permit "
                "fits, then names the project.",
            ),
            Step(
                "Check the application before it is sent",
                "Applicant",
                "/apply",
                "Press Fill in the story’s answers, press Check my application, "
                "then set the fence to 6 ft in the front yard and press Check my "
                "application again to see Must fix, or press Submit application.",
                "The findings are grouped under Must fix, Should check and "
                "Looks good, and each one names the published rule behind it.",
                "We are here because Check my application asks Muse for feedback "
                "before the application is sent.",
            ),
            Step(
                "Let the agent route the application",
                "Agent Operator",
                "/agent/intake",
                "Press Wake agent, then press the batch button, which reads "
                "Process N cases, or Process the next 20 of N when more than 20 "
                "cases are waiting.",
                "The Router line sends an application that breaks a rule to Early "
                "resolution and says which rule.",
                "We are here because document reading is a recorded Muse run "
                "(replay) and the agent sends the application to the right queue.",
            ),
            Step(
                "Track the application",
                "Applicant",
                "/apply/track",
                "Press Track application on the City of Acme website and open "
                "the application.",
                "The tracker lists both documents as received and the status of "
                "the application.",
                "We are here because the resident needs to see what the City "
                "has recorded so far.",
            ),
            Step(
                "Read the messages from the City",
                "Applicant",
                "/apply/track",
                "Open the application in the list and read Messages from the City.",
                "The tracker shows Messages from the City and says the City would "
                "also send this by email while the demonstration sends no email.",
                "We are here because the applicant is told of each decision.",
            ),
        ),
    ),
    Path(
        key="cafe",
        title="Get the café open",
        one_line=(
            "Cedarline Coffee cannot open until its permit is issued, and its "
            "owner is recorded three ways in three city systems."
        ),
        story=(
            "Cedarline Coffee cannot open until its permit is issued. The case "
            "starts with the Data Steward, because the owner is recorded three "
            "ways."
        ),
        minutes=6,
        steps=(
            Step(
                "Match the café to its owner",
                "Data Steward",
                "/steward",
                "Press Start fresh, then on Data issues press Wake if the steward "
                "assistant is asleep, or open Steward assistant in the left menu "
                "as the Agent Operator and press Wake agent, then press Prepare "
                "recommendations, press Accept recommendation on each task that "
                "carries a High pill, and approve the link of the property.",
                "Every task of the café carries a High pill and a reason in one "
                "line, Put to sleep is beside Wake once the assistant is awake, "
                "and the decision is recorded in your name.",
                "We are here because the owner is three records until a steward "
                "decides, and the Agent Operator or the Data Steward wakes the "
                "Steward assistant.",
            ),
            Step(
                "Let the agent route the case",
                "Agent Operator",
                "/agent/intake",
                "Press Wake agent, then press Process one beside the case of "
                "the café.",
                "The run shows Completed and the Router line says Ready for "
                "review in the Building area.",
                "We are here because document reading is a recorded Muse run "
                "(replay) and a person has to send the case on.",
            ),
            Step(
                "Run the checks and approve the case",
                "Permit Reviewer",
                "/queue/review",
                "Open Review queue, read Stage and Next action, where Stage for a "
                "case in checks reads Checks (3 of 6) and Next action is Ready "
                "to decide, Ready to issue, Needs "
                "checks, Fee not settled, In early resolution, or Submitted with "
                "known issues, with Ready to decide and Ready to issue first, "
                "then open the case of the café, press Start under Confirm "
                "parcel, press Start under Run application checks or Run checks "
                "again, and record the decision.",
                "The checks summary reads Checks finished or These checks already "
                "ran on this revision, Next: record the decision appears when a "
                "decision is open, the Recommendation section reads Recommend "
                "deny: with the reason when the rules fail or Passed when they "
                "do not, Needs information is prefilled, plain blockers link to "
                "the fix, Data follow-up does not block the decision, and an "
                "approval against a failed rule reads Approved as an exception "
                "to the failed rule once Exception reason is written.",
                "We are here because a person decides the case, an open parcel "
                "or identity link is Data follow-up that does not block the "
                "decision; open parcel and identity work is marked Data follow-up, "
                "and the applicant is told by email at this point "
                "while the demonstration sends no email.",
            ),
            Step(
                "Apply the café’s payment",
                "City Administrator",
                "/reconciliation",
                "Open Reconciliation, press Start under Assess application, type "
                "the reference of the café’s case and press Assess application, "
                "then press Start under Confirm allocation and press Confirm "
                "allocation, then press Start under Reconcile assessment and "
                "press Reconcile assessment.",
                "The fee from the approved schedule is assessed, the café’s "
                "payment is applied, and the balance shows 0.00, so the permit "
                "can be issued.",
                "We are here because the café paid its 150.00 fee when it "
                "applied, but the payment came in under its old finance "
                "account, so nobody could match it to the case.",
            ),
            Step(
                "Issue the permit",
                "Permit Reviewer",
                "/queue/review",
                "When the fee is settled, Stage reads Fee (5 of 6) and Next action "
                "reads Ready to issue, so open the case of the café and press "
                "Start under Issue permit.",
                "After issuance, Stage reads Issued (6 of 6) and Next action "
                "reads Issued, and the applicant is told by email at this point "
                "while the demonstration sends no email.",
                "We are here because deciding and issuing are separate, and the "
                "payer link and the fee still block issuing.",
            ),
            Step(
                "Find it as a resident",
                "",
                "/city/community",
                "Search for the permit number or the address, or press Search for "
                "my permit.",
                "The public record shows the permit, the parcel and the outcome, "
                "and never a homeowner’s name, documents or fees.",
                "We are here because a resident should find the permit without "
                "a homeowner’s name.",
            ),
        ),
    ),
    Path(
        key="city",
        title="Run the city",
        one_line=(
            "Cafés like Cedarline waited weeks, and the City asks whether to "
            "change the commercial fee or the process."
        ),
        story=(
            "Cafés like Cedarline waited weeks for a permit. Should the City "
            "change the commercial fee, or the process? The City starts with "
            "the counts, because that is where the wait shows up."
        ),
        minutes=5,
        steps=(
            Step(
                "See where the weeks went",
                "City Administrator",
                "/insight/city",
                "Open the City view and read the counts, the map and the "
                "definition beside each figure for commercial cases.",
                "Each figure has its definition printed beside it.",
                "We are here because the weeks cafés waited should show up in "
                "the counts.",
            ),
            Step(
                "Follow where the café’s time went",
                "City Administrator",
                "/ops/audit",
                "Choose Recorded permit decision in the Action filter, press "
                "Apply filters, then press View details on the top row.",
                "The actor, the time, the decision and the case it belongs to "
                "are recorded together.",
                "We are here because the counts raise where the café’s weeks "
                "went.",
            ),
            Step(
                "Ask Muse what the pattern is",
                "City Administrator",
                "/policy/scenarios",
                "Open What-if, open More details and press Ask Muse to propose "
                "so Muse summarises the pattern.",
                "Muse summarises the pattern in the policy briefing and the run "
                "decides nothing.",
                "We are here because the record shows a pattern and a person "
                "should read it before any rule changes.",
            ),
            Step(
                "Try the fee change",
                "City Administrator",
                "/policy/scenarios",
                "Open What-if, press Create a what-if, change a fee and run it "
                "over the cases.",
                "The run writes down what the fee change would do and it decides "
                "nothing.",
                "We are here because the City should see the effect of a fee "
                "change before it changes a rule.",
            ),
            Step(
                "Leave the change for a person",
                "City Administrator",
                "/policy/scenarios",
                "Draft the change and submit it for approval on Rules and fees, "
                "because a person must approve and publish it.",
                "A person must approve and publish it.",
                "We are here because the fee question is answered only when a "
                "person approves the change.",
            ),
        ),
    ),
    Path(
        key="before",
        title="Before you start",
        one_line=(
            "The video, the permit life cycle and the plans for assistants "
            "through MCP and for staff screens on a phone."
        ),
        minutes=2,
        steps=(
            Step(
                "Watch the video",
                "",
                "/select",
                "Open the video below the persona cards and play it.",
                "It runs under three minutes and every record it shows is "
                "fictional.",
                "We are here because the video shows the same journey before "
                "you walk it.",
            ),
            Step(
                "Read the permit life cycle",
                "",
                "/lifecycle",
                "Read the main path across the top, then the statuses a case "
                "can move to instead.",
                "Each move names who makes it, an agent only routes cases and a "
                "person decides and issues.",
                "We are here because each move names who makes it.",
            ),
            Step(
                "See what the City plans next",
                "",
                "/help",
                "Open Help and documentation and read the plan for assistants "
                "through MCP.",
                "The plan says plainly that none of it is built yet.",
                "We are here because the help hub holds the plan for what is "
                "not built yet.",
            ),
        ),
    ),
)

#: The path an unknown tour name opens. Take the tour, with no path named,
#: runs the three tracks in order. A name that is not a path still opens
#: the café path.
DEFAULT_PATH = "cafe"


def resolve_path(path: str, case_id: str = DEFAULT_CASE_ID) -> str:
    """Return the screen a step opens, with the case of the café path in it."""
    return path.replace(CASE_PLACEHOLDER, case_id)


def path_by_key(key: str) -> Path | None:
    """Return the path with that key, or nothing when there is no such path."""
    for path in PATHS:
        if path.key == key:
            return path
    return None


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


def path_cards(session: Session) -> list[dict[str, Any]]:
    """Return the card of every path: its title, its one line and its minutes."""
    return [
        {
            "key": path.key,
            "title": path.title,
            "one_line": path.one_line,
            "minutes": path.minutes,
        }
        for path in PATHS
    ]


def fresh_copy_context(session: Session) -> dict[str, Any]:
    """Return the state of the Start fresh button of the café path.

    The button is offered while the demonstration has room under the
    allowance of copies.  When it is not offered, the reason says why, and
    the reason is shown beside the disabled button.
    """
    from acme_city.walkthrough import judge_copy

    room = judge_copy.room_for_copies(session)
    return {
        "label": "Start fresh",
        "url": "/walkthrough/start-fresh",
        "permitted": room > 0,
        "room": room,
        "max": judge_copy.MAX_JUDGE_COPIES,
        "reason": "" if room > 0 else judge_copy.COPIES_IN_USE,
    }


#: Plain words for a stored decision outcome.  The card never shows the key.
_OUTCOME_WORDS = {
    "approved": "Approved",
    "denied": "Denied",
    "modified": "Modified",
    "information_requested": "Needs information",
    "approved_with_conditions": "Approved with conditions",
}


def permit_card(session: Session, case_id: str) -> dict[str, str] | None:
    """Return the issued permit of one case, for the tour card.

    The card names the permit, the address, the parcel, the outcome, the
    conditions and the date.  It leaves out names, documents and fees.
    """
    from acme_city.persistence.models.registry import Parcel

    row = session.execute(
        select(permit.Permit)
        .where(permit.Permit.application_id == case_id)
        .order_by(permit.Permit.issued_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    site = session.execute(
        select(permit.ApplicationSite)
        .where(permit.ApplicationSite.application_id == case_id)
        .order_by(permit.ApplicationSite.is_primary.desc())
        .limit(1)
    ).scalar_one_or_none()
    address = ""
    parcel_number = ""
    if site is not None:
        address = (site.submitted_address_text or "").strip()
        if site.parcel_id:
            found = session.execute(
                select(Parcel).where(
                    (Parcel.id == site.parcel_id) | (Parcel.parcel_id == site.parcel_id)
                )
            ).scalars().first()
            if found is not None:
                parcel_number = found.source_parcel_number
    decision = session.get(permit.Decision, row.decision_id) if row.decision_id else None
    outcome_key = decision.outcome if decision is not None else ""
    conditions: list[str] = []
    if decision is not None and decision.conditions:
        conditions = [str(item).strip() for item in decision.conditions if str(item).strip()]
    when = row.issued_at
    date = f"{when:%b} {when.day}, {when.year}" if when is not None else ""
    place = address or parcel_number
    number = row.permit_number
    return {
        "title": "Permit issued",
        "number": number,
        "address": address,
        "parcel": parcel_number,
        "outcome": _OUTCOME_WORDS.get(outcome_key, outcome_key.replace("_", " ")),
        "conditions": "; ".join(conditions) if conditions else "none recorded",
        "date": date,
        "search_label": "Search for my permit",
        "search_href": "/city/community?q=" + number,
        "search_line": f"Search for permit {number} or {place}.",
    }


def walkthrough_view(session: Session, *, case_id: str = DEFAULT_CASE_ID) -> dict[str, Any]:
    """Return the judge walkthrough: the paths, their steps and the actor each step switches to."""
    ids = _persona_ids(session)
    reference = ""
    if case_id != DEFAULT_CASE_ID:
        row = session.execute(
            select(permit.Application.source_application_number).where(
                permit.Application.id == case_id
            )
        ).scalar_one_or_none()
        reference = str(row or "")
    return {
        "case_id": case_id,
        "default_case_id": DEFAULT_CASE_ID,
        "has_copy": case_id != DEFAULT_CASE_ID,
        "copy_reference": reference,
        "fresh": fresh_copy_context(session),
        "paths": [
            {
                "key": path.key,
                "title": path.title,
                "one_line": path.one_line,
                "story": path.story,
                "minutes": path.minutes,
                "steps": [
                    {
                        "number": number,
                        "title": step.title,
                        "persona": step.persona,
                        "actor_id": ids.get(step.persona, "") if step.persona else "",
                        "path": resolve_path(step.path, case_id),
                        "do": step.do,
                        "look_for": step.look_for,
                        "why": step.why,
                    }
                    for number, step in enumerate(path.steps, start=1)
                ],
            }
            for path in PATHS
        ],
    }


#: The heading of the submission copy of the walkthrough.
DOC_TITLE = "City of Acme permits: judge walkthrough"

#: The introduction of the submission copy of the walkthrough.
DOC_INTRO = (
    "Four paths, each one independent, and each with its own guided tour. The "
    "café path offers a fresh copy of the café case, so every judge walks a "
    "case of their own. Every record in the app is fictional, and the app "
    "issues no real permit."
)

#: The instruction of the submission copy of the walkthrough.
DOC_HOWTO = (
    "Start at https://acme-city-permits.onrender.com/walkthrough. The same "
    "steps are on that page, and the button on each step switches to the right "
    "persona and opens the screen. To run the app on a local computer instead, "
    "follow `repo/USER_TEST_GUIDE.md`. From `repo/`, run `uv run python "
    "scripts/prepare_user_test.py --mode demo-synthetic` and then `uv run python "
    "scripts/start_demo.py --host 127.0.0.1 --port 8266`, and open "
    "http://127.0.0.1:8266/walkthrough. The demo-synthetic mode loads the "
    "synthetic year of permits that the City view needs."
)

#: The note of the submission copy of the walkthrough.
DOC_LIFECYCLE = (
    "The permit life cycle behind these steps is at `/lifecycle`: every status, "
    "every move, and who makes each move."
)


def walkthrough_markdown() -> str:
    """Return the submission copy of the walkthrough.

    The document is generated from the paths, so the words of the page and the
    words of the document cannot drift apart.
    """
    lines: list[str] = [
        f"# {DOC_TITLE}",
        "",
        DOC_INTRO,
        "",
        DOC_HOWTO,
        "",
        DOC_LIFECYCLE,
        "",
    ]
    for path in PATHS:
        lines.append(f"## {path.title}")
        lines.append("")
        lines.append(path.one_line)
        lines.append("")
        if path.story:
            lines.append(path.story)
            lines.append("")
        lines.append(f"{len(path.steps)} steps, about {path.minutes} minutes.")
        lines.append("")
        for number, step in enumerate(path.steps, start=1):
            lines.append(f"### {number}. {step.title}")
            lines.append("")
            if step.persona:
                lines.append(f"As **{step.persona}**, open `{step.path}`.")
            else:
                lines.append(f"Open `{step.path}`.")
            lines.append("")
            if step.why:
                lines.append(f"- Why: {step.why}")
            lines.append(f"- Do: {step.do}")
            lines.append(f"- Look for: {step.look_for}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = [
    "CASE_PERSONA",
    "CASE_PLACEHOLDER",
    "DEFAULT_CASE_ID",
    "DEFAULT_PATH",
    "DOC_HOWTO",
    "DOC_INTRO",
    "DOC_LIFECYCLE",
    "DOC_TITLE",
    "MAIN_PATH",
    "PATHS",
    "Path",
    "Step",
    "lifecycle_view",
    "path_by_key",
    "resolve_path",
    "walkthrough_markdown",
    "walkthrough_view",
]

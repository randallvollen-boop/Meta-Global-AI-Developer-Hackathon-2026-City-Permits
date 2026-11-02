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
        minutes=3,
        steps=(
            Step(
                "Apply for a permit",
                "Applicant",
                "/apply",
                "Choose Residential deck or fence, type 400 Lantern Row, answer "
                "the questions for a 6 ft fence in the front yard, attach a file "
                "for each of the two required documents and tick the "
                "certification.",
                "The form asks only the questions that project needs, and the "
                "assistant names the published rule behind each answer.",
                "We are here because the resident asks Muse which fence permit "
                "fits, then names the project.",
            ),
            Step(
                "Check the application before it is sent",
                "Applicant",
                "/apply",
                "Press Check my application, then change the 6 ft front yard "
                "fence to 4 ft and press Submit application, or press Submit "
                "anyway and write why you send it now.",
                "The findings are grouped under Must fix, Should check and "
                "Looks good, and each one names the published rule behind it.",
                "We are here because Check my application asks Muse for feedback "
                "before the application is sent.",
            ),
            Step(
                "Let the agent route the application",
                "Agent Operator",
                "/agent/intake",
                "Press Wake agent, then press Process the next 20 cases.",
                "The Router line sends an application that breaks a rule to Early "
                "resolution and says which rule.",
                "We are here because Muse reads the documents and the agent "
                "sends the application to the right queue.",
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
                "Press Start fresh, then open Data issues, press Prepare "
                "recommendations, press Accept recommendation on each task that "
                "carries a High pill and approve the link of the property.",
                "Every task of the café carries a High pill and a reason in one "
                "line, and the decision is recorded in your name.",
                "We are here because the owner is three records until a steward "
                "decides, and Explain with Muse only rewrites the reason.",
            ),
            Step(
                "Let the agent route the case",
                "Agent Operator",
                "/agent/intake",
                "Press Wake agent, then press Process one beside the case of "
                "the café.",
                "The run shows Completed and the Router line says Ready for "
                "review in the Building area.",
                "We are here because Muse has read the documents and a person "
                "has to send the case on.",
            ),
            Step(
                "Run the checks and approve the case",
                "Permit Reviewer",
                "/queue/review",
                "Open the case of the café from the Review queue, press Start "
                "under Confirm parcel on the People and organizations tab and "
                "submit it, press Start under Run application checks and submit "
                "it, then press Start under Record review decision, choose "
                "Approve and write your reason.",
                "The rule results show Passed and the decision is recorded in "
                "the case history with your reason.",
                "We are here because the identity is clear, so a person can "
                "decide the case.",
            ),
            Step(
                "Apply the café's payment",
                "City Administrator",
                "/reconciliation",
                "Open Reconciliation, press Start under Assess application, type "
                "the reference of the café's case and press Assess application, "
                "then press Start under Confirm allocation and press Confirm "
                "allocation, then press Start under Reconcile assessment and "
                "press Reconcile assessment.",
                "The fee from the approved schedule is assessed, the café's "
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
                "Open the case of the café again and press Start under Issue "
                "permit.",
                "The permit number appears on the case and the issued artifact "
                "opens.",
                "We are here because deciding and issuing are separate.",
            ),
            Step(
                "Find it as a resident",
                "",
                "/city/community",
                "Search for the permit number on the City of Acme website.",
                "The public record shows the permit, the parcel and the outcome, "
                "and never a homeowner's name, documents or fees.",
                "We are here because a resident should find the permit without "
                "a homeowner's name.",
            ),
        ),
    ),
    Path(
        key="city",
        title="Run the city",
        one_line=(
            "The record of the café decision, the City at a glance and a what "
            "if on a fee change."
        ),
        story=(
            "The café permit is on the public record. The City starts with the "
            "audit log, because it has to see who decided."
        ),
        minutes=3,
        steps=(
            Step(
                "Check the record of the decision",
                "City Administrator",
                "/ops/audit",
                "Choose Recorded permit decision in the Action filter, press "
                "Apply filters, then press View details on the top row.",
                "The actor, the time, the decision and the case it belongs to "
                "are recorded together.",
                "We are here because the decision has to stay tied to the "
                "person who made it.",
            ),
            Step(
                "See the city at a glance",
                "City Administrator",
                "/insight/city",
                "Filter the City view by permit type and outcome.",
                "The map, the counts and the definition printed beside each "
                "figure.",
                "We are here because the City needs the counts and the map with "
                "a definition beside each figure.",
            ),
            Step(
                "Try a what if on a fee change",
                "City Administrator",
                "/policy/scenarios",
                "Open What-if, save a new what-if, change a fee and run it over "
                "the cases.",
                "The run writes down what the change would do and it decides "
                "nothing.",
                "We are here because Muse writes the briefing for a fee change, "
                "and the run decides nothing.",
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
        "reason": (
            ""
            if room > 0
            else (
                f"the demonstration already holds {judge_copy.MAX_JUDGE_COPIES} copies of "
                "the café case, the whole allowance"
            )
        ),
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

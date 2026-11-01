"""The view model of the applicant help panel.

The panel shows three things and nothing else:

* the **conversation** of the applicant, with the question, the label of the
  answer and the citations of every passage the answer quoted;
* the **timing figures** of the permit type — the configured service target
  and the current backlog of the review area — as two separate figures, each
  with its own definition and the time it was read.  The two are never added
  together: no completion date is computed and no queue position is claimed;
* the **next steps** open to this applicant, derived from the grants the
  server holds for them, never from the text of an answer.

Every conversation on the panel belongs to the applicant who opened it.  A
conversation of another applicant is not found.
"""
# REQUIRES: UX-02, UX-03, PER-04, SEC-03
# The panel shows the applicant's own conversation, two separate timing
# figures with their definitions, and the next steps the applicant's own
# grants open to them.

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.applicant_help.service import ApplicantHelpService
from acme_city.applicant_help.sources import applicant_next_steps as _applicant_next_steps
from acme_city.applicant_portal.permits_view import short_date
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.persistence.models import help as help_models
from acme_city.persistence.models import model_run, permit

#: The statuses a case holds while it is with the reviewer.
#:
#: The backlog figure counts exactly these statuses.  The panel says which
#: ones they are.
REVIEW_BACKLOG_STATUSES: tuple[str, ...] = ("ready_for_review", "under_review")

#: The panels the help assistant is offered on.
#:
#: ``contact`` is the contact page of the City website, where the applicant
#: asks a person at the City instead of the assistant.
PLACEMENTS: tuple[str, ...] = ("chooser", "form", "track", "contact")

#: The plain words of the backlog statuses.
STATUS_WORDS: dict[str, str] = {
    "ready_for_review": "ready for review",
    "under_review": "under review",
}


def _type_row(session: Session, permit_type_key: str) -> permit.PermitType | None:
    """Return the stored configuration of one permit type."""
    if not permit_type_key:
        return None
    return session.execute(
        select(permit.PermitType).where(
            permit.PermitType.key == permit_type_key,
            permit.PermitType.active.is_(True),
        )
    ).scalar_one_or_none()


def _application(session: Session, application_id: str) -> permit.Application | None:
    """Return one application."""
    if not application_id:
        return None
    return session.get(permit.Application, application_id)


def review_area_backlog(session: Session, review_area: str) -> int:
    """Return the number of cases in a review area that are with the reviewer.

    The count is the City-wide backlog of the area.  It carries no applicant
    and no case: it is a number, and the panel says what it counts.
    """
    if not review_area:
        return 0
    count = session.execute(
        select(func.count())
        .select_from(permit.Application)
        .where(
            permit.Application.review_area == review_area,
            permit.Application.status.in_(REVIEW_BACKLOG_STATUSES),
        )
    ).scalar_one()
    return int(count or 0)


def timing_figures(
    session: Session,
    *,
    permit_type_key: str = "",
    review_area: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the two timing figures of the panel.

    The configured service target and the current backlog of the review area
    are two separate figures.  They are never added together and neither one
    is turned into a date.
    """
    moment = now or utc_now()
    type_row = _type_row(session, permit_type_key)
    area = review_area or (type_row.review_area if type_row is not None else "")
    figures: dict[str, Any] = {
        "as_of": moment.isoformat(),
        "permit_type_label": type_row.label if type_row is not None else "",
        "service_target": None,
        "review_area": None,
        "note": (
            "The service target and the backlog are two different figures. "
            "Neither one is a completion date for your application."
        ),
    }
    if type_row is not None:
        figures["service_target"] = {
            "days": int(type_row.service_target_days or 0),
            "definition": (
                "This is the fictional number of days the City aims to review a "
                "case of this type in. It is a target the City works to. It makes "
                "no promise about your application."
            ),
        }
    if area:
        figures["review_area"] = {
            "name": area,
            "count": review_area_backlog(session, area),
            "statuses": [STATUS_WORDS.get(status, status) for status in REVIEW_BACKLOG_STATUSES],
            "definition": (
                "These are the cases in this review area that are ready for "
                "review or under review right now."
            ),
        }
    return figures


def applicant_next_steps(
    session: Session, actor: ActorContext, application: permit.Application | None
) -> list[str]:
    """Return the steps that are open to this applicant right now.

    The steps come from the grants the server holds for the actor, never from
    the text of an answer.
    """
    return _applicant_next_steps(session, actor, application)


def applicant_requests(
    session: Session, actor: ActorContext, limit: int = 5
) -> list[dict[str, Any]]:
    """Return the requests this applicant sent to the City, newest first.

    A request is the applicant's own: the list never shows the request of
    another applicant, and it never shows the text of a conversation the
    applicant did not escalate.
    """
    rows = session.execute(
        select(help_models.HelpRequest)
        .where(help_models.HelpRequest.applicant_actor_id == actor.actor_id)
        .order_by(help_models.HelpRequest.created_at.desc(), help_models.HelpRequest.id)
        .limit(limit)
    ).scalars().all()
    return [
        {
            "request_id": row.id,
            "status": row.status,
            "created_on": short_date(row.created_at),
            "question": row.question,
            "reply": row.reply or "",
        }
        for row in rows
    ]


def run_view(session: Session, turn: Any, label: str) -> dict[str, Any] | None:
    """Return the source line of the model run behind a turn, if there is one.

    The shape is the one ``components/muse_source.html`` renders: the mode, the
    source label, the usage and the latency.  The run is read only when it
    belongs to the very turn being shown, so a turn never shows another run.
    """
    answer = dict(turn.answer or {})
    run_id = str(answer.get("model_run_id") or "")
    if not run_id or turn.mode not in ("replay", "live"):
        # A turn the validation refused shows the deterministic rule text; it
        # carries no model source line, because no model answer is shown.
        return None
    row = session.get(model_run.ModelRun, run_id)
    if row is None:
        return None
    refs = row.input_refs if isinstance(row.input_refs, dict) else {}
    if str(refs.get("turn_id") or "") != str(turn.id):
        return None
    usage = row.usage if isinstance(row.usage, dict) else {}
    return {
        "run_id": row.id,
        "mode": row.mode,
        "source_label": label,
        "usage": dict(usage),
        "latency_ms": row.latency_ms,
    }


def turn_view(turn: Any, config: Any = None) -> dict[str, Any]:
    """Return the view of one turn of the conversation.

    ``config`` is the help configuration.  When it is given, the view also
    carries the sentence of a refusal, so that the panel and the script show
    the same words for a turn the assistant declined.
    """
    answer = dict(turn.answer or {})
    view = {
        "turn_id": turn.id,
        "question": turn.question,
        "created_at": turn.created_at.isoformat() if turn.created_at else "",
        "mode": turn.mode,
        "outcome": turn.outcome,
        "label": str(answer.get("label", "")),
        "paragraphs": list(answer.get("paragraphs") or []),
        "cannot_answer": bool(answer.get("cannot_answer")),
        "reason": str(answer.get("reason", "")),
        "sources": list(turn.sources or []),
        "declined_text": "",
    }
    if config is not None:
        view["declined_text"] = (
            config.refusal_text(view["reason"]) if view["outcome"] == "unanswerable" else ""
        )
    return view


def _turn_with_run(session: Session, turn: Any, config: Any) -> dict[str, Any]:
    """Return the view of a turn with the source line of its run."""
    view = turn_view(turn, config)
    view["run"] = run_view(session, turn, view["label"])
    return view


def panel_context(
    session: Session,
    actor: ActorContext,
    *,
    service: ApplicantHelpService,
    placement: str,
    permit_type_key: str = "",
    application_id: str = "",
    conversation_id: str = "",
    reference: str = "",
) -> dict[str, Any]:
    """Return the context of the help panel.

    Args:
        session: The open session.
        actor: The acting applicant.
        service: The help service.
        placement: The panel the applicant is on.
        permit_type_key: The permit type the panel knows about.
        application_id: The application the panel knows about.
        conversation_id: The conversation the panel shows, when there is one.
        reference: The reference of the application, for the return path.

    Returns:
        The context the panel template renders.
    """
    config = service.config
    conversation = service.conversation_for(actor, conversation_id)
    every_turn = service.turns(conversation) if conversation is not None else []
    # The conversation is kept whole; the panel shows the last turns of it,
    # and says how many earlier ones there are.
    turns = every_turn[-config.history_turns :] if every_turn else []
    earlier = len(every_turn) - len(turns)
    requests = service.help_requests(conversation) if conversation is not None else []
    application = _application(session, application_id)
    if application is not None:
        application_id = application.id
        type_row = session.get(permit.PermitType, application.permit_type_id)
        if type_row is not None:
            permit_type_key = type_row.key
    review_area = ""
    if application is not None:
        review_area = application.review_area or ""
    type_row = _type_row(session, permit_type_key)
    if not review_area and type_row is not None:
        review_area = type_row.review_area or ""
    preserved: dict[str, str] = {}
    if conversation is not None:
        preserved["help"] = conversation.id
    if reference:
        preserved["ref"] = reference
    return {
        "help_notice": config.notice,
        "help_placement": placement,
        "help_conversation_id": conversation.id if conversation is not None else "",
        "help_conversation_version": conversation.version if conversation is not None else 0,
        "help_turns": [_turn_with_run(session, turn, config) for turn in turns],
        "help_earlier_turns": earlier,
        "help_requests": [
            {
                "request_id": row.id,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "reply": row.reply or "",
            }
            for row in requests
        ],
        "help_last_question": turns[-1].question if turns else "",
        "help_escalation": service.escalation_state(conversation),
        "help_demo_mode": service.demo_mode,
        "help_suggestions": [
            {"id": identifier, "text": text}
            for identifier, text in config.questions(demo_mode=service.demo_mode)
        ],
        "help_max_length": config.max_message_length,
        "help_no_match_text": config.no_match_text,
        "help_type_key": permit_type_key,
        "help_application_id": application_id,
        "help_reference": reference,
        "help_query": urlencode(preserved),
        "help_timing": timing_figures(
            session,
            permit_type_key=permit_type_key,
            review_area=review_area,
        ),
        "help_next_steps": applicant_next_steps(session, actor, application),
    }


__all__ = [
    "PLACEMENTS",
    "REVIEW_BACKLOG_STATUSES",
    "STATUS_WORDS",
    "applicant_next_steps",
    "applicant_requests",
    "panel_context",
    "review_area_backlog",
    "run_view",
    "timing_figures",
    "turn_view",
]

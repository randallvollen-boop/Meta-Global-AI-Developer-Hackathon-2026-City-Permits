"""The Data Steward screens.

Routes:

* ``GET /steward``                            Data issues, the steward's queue
* ``GET /steward/issues/{kind}/{id}``         one focused case
* ``GET /masters``                            Master records, four tabs
* ``GET /masters/{party_id}``                 one record profile
* ``GET /applicants``                         the People & organizations tab
* ``GET /applicants/{party_id}``              one record profile
* ``GET /source-records``                     the source-record catalogue
* ``GET /activity``                           recorded steward decisions
* ``GET /queue/intake``                       the intake queue
* ``GET /queue/early-resolution``             the early-resolution board

``/applicants`` is rendered as the People & organizations tab, so its address,
its test ids and ``/applicants/{id}`` keep working.  Every screen is guarded by
the grants in ``view_models.SCREEN_PERMISSIONS``, the same predicate the
navigation uses.  ``HANDLERS`` holds the lane's interface actions, which
``ui/router.py`` merges into ``ACTION_HANDLERS``.
"""
# REQUIRES: UX-01, UX-02, UX-03, MDM-02, SEC-01

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.persistence.models import registry
from acme_city.permits import queues
from acme_city.ui import (
    agent_views,
    steward_assist_views,
    steward_guide,
    steward_queue_views,
    steward_views,
    view_models,
)
from acme_city.ui.router import (
    ActionContext,
    Outcome,
    _guard,
    error_response,
    page_context,
    render,
    safe_next,
    ui_actor,
)

router = APIRouter(tags=["steward"])

#: Where each collection's values come from (for the source summary).
COLLECTION_SOURCES = {
    "people": ("permitting", "applicant_profiles"),
    "properties": ("gis", "parcel_register"),
    "licenses": ("erp_finance", "business_licensing_register"),
    "registrations": ("permitting", "contractor_register"),
}


def _role_reasons(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Say "Your role cannot do this." where only the grant is missing."""
    for item in actions:
        if not item["permitted"] and "does not hold the" in str(item["reason"]):
            item["reason"] = "Your role cannot do this."
    return actions


def _may_read_source(session: Session, actor: ActorContext) -> bool:
    return any(
        view_models.holds_grant(session, actor, permission, domain)
        for permission, domain in steward_views.SOURCE_GRANTS
    )


#: The guide screen of each kind of focused case.  A kind with no saved words
#: of its own reads the plain "no guidance" answer.
CASE_GUIDE_SCREENS = {
    "link": "match_case",
    "parcel": "parcel_case",
    "case": "source_correction",
    "linked": "match_case",
}


def _guide(screen: str, *, evidence: tuple[str, ...] = ()) -> Any:
    """Build saved guidance from facts the screen already shows."""
    return steward_guide.build(
        steward_guide.GuideContext(screen=screen, evidence=evidence)
    )


def _tab_counts(session: Session, actor: ActorContext) -> dict[str, int]:
    visible = {party.id for party in view_models.visible_parties(session, actor)}
    parcels = session.execute(select(func.count()).select_from(registry.Parcel)).scalar_one()
    by_type: dict[str, int] = {"business_license": 0, "contractor_registration": 0}
    for holder, kind in session.execute(
        select(registry.Credential.holder_party_id, registry.Credential.credential_type)
    ).all():
        if holder in visible and kind in by_type:
            by_type[kind] += 1
    return {
        "people": len(visible),
        "properties": int(parcels),
        "licenses": by_type["business_license"],
        "registrations": by_type["contractor_registration"],
    }


def _collections_page(
    request: Request,
    session: Session,
    resolved: ActorContext,
    *,
    tab: str,
    kind: str,
    q: str,
    page: int,
    base_path: str,
) -> Any:
    may_masters = view_models.may_open_screen(session, resolved, "masters")
    allowed = [key for key, _ in steward_views.MASTER_TABS if key == "people" or may_masters]
    if tab not in allowed:
        tab = "people"
    counts = _tab_counts(session, resolved)
    tabs = [
        {
            "key": key,
            "label": label,
            "count": counts[key],
            "active": key == tab,
            "href": "/masters" if key == "people" else f"/masters?tab={key}",
        }
        for key, label in steward_views.MASTER_TABS
        if key in allowed
    ]
    if not may_masters:
        tabs[0]["href"] = "/applicants"
    if tab == "people":
        collection = steward_views.people_collection(
            session, resolved, kind=kind, query=q, page=page, base_path=base_path
        )
    elif tab == "properties":
        collection = steward_views.properties_collection(session, resolved, query=q, page=page)
    elif tab == "licenses":
        collection = steward_views.credentials_collection(
            session, resolved, credential_type="business_license", query=q, page=page
        )
    else:
        collection = steward_views.credentials_collection(
            session, resolved, credential_type="contractor_registration", query=q, page=page
        )
    system_id, dataset = COLLECTION_SOURCES[tab]
    summary = steward_views.source_summary(session, system_id, dataset)
    summary["may_open"] = _may_read_source(session, resolved)
    title = "People & organizations" if base_path == "/applicants" else "Master records"
    context = page_context(
        request,
        session,
        resolved,
        screen="masters" if may_masters else "applicants",
        title=title,
        tab=tab,
        tabs=tabs,
        collection=collection,
        collection_path=base_path if tab == "people" else "/masters",
        summary=summary,
        help_screen="masters" if may_masters else "applicants",
        guide=_guide("master_collection"),
        quiet_feedback=True,
    )
    return render(request, "masters.html", context)


@router.get("/masters", operation_id="ui_masters")
def ui_masters(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "people",
    kind: str = "all",
    q: str = "",
    page: int = 1,
) -> Any:
    """Show the master records, one collection at a time."""
    resolved, refused = _guard(request, session, actor, "masters")
    if refused is not None:
        return refused
    return _collections_page(
        request, session, resolved, tab=tab, kind=kind, q=q, page=page, base_path="/masters"
    )


@router.get("/applicants", operation_id="ui_applicants")
def ui_applicants(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    kind: str = "all",
    q: str = "",
    page: int = 1,
) -> Any:
    """Show the People & organizations tab (the shared applicant view)."""
    resolved, refused = _guard(request, session, actor, "applicants")
    if refused is not None:
        return refused
    return _collections_page(
        request, session, resolved, tab="people", kind=kind, q=q, page=page, base_path="/applicants"
    )


def _profile_page(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    party_id: str,
    *,
    screen: str,
    view: str,
) -> Any:
    resolved, refused = _guard(request, session, actor, screen)
    if refused is not None:
        return refused
    profile = steward_views.record_profile(session, resolved, party_id)
    if not profile:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title=(
                "That applicant record is not available to you"
                if screen == "applicants"
                else "That master record is not available to you"
            ),
            message=(
                "The record does not exist or it is outside the record scope of "
                "your persona."
            ),
            code="not_found",
            back="/applicants" if screen == "applicants" else "/masters",
        )
    detail = profile["detail"]
    if screen == "masters":
        master = view_models.master_detail(session, resolved, party_id)
        actions = _role_reasons(
            view_models.allowed_actions_for(session, resolved, "masters", party_id, master)
        )
        accounts = master["accounts"]
    else:
        actions = _role_reasons(
            view_models.allowed_actions_for(session, resolved, "applicants", party_id, detail)
        )
        accounts = []
    nav_screen = "masters" if view_models.may_open_screen(session, resolved, "masters") else "applicants"
    if view not in ("overview", "sources", "history"):
        view = "overview"
    base = f"/{screen}/{party_id}"
    guide = _guide(
        "record_profile", evidence=tuple(item["label"] for item in detail["evidence"]),
    )
    if view != "overview":
        # The identity and the related records are on the overview only, so the
        # guide holds no link to them on the other views.
        guide = replace(guide, links=())
    context = page_context(
        request,
        session,
        resolved,
        screen=nav_screen,
        title=profile["name"],
        profile=profile,
        detail=detail,
        profile_view=view,
        profile_tabs=[
            {"key": key, "label": label, "active": key == view, "href": base if key == "overview" else f"{base}?view={key}"}
            for key, label in (("overview", "Overview"), ("sources", "Sources"), ("history", "History"))
        ],
        accounts=accounts,
        responsibility=profile["responsibility"],
        evidence=detail["evidence"],
        model_runs=[],
        history=profile["history"],
        actions=actions,
        guide=guide,
        denied_action_explanations=view_models.denied_action_explanations(actions),
        back_href="/masters" if nav_screen == "masters" else "/applicants",
        may_read_source=_may_read_source(session, resolved),
        help_screen="masters" if nav_screen == "masters" else "applicants",
        quiet_feedback=True,
    )
    return render(request, "record_profile.html", context)


@router.get("/applicants/{party_id}", operation_id="ui_applicant_detail")
def ui_applicant_detail(
    party_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    view: str = "overview",
) -> Any:
    """Show one record profile: overview, sources and history."""
    return _profile_page(request, session, actor, party_id, screen="applicants", view=view)


@router.get("/masters/{party_id}", operation_id="ui_master_detail")
def ui_master_detail(
    party_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    view: str = "overview",
) -> Any:
    """Show one business or contractor record profile."""
    return _profile_page(request, session, actor, party_id, screen="masters", view=view)


@router.get("/steward", operation_id="ui_steward_review")
def ui_steward_review(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    filter: str = "needs_review",
    q: str = "",
    record_type: str = "",
    source: str = "",
    page: int = 1,
) -> Any:
    """Show the work queue: the search, the filters, the views and the rows.

    Every value arrives in the address of the request, so a steward can
    bookmark a queue, send it to a colleague and come back to it from a
    case with the same search, the same filters and the same page.
    """
    resolved, refused = _guard(request, session, actor, "steward")
    if refused is not None:
        return refused
    return_path = str(request.url.path)
    if request.url.query:
        return_path = f"{return_path}?{request.url.query}"
    queue = steward_views.data_issues(
        session,
        resolved,
        filter_key=filter,
        query=q,
        record_type=record_type,
        source=source,
        page=page,
        return_path=return_path,
    )
    # The parcel decisions are made inside each focused case; the queue page
    # keeps the generic "work from a source record" forms.
    actions = _role_reasons(
        view_models.allowed_actions_for(session, resolved, "steward", None, {"parcel_proposals": []})
    )
    feedback = view_models.feedback(session, resolved)
    confirmation = ""
    if feedback and feedback.get("outcome") == "accepted" and feedback.get("occurred_at"):
        age = datetime.now(UTC) - datetime.fromisoformat(str(feedback["occurred_at"]))
        if age < timedelta(minutes=10) and str(feedback.get("action", "")).startswith("ui.registry"):
            confirmation = str(feedback.get("reason") or "")
    # The control of the steward assistant.  The button asks the assistant to
    # prepare the work of the tasks of this view; it never runs on a timer.
    assistant = steward_assist_views.assistant_state(session, resolved)
    assistant["tasks"] = next(
        (item["count"] for item in queue["filters"] if item["key"] == "needs_review"), 0
    )
    assistant["bound"] = steward_assist_views.MAX_TASKS_PER_PRESS
    # The batch the steward may accept.  The queue shows how many
    # recommendations it holds; the preview names them.
    batch = steward_assist_views.batch_state(
        session, resolved, with_items=False, settings=request.app.state.settings
    )
    # The agreement figure: the share of the recommendations the steward
    # accepted unchanged in the last seven days.
    agreement = steward_assist_views.agreement_figure(session)
    context = page_context(
        request,
        session,
        resolved,
        screen="steward",
        title="Data issues",
        confirmation=confirmation,
        queue=queue,
        actions=actions,
        assistant=assistant,
        batch=batch,
        agreement=agreement,
        queue_path=return_path,
        guide=_guide("queue"),
        denied_action_explanations=view_models.denied_action_explanations(actions),
        quiet_feedback=True,
    )
    return render(request, "steward_review.html", context)


@router.get("/steward/batch", operation_id="ui_steward_batch")
def ui_steward_batch(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the preview of the recommendations a batch would accept.

    The preview names every item the batch would accept and nothing else.
    Nothing is accepted before the steward confirms this list, and an item
    that changed since the list was made is skipped and named.
    """
    resolved, refused = _guard(request, session, actor, "steward")
    if refused is not None:
        return refused
    batch = steward_assist_views.batch_state(
        session, resolved, settings=request.app.state.settings
    )
    if not batch["may_batch"]:
        return error_response(
            request,
            session,
            resolved,
            status_code=403,
            title="This screen is outside your grants",
            message=steward_assist_views.BATCH_GRANT_NOTE,
            code="permission_denied",
            back="/steward",
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="steward",
        title="Accept the high-confidence recommendations",
        batch=batch,
        guide=_guide("queue"),
    )
    return render(request, "steward_batch.html", context)


@router.get("/steward/issues/{kind}/{item_id}", operation_id="ui_steward_case")
def ui_steward_case(
    kind: str,
    item_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    back: str = "",
    candidate: str = "",
) -> Any:
    """Show one focused case: the problem, why it matters, the comparison, the evidence, the preview and the result.

    The ``candidate`` value names the master record the steward chose in the
    chooser of the case.  Choosing a record only changes what the page shows;
    it never changes a link.
    """
    resolved, refused = _guard(request, session, actor, "steward")
    if refused is not None:
        return refused
    case = steward_views.focused_case(
        session,
        resolved,
        kind,
        item_id,
        selected_id=candidate,
        settings=request.app.state.settings,
    )
    if not case:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That data issue was not found",
            message="The issue does not exist, or it has been resolved and removed from the queue.",
            code="not_found",
            back="/steward",
        )
    feedback = view_models.feedback(session, resolved)
    confirmation = ""
    if feedback and feedback.get("outcome") == "accepted" and feedback.get("target_id") in case["target_ids"]:
        confirmation = str(feedback.get("reason") or "")
    # The case keeps the address of the queue it was opened from, so an action
    # that returns to the case returns to the same search, filters and page.
    case_path = str(request.url.path)
    if request.url.query:
        case_path = f"{case_path}?{request.url.query}"
    context = page_context(
        request,
        session,
        resolved,
        screen="steward",
        title=f"Data issue: {case['title']}",
        case=case,
        guide=_guide(
            CASE_GUIDE_SCREENS.get(kind, kind),
            evidence=tuple(case["evidence"]),
        ),
        case_path=case_path,
        confirmation=confirmation,
        back_href=safe_next(back, "/steward"),
        help_screen="steward",
        quiet_feedback=True,
    )
    return render(request, "steward_case.html", context)


@router.get("/source-records", operation_id="ui_source_records")
def ui_source_records(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    system: str = "",
    q: str = "",
    page: int = 1,
    link_state: str = "",
) -> Any:
    """Show the source-record catalogue.

    The search, the source filter and the link state filter are read from the
    address of the request, so the catalogue can be bookmarked and shared.
    """
    resolved, refused = _guard(request, session, actor, "source_records")
    if refused is not None:
        return refused
    catalogue = steward_views.source_records(
        session, resolved, system=system, query=q, page=page, link_state=link_state
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="source_records",
        title="Source records",
        catalogue=catalogue,
        help_screen="source_records",
        guide=_guide("source_record"),
        quiet_feedback=True,
    )
    return render(request, "source_records.html", context)


@router.get("/activity", operation_id="ui_activity")
def ui_activity(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    page: int = 1,
) -> Any:
    """Show the recorded steward decisions and changes."""
    resolved, refused = _guard(request, session, actor, "activity")
    if refused is not None:
        return refused
    context = page_context(
        request,
        session,
        resolved,
        screen="activity",
        title="Activity",
        activity=steward_views.activity(session, resolved, page=page),
        help_screen="activity",
        guide=_guide("activity"),
        quiet_feedback=True,
    )
    return render(request, "activity.html", context)


@router.get("/queue/intake", operation_id="ui_intake_queue")
def ui_intake_queue(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "active",
    q: str = "",
    channel: str = "",
    permit_type: str = "",
    priority: str = "",
    owner: str = "",
    sort: str = "age",
) -> Any:
    """Show the intake queue of the Data Steward."""
    resolved, refused = _guard(request, session, actor, "intake_queue")
    if refused is not None:
        return refused
    queue = queues.intake_queue(
        session,
        resolved,
        tab=tab,
        query=q,
        channel=channel,
        permit_type=permit_type,
        priority=priority,
        owner=owner,
        sort=sort,
    )
    # The next step of every case is a short summary of the state the server
    # recorded, so a reader sees what happens next before the detailed signals.
    for row in queue["rows"]:
        row["next_step"] = steward_queue_views.intake_next_step(row)
    context = page_context(
        request,
        session,
        resolved,
        screen="intake_queue",
        title="Intake queue",
        queue=queue,
        agent_awake=agent_views.agent_state(session, "intake")["mode"] == "awake",
        guide=_guide("incoming"),
        # The processing control is a gate of two grants: the execution grant
        # that names the action and the run grant of the intake agent.  The
        # person who may run the agent is the person who may process the
        # selected cases; a persona that may only read the queue sees the
        # locked control and the reason it is locked.
        can_process=(
            view_models.holds_grant(
                session, resolved, "permit.intake.process_selected", "permits"
            )
            and view_models.holds_grant(session, resolved, "agent.run.intake", "permits")
        ),
    )
    return render(request, "intake_queue.html", context)


@router.get("/queue/early-resolution", operation_id="ui_early_resolution")
def ui_early_resolution(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the early-resolution board of the Data Steward."""
    resolved, refused = _guard(request, session, actor, "early_resolution")
    if refused is not None:
        return refused
    board = queues.early_resolution(session, resolved)
    # Every case of the board names the step that follows, so a reader knows
    # what the board is waiting for before the findings are read.
    for group in board["groups"]:
        for case in group["cases"]:
            case["next_step"] = steward_queue_views.intake_next_step(case)
    context = page_context(
        request,
        session,
        resolved,
        screen="early_resolution",
        title="Early resolution",
        board=board,
        guide=_guide("early_resolution"),
    )
    return render(request, "early_resolution.html", context)


#: The interface actions of the steward lane, merged into ``ACTION_HANDLERS``.
HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {}

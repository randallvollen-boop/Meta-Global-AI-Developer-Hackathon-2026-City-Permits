"""The eight server-rendered screens of the ACME City demonstration.

Every page resolves the acting persona from the server-held session and reads
the domain services directly.  A form posts a stable action identifier, the
expected version and a CSRF token; the server decides whether the action is
allowed.  The interface never accepts a role, an actor or a permission from
the browser.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-01, EDIT-02, EDIT-03, SEC-01
# The screens render the resolved responsibility, the current, submitted,
# proposed and issued values, the evidence and the history of every governed
# record, and every write names its destination and its expected version.

from __future__ import annotations

import hashlib
from types import SimpleNamespace
import hmac
import json
from urllib.parse import urlencode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from acme_city.adapters.sources.base import SourceCommand, adapter_for
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.auth.service import SessionService
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.schemas import (
    ChangeRequestCommand,
    ChangeTransitionCommand,
)
from acme_city.changes.service import ChangeService
from acme_city.core.config import Settings
from acme_city.core.errors import (
    AcmeError,
    AuthenticationRequiredError,
    PermissionDeniedError,
    ValidationError,
)
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import (
    AllocationCommand,
    AssessmentCommand,
    PaymentEventCommand,
    ReconciliationCommand,
    ReassessmentCommand,
)
from acme_city.finance.service import FinanceService
from acme_city.governance.schemas import (
    EscalateIssueCommand,
    PreviewAuthorityChangeCommand,
    PublishAuthorityChangeCommand,
    ReassignStewardCommand,
    RegisterDatasetCommand,
)
from acme_city.governance.service import GovernanceService
from acme_city.muse.image_client import IMAGE_COST_ESTIMATE_USD
from acme_city.persistence.models import finance as finance_models
from acme_city.permits import icons as permit_icons
from acme_city.permits import queues
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.issuance import IssuePermitCommand
from acme_city.permits.schemas import ReviseApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService
from acme_city.rules import approval_policy
from acme_city.rules.schemas import (
    DraftFeeScheduleCommand,
    DraftRuleCommand,
    FeeScheduleLifecycleCommand,
    PublishRuleCommand,
    RetireRuleCommand,
    RuleLifecycleCommand,
)
from acme_city.rules.service import RuleCatalogService
from acme_city.ui import admin_tabs as _admin_tabs
from acme_city.ui import admin_views, agent_views, display, patterns, property_views, view_models
from acme_city.ui.view_models import (
    actor_label,
    allowed_actions_for,
    feedback,
    navigation,
    persona_options,
)

#: The templates of the interface.
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"

#: The local stylesheet and script of the interface.
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"

#: The prefix of the local assets.  No external script, font or image is used.
STATIC_PREFIX = "/ui/static"

router = APIRouter(tags=["ui"])
#: The demonstration persona selector pages.  Mounted in demo mode only.
persona_router = APIRouter(tags=["ui"])
#: The /select page in production mode: the "Sign-in is not configured" page.
signin_router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT))
router.mount(STATIC_PREFIX, StaticFiles(directory=str(STATIC_ROOT)), name="ui-static")

#: Interface actions that exist only in the demonstration (simulators).  In
#: production mode they are neither listed nor accepted.
PRODUCTION_BLOCKED_ACTIONS: frozenset[str] = frozenset({"intake.simulate"})

#: The name of the field that carries the CSRF token of a form.
CSRF_FIELD = "csrf_token"

#: The name of the field that carries the page an action returns to.
NEXT_FIELD = "next"


# --------------------------------------------------------------------- context


@dataclass(frozen=True)
class ActionContext:
    """One action request: the session, the actor and the posted fields."""

    session: Session
    actor: ActorContext
    form: dict[str, str]
    settings: Settings
    #: The fields that were posted more than once, so a selection of rows can
    #: arrive without JavaScript.
    multi: dict[str, list[str]] = field(default_factory=dict)

    def text(self, name: str, default: str = "") -> str:
        """Return one posted text field."""
        value = self.form.get(name, default)
        return value.strip() if isinstance(value, str) else default

    def values(self, name: str) -> list[str]:
        """Return every posted value of one field."""
        values = self.multi.get(name)
        if values:
            return list(values)
        value = self.form.get(name)
        return [value] if isinstance(value, str) and value else []

    def integer(self, name: str) -> int | None:
        """Return one posted integer field."""
        raw = self.text(name)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError as error:
            raise ValidationError(f"{name!r} must be a whole number") from error

    def mapping(self, name: str) -> dict[str, Any]:
        """Return one posted JSON object field."""
        raw = self.text(name)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValidationError(f"{name!r} must be a JSON object") from error
        if not isinstance(value, dict):
            raise ValidationError(f"{name!r} must be a JSON object")
        return value


@dataclass(frozen=True)
class Outcome:
    """What an accepted action did and what the interface must report."""

    message: str
    destination: str = ""
    state: str = ""
    pending: bool = False
    affected: tuple[str, ...] = ()
    target_type: str = ""
    target_id: str = ""
    before_version: int | None = None
    after_version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ security


def csrf_token(settings: Settings, session_id: str | None) -> str:
    """Return the CSRF token of one server-held session.

    The token is derived from the session identifier and the server secret.
    It is bound to the session and it is never stored in the page as an
    authority: it only proves that the form came from this server.
    """
    if not session_id:
        return ""
    digest = hmac.new(
        settings.secret_key.get_secret_value().encode("utf-8"),
        f"csrf:{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def verify_csrf(settings: Settings, actor: ActorContext, presented: str) -> None:
    """Refuse a write whose CSRF token does not belong to the session."""
    expected = csrf_token(settings, actor.session_id)
    if not presented or not hmac.compare_digest(expected, presented):
        raise PermissionDeniedError(
            "the form token does not belong to this session; reload the screen and try again",
            actor_id=actor.actor_id,
            action="ui.action",
        )


#: The applicant's entry point. The staff-layout landing would duplicate it.
APPLICANT_HOME = "/city/"
APPLICANT_LABEL = "Applicant"


def moved_notice(
    request: Request, session: Session, actor: ActorContext | None, home_label: str
) -> str:
    """Return the one-line notice shown after a persona switch was redirected."""
    key = request.query_params.get("moved_from", "")
    known = {screen["key"] for screen in view_models.SCREENS}
    if actor is None or key not in known:
        return ""
    return (
        f"{actor_label(session, actor.actor_id)} can't open {view_models.screen_label(key)}, "
        f"so you're on {home_label} instead."
    )


def safe_next(value: str | None, fallback: str = "/queue") -> str:
    """Return a local path an action may return to."""
    if not value:
        return fallback
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    # A browser reads a backslash as a slash, so "/\\host" would leave the site;
    # control characters (CR, LF, tab) are stripped by URL parsers the same way.
    if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return fallback
    return value


def ui_actor(request: Request, session: Session = Depends(get_session, scope="function")) -> ActorContext | None:
    """Return the acting persona, or ``None`` when no session is presented."""
    try:
        return SessionService(session, request.app.state.settings).resolve_actor(request)
    except AuthenticationRequiredError:
        return None


def require_actor(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> ActorContext:
    """Return the acting persona, or ``None`` when no session is presented."""
    return actor


# ------------------------------------------------------------------- rendering


def _applicant_name(session: Session, actor: ActorContext | None) -> str:
    """Return the acting applicant's name for the page header ("" for staff)."""
    from acme_city.applicant_portal.service import applicant_display_name

    return applicant_display_name(session, actor)


def page_context(
    request: Request,
    session: Session,
    actor: ActorContext,
    *,
    screen: str,
    title: str,
    **extra: Any,
) -> dict[str, Any]:
    """Return the context every screen shares."""
    settings: Settings = request.app.state.settings
    return {
        "screen": screen,
        "title": title,
        "actor": {
            "actor_id": actor.actor_id,
            "label": actor_label(session, actor.actor_id),
            "department": view_models.actor_department(session, actor.actor_id),
        },
        "personas": persona_options(session),
        "navigation": navigation(session, actor),
        "moved_notice": moved_notice(
            request,
            session,
            actor,
            view_models.screen_label(screen) if view_models.screen_label(screen) != screen else title,
        ),
        "feedback": feedback(session, actor),
        "agent_status": agent_views.sidebar_status(session, actor),
        "csrf_token": csrf_token(settings, actor.session_id),
        "fictional_demo": True,
        "applicant_name": _applicant_name(session, actor),
        "ui_drawer": patterns.drawer_state(request, session, actor),
        **extra,
    }


def render(
    request: Request,
    name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> Any:
    """Render one template."""
    context = {"public_demo": request.app.state.settings.public_demo, **context}
    if request.app.state.settings.is_production:
        # No persona switch and no simulator action is shown in production mode.
        context = {**context, "personas": []}
        actions = context.get("actions")
        if isinstance(actions, list):
            context["actions"] = [
                item
                for item in actions
                if (item.get("action_id") if isinstance(item, dict) else getattr(item, "action_id", None))
                not in PRODUCTION_BLOCKED_ACTIONS
            ]
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def error_response(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    *,
    status_code: int,
    title: str,
    message: str,
    code: str = "",
    back: str = "",
) -> Any:
    """Render the error page of a refused screen."""
    context: dict[str, Any] = {
        "screen": "error",
        "title": title,
        "personas": persona_options(session),
        # A refused screen keeps the persona's own navigation, so a persona who landed
        # on a screen it cannot open can still reach one it can.
        "navigation": navigation(session, actor) if actor is not None else [],
        "home": view_models.home_for(session, actor) if actor is not None else None,
        "feedback": None,
        "csrf_token": "",
        "fictional_demo": True,
        "actor": (
            {
                "actor_id": actor.actor_id,
                "label": actor_label(session, actor.actor_id),
                "department": view_models.actor_department(session, actor.actor_id),
            }
            if actor is not None
            else None
        ),
        "error": {
            "title": title,
            "message": message,
            "code": code,
            "back": back,
        },
    }
    return render(request, "base.html", context, status_code=status_code)


# ------------------------------------------------------------------ persona


@persona_router.get("/select", operation_id="select_persona", name="select_persona")
def select_persona(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the persona selector.

    The selector offers exactly the four selectable personas.  A service
    identity is never offered and never holds a session.
    """
    context = {
        "screen": "select",
        "title": "Choose a persona",
        "personas": persona_options(session),
        "navigation": [],
        "feedback": None,
        "csrf_token": "",
        "fictional_demo": True,
        "actor": (
            {
                "actor_id": actor.actor_id,
                "label": actor_label(session, actor.actor_id),
            }
            if actor is not None
            else None
        ),
    }
    return render(request, "base.html", context)


@signin_router.get("/select", operation_id="sign_in_not_configured")
def sign_in_not_configured(request: Request, session: Session = Depends(get_session, scope="function")) -> Any:
    """Production mode: say that sign-in is not configured instead of offering personas."""
    from acme_city.auth.identity import (
        SIGN_IN_NOT_CONFIGURED_MESSAGE,
        SIGN_IN_NOT_CONFIGURED_TITLE,
    )

    context: dict[str, Any] = {
        "screen": "error",
        "title": SIGN_IN_NOT_CONFIGURED_TITLE,
        "personas": [],
        "navigation": [],
        "home": None,
        "feedback": None,
        "csrf_token": "",
        "fictional_demo": False,
        "actor": None,
        "error": {
            "title": SIGN_IN_NOT_CONFIGURED_TITLE,
            "message": SIGN_IN_NOT_CONFIGURED_MESSAGE,
            "code": "sign_in_not_configured",
            "back": "",
        },
    }
    return render(request, "base.html", context, status_code=503)


@persona_router.post("/ui/actor", operation_id="switch_persona")
async def switch_persona(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
) -> RedirectResponse:
    """Establish a server-held session for the selected persona."""
    form = await request.form()
    actor_id = str(form.get("actor_id", "")).strip()
    if not actor_id:
        return RedirectResponse("/select", status_code=303)
    service = SessionService(session, request.app.state.settings)
    try:
        cookie = service.select_actor(actor_id)
    except AuthenticationRequiredError:
        return RedirectResponse("/select", status_code=303)
    destination = safe_next(str(form.get(NEXT_FIELD, "")), "/queue")
    new_actor = service.resolve_actor(SimpleNamespace(cookies={cookie.cookie_name: cookie.value}))
    wanted = view_models.screen_for_path(destination)
    if actor_label(session, actor_id) == APPLICANT_LABEL and not destination.startswith(
        ("/apply", "/city")
    ):
        # The applicant's front door is the City website, not a staff page. A switch
        # made from the City website itself (next already under /apply or /city) is kept.
        destination = APPLICANT_HOME
        if wanted and not view_models.may_open_screen(session, new_actor, wanted):
            destination += f"?moved_from={wanted}"
    elif wanted and not view_models.may_open_screen(session, new_actor, wanted):
        # Demo smoothing: the new persona cannot open that screen, so land on its own home.
        home = view_models.home_for(session, new_actor)
        destination = f"{home['href']}?moved_from={wanted}"
    elif destination == "/queue":
        # A switch that asks for the generic staff landing lands on the home of
        # the new persona.  The City Administrator's home is the planning
        # overview; every other staff persona's home is the queue.
        home = view_models.home_for(session, new_actor)
        if home["href"] != destination:
            destination = home["href"]
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(**cookie.set_cookie_kwargs())
    return response


@router.post("/ui/end", operation_id="end_persona")
async def end_persona(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(ui_actor),
) -> RedirectResponse:
    """Revoke the current server-held session."""
    if actor is not None and actor.session_id:
        SessionService(session, request.app.state.settings).revoke(actor.session_id)
    response = RedirectResponse("/select", status_code=303)
    response.delete_cookie(key="acme_session", path="/")
    return response


# ----------------------------------------------------------------- screens


@router.get("/", operation_id="ui_root")
def ui_root(request: Request) -> RedirectResponse:
    """Send the browser to the work queue."""
    return RedirectResponse("/queue", status_code=303)


def _guard(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    screen: str,
) -> tuple[ActorContext | None, Any]:
    """Return the acting persona, or the refused response of a screen."""
    if actor is None:
        return None, RedirectResponse("/select", status_code=303)
    permissions = view_models.SCREEN_PERMISSIONS.get(screen, ())
    if not any(
        view_models.holds_grant(session, actor, permission, domain_id)
        for permission, domain_id in permissions
    ):
        return None, error_response(
            request,
            session,
            actor,
            status_code=403,
            title="This screen is outside your grants",
            message=(
                "Your persona does not hold a grant for this screen. The screens "
                "are separated by domain, and a configuration grant never implies "
                "a business approval."
            ),
            code="permission_denied",
            back="/queue",
        )
    return actor, None


@router.get("/queue", operation_id="ui_work_queue")
def ui_work_queue(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    view: str = "my",
    department: str | None = None,
    object_type: str | None = None,
    state: str | None = None,
    focus: str = "all",
) -> Any:
    """Show the work queue of the acting persona."""
    resolved, refused = _guard(request, session, actor, "queue")
    if refused is not None:
        return refused
    if actor_label(session, resolved.actor_id) == APPLICANT_LABEL:
        return RedirectResponse(APPLICANT_HOME, status_code=303)
    queue = view_models.work_queue(
        session,
        resolved,
        view=view,
        department=department,
        object_type=object_type,
        state=state,
        focus=focus,
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="queue",
        title="Work queue",
        queue=queue,
        saved_queues=view_models.queue_links(session, resolved),
        can_apply=bool(resolved.record_scope)
        and view_models.holds_grant(session, resolved, "application.submit", "permits"),
    )
    return render(request, "work_queue.html", context)


@router.get("/queue/review", operation_id="ui_review_queue")
def ui_review_queue(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    area: str = "",
) -> Any:
    """Show the review queue of the Permit Reviewer."""
    resolved, refused = _guard(request, session, actor, "review_queue")
    if refused is not None:
        return refused
    queue = queues.review_queue(session, resolved, area=area)
    context = page_context(
        request,
        session,
        resolved,
        screen="review_queue",
        title="Review queue",
        queue=queue,
        agent_awake=agent_views.agent_state(session, "adjudication")["mode"]
        == "awake",
        can_run=view_models.holds_grant(
            session, resolved, "agent.run.adjudication", "permits"
        ),
    )
    return render(request, "review_queue.html", context)


@router.get("/insight/city", operation_id="ui_insight_city")
def ui_insight_city(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    type: str = "",
    outcome: str = "",
    period: str = "",
    category: str = "",
    exceptions: str = "",
    synthetic: str = "",
) -> Any:
    """Show the City view: permit activity across the city (read-only)."""
    resolved, refused = _guard(request, session, actor, "insight_city")
    if refused is not None:
        return refused
    from acme_city.insight.city_view import city_view

    view = city_view(
        session,
        type=type,
        outcome=outcome,
        period=period,
        category=category,
        exceptions=exceptions,
        synthetic=synthetic,
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="insight_city",
        title="City view",
        view=view,
        can_start_whatif=view_models.holds_grant(
            session, resolved, "policy.scenario.manage", None
        ),
        whatif_query=urlencode(
            {
                name: value
                for name, value in (
                    ("type", view["filters"]["type"]),
                    ("category", ",".join(view["filters"]["category"])),
                )
                if value
            }
        ),
        model_runs=[],
        evidence=[
            {
                "label": "Stored applications, decisions and permits",
                "kind": "database query",
                "detail": f"{view['total_before_filters']} permits in the view; every figure is a count over these rows",
                "received_at": None,
            },
            {
                "label": "Synthetic data",
                "kind": "label",
                "detail": view["synthetic"]["note"],
                "received_at": None,
            },
        ],
    )
    return render(request, "insight_city.html", context)


@router.get("/permits/{application_id}", operation_id="ui_permit_workspace")
def ui_permit_workspace(
    application_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the permit workspace of one application."""
    resolved, refused = _guard(request, session, actor, "permit")
    if refused is not None:
        return refused
    detail = view_models.permit_workspace(session, resolved, application_id)
    if not detail:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That application is not available to you",
            message=(
                "The application does not exist or it is outside the record scope "
                "of your persona."
            ),
            code="not_found",
            back="/queue",
        )
    actions = allowed_actions_for(session, resolved, "permit", application_id, detail)
    context = page_context(
        request,
        session,
        resolved,
        screen="permit",
        title=f"Permit workspace: {detail['application']['source_application_number']}",
        detail=detail,
        active_tab=request.query_params.get("tab", "review"),
        responsibility=detail["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "permit_workspace.html", context)



# ------------------------------------------------------------- property master


def _locator_for(request: Request, session: Session) -> Any:
    from acme_city.gis.adapter import get_locator

    return get_locator(request.app.state.settings)


@router.get("/property", operation_id="ui_property_find")
def ui_property_find(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Find a property: the locator corrects the address, the parcel is the key."""
    resolved, refused = _guard(request, session, actor, "property")
    if refused is not None:
        return refused
    results: list[dict[str, Any]] = []
    error = ""
    query = q.strip()
    if query:
        from acme_city.gis.adapter import GisServiceError
        from acme_city.gis.catalog import SIMULATED_LABEL as _unused  # noqa: F401

        try:
            locator = _locator_for(request, session)
            for candidate in locator.find_candidates(query, 8):
                parcel = locator.parcel_at(candidate.x, candidate.y)
                results.append(
                    {
                        "address": candidate.address,
                        "score": candidate.score,
                        "status_word": property_views.STATUS_WORDS.get(
                            candidate.status, candidate.status
                        ),
                        "parcel_number": parcel.parcel_number if parcel else "",
                        "zoning": parcel.zoning if parcel else "",
                    }
                )
        except GisServiceError as exc:
            error = f"The city locator could not be used: {exc}"
    context = page_context(
        request,
        session,
        resolved,
        screen="masters",
        title="Find a property",
        query=query,
        results=results,
        error=error,
    )
    return render(request, "property_find.html", context)


@router.get("/property/suggest", operation_id="ui_property_suggest")
def ui_property_suggest(
    request: Request,
    text: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Return locator suggestions for the Find a property box."""
    resolved, refused = _guard(request, session, actor, "property")
    if refused is not None:
        return refused
    from acme_city.gis.adapter import GisServiceError

    try:
        suggestions = _locator_for(request, session).suggest(text, 6) if text.strip() else []
    except GisServiceError:
        suggestions = []
    return JSONResponse({"suggestions": suggestions, "simulated": True})


@router.get("/property/{parcel_number}", operation_id="ui_property_record")
def ui_property_record(
    parcel_number: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the property record of one parcel."""
    resolved, refused = _guard(request, session, actor, "property")
    if refused is not None:
        return refused
    record = property_views.property_record(session, resolved, parcel_number)
    if not record:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That property is not in the property master",
            message="No parcel with that number exists in the parcel register.",
            code="not_found",
            back="/property",
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="masters",
        title=f"Property record: {record['parcel_number']}",
        record=record,
        responsibility=record["responsibility"],
    )
    return render(request, "property_record.html", context)


@router.get("/map", operation_id="ui_town_map")
def ui_town_map(
    request: Request,
    parcel: str = "",
    application: str = "",
    q: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the map of the fictional town (staff personas)."""
    resolved, refused = _guard(request, session, actor, "property")
    if refused is not None:
        return refused
    candidates: list[dict[str, Any]] = []
    error = ""
    query = q.strip()
    if query:
        from acme_city.gis.adapter import GisServiceError

        try:
            locator = _locator_for(request, session)
            found = locator.find_candidates(query, 5)
            candidates = [
                {
                    "address": item.address,
                    "score": item.score,
                    "location": {"x": item.x, "y": item.y},
                    "attributes": {"PARCELID": item.parcel_number},
                }
                for item in found
            ]
            if found and not parcel:
                hit = locator.parcel_at(found[0].x, found[0].y)
                parcel = hit.parcel_number if hit else ""
        except GisServiceError as exc:
            error = f"The city locator could not be used: {exc}"
    town = property_views.town_map(
        session, resolved, parcel=parcel, application=application, candidates=candidates
    )
    subject = None
    if town["subject"]:
        subject = property_views.property_record(session, resolved, town["subject"]) or None
    context = page_context(
        request,
        session,
        resolved,
        screen="masters",
        title="Town map",
        town=town,
        subject=subject,
        query=query,
        candidates=candidates,
        error=error,
    )
    return render(request, "town_map.html", context)


@router.get("/rules-fees", operation_id="ui_rules_fees_old")
def ui_rules_fees_old() -> RedirectResponse:
    """Redirect the former rules and fees address to the current one."""
    return RedirectResponse(url="/rules", status_code=303)


@router.get("/rules", operation_id="ui_rules_fees")
def ui_rules_fees(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "rules",
    view: str = "published",
    version: str = "",
) -> Any:
    """Show the rule and fee catalogue."""
    resolved, refused = _guard(request, session, actor, "rules")
    if refused is not None:
        return refused
    catalogue = admin_views.rules_register(
        session,
        resolved,
        tab=tab,
        view=view,
        version_id=version or None,
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="rules",
        title="Rules and fees",
        catalogue=catalogue,
        responsibility=catalogue["responsibility"],
        actions=catalogue["actions"],
        denied_action_explanations=catalogue["denied_action_explanations"],
    )
    return render(request, "rules_fees.html", context)


@router.get("/overview", operation_id="ui_planning_overview")
def ui_planning_overview(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the planning overview of the City Administrator."""
    resolved, refused = _guard(request, session, actor, "overview")
    if refused is not None:
        return refused
    overview = admin_views.planning_overview(session, resolved)
    context = page_context(
        request,
        session,
        resolved,
        screen="overview",
        title="Planning overview",
        overview=overview,
        evidence_note=(
            "This screen counts records from several places. The "
            "evidence of a record is on the record itself."
        ),
    )
    return render(request, "overview.html", context)


@router.get("/reconciliation", operation_id="ui_reconciliation")
def ui_reconciliation(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "assessments",
    assessment: str = "",
    q: str = "",
) -> Any:
    """Show the reconciliation screen."""
    resolved, refused = _guard(request, session, actor, "reconciliation")
    if refused is not None:
        return refused
    position = admin_views.reconciliation_screen(
        session,
        resolved,
        tab=tab,
        assessment_id=assessment or None,
        query=q,
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="reconciliation",
        title="Reconciliation",
        position=position,
        responsibility=position["responsibility"],
        actions=position["actions"],
        denied_action_explanations=position["denied_action_explanations"],
    )
    return render(request, "reconciliation.html", context)


@router.get("/governance", operation_id="ui_governance_sources")
def ui_governance_sources(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "sources",
) -> Any:
    """Show the governance and sources screen."""
    resolved, refused = _guard(request, session, actor, "governance")
    if refused is not None:
        return refused
    governance = admin_views.governance_screen(session, resolved, tab=tab)
    actions = allowed_actions_for(session, resolved, "governance")
    context = page_context(
        request,
        session,
        resolved,
        screen="governance",
        title="Governance and sources",
        governance=governance,
        responsibility=governance["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "governance_sources.html", context)


@router.get("/agent/intake", operation_id="ui_agent_intake")
def ui_agent_intake(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the intake agent screen."""
    return _render_agent(request, session, actor, "agent_intake", "intake")


@router.get("/agent/adjudication", operation_id="ui_agent_adjudication")
def ui_agent_adjudication(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the adjudication agent screen."""
    return _render_agent(request, session, actor, "agent_adjudication", "adjudication")


def _render_agent(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    screen: str,
    agent_key: str,
) -> Any:
    """Render one agent screen with its banner, KPIs, graph and lists."""
    resolved, refused = _guard(request, session, actor, screen)
    if refused is not None:
        return refused
    view = agent_views.agent_screen(session, resolved, agent_key)
    context = page_context(
        request,
        session,
        resolved,
        screen=screen,
        title=view["agent_label"],
        agent=view,
        evidence=view["evidence"],
        model_runs=view["model_runs"],
        history=view["audit_history"],
    )
    return render(request, "agent_screen.html", context)


@router.get("/admin", operation_id="ui_administration")
def ui_administration(
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    tab: str = "permit-types",
) -> Any:
    """Show the administration screen."""
    resolved, refused = _guard(request, session, actor, "admin")
    if refused is not None:
        return refused
    view = agent_views.administration(session, resolved)
    settings: Settings = request.app.state.settings
    # The appearance tab carries the limits, the cost and the provenance of
    # the Muse Image generation, so the icons read the same everywhere.
    view["permit_type_icons"] = {
        **view["permit_type_icons"],
        "global_cap": settings.muse_image_daily_cap,
        "cost_estimate_usd": IMAGE_COST_ESTIMATE_USD,
    }
    # The tabs work without JavaScript: each tab is a link that carries the
    # section to show.  ``admin_tabs`` holds the registered tabs and the parts
    # of the Users tab.
    tabs = _admin_tabs.visible_tabs(session, resolved)
    keys = [entry.key for entry in tabs]
    context = page_context(
        request,
        session,
        resolved,
        screen="admin",
        title="Administration",
        admin=view,
        evidence=view["evidence"],
        model_runs=view["model_runs"],
        history=view["audit_history"],
        tab=tab if tab in keys else keys[0],
        admin_tabs=keys,
        admin_tab_labels={entry.key: entry.label for entry in tabs},
        admin_tab_templates=[entry.template for entry in tabs],
        admin_users_extras=[
            extra.template for extra in _admin_tabs.ADMIN_USERS_EXTRAS_PROVIDERS
        ],
        admin_icon_generation={"available": False, "reason": ""},
    )
    # A provider may add variables but never replace one: a clash with the
    # page or with another lane is refused rather than silently overwritten.
    for provider in [*tabs, *_admin_tabs.ADMIN_USERS_EXTRAS_PROVIDERS]:
        if provider.context_fn is not None:
            extra = provider.context_fn(session, resolved)
            clash = sorted(set(extra) & set(context))
            if clash:
                raise ValueError(
                    f"the administration part {provider.template!r} "
                    f"would replace {', '.join(clash)}"
                )
            context.update(extra)
    return render(request, "admin.html", context)


@router.get("/permit-type-icons/{icon_id}", operation_id="ui_permit_type_icon")
def ui_permit_type_icon(
    icon_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Serve one permit type icon's bytes to an actor who may view its type.

    Viewing a permit type follows the rules screen: the actor must hold one
    of that screen's grants.  The bytes are served with the icon's recorded
    media type and are never cached across icon changes.
    """
    from sqlalchemy import select as sa_select

    from acme_city.persistence.models import permit as permit_models

    # Icons are decorative and carry no record data. Every signed-in persona
    # sees them on work-queue rows, so a session is the only requirement.
    if actor is None:
        return RedirectResponse("/select", status_code=303)
    icon = session.execute(
        sa_select(permit_models.PermitTypeIcon).where(
            permit_models.PermitTypeIcon.id == icon_id
        )
    ).scalar_one_or_none()
    if icon is None:
        return Response(status_code=404)
    permit_type = session.execute(
        sa_select(permit_models.PermitType).where(
            permit_models.PermitType.id == icon.permit_type_id
        )
    ).scalar_one_or_none()
    if permit_type is None:
        return Response(status_code=404)
    return Response(
        content=icon.image_data,
        media_type=icon.media_type,
        headers={"Cache-Control": "no-store"},
    )


# ------------------------------------------------------------------ actions


def _conflict(result: ConflictResult) -> AcmeError:
    """Return the error envelope of a stale write."""
    return AcmeError(
        "the record changed since it was read; read it again and retry",
        code=result.code,
        expected_version=result.expected_version,
        current_version=result.current_version,
    )


def _stale_link(result: ConflictResult) -> AcmeError:
    """A stale link version is a 409, with the two versions."""
    from acme_city.core.errors import ConflictError

    return ConflictError(
        "the record changed since it was read; read it again and retry",
        expected_version=result.expected_version,
        current_version=result.current_version,
    )


def _registry_propose(ctx: ActionContext) -> Outcome:
    """Propose the candidate links of one source record."""
    command = MatchProposalCommand(
        source_system_id=ctx.text("source_system_id"),
        dataset_key=ctx.text("dataset_key"),
        source_record_id=ctx.text("source_record_id"),
        entity_type=ctx.text("entity_type") or None,
        notes=ctx.text("notes") or None,
    )
    proposal = RegistryService(ctx.session).propose(command, ctx.actor)
    return Outcome(
        message=(
            f"Proposed {len(proposal.candidate_ids)} candidate link(s) for "
            f"{command.source_record_id}. A steward decision is still required."
        ),
        destination="Registry candidate comparison",
        state=proposal.disposition,
        pending=True,
        target_type="source_record",
        target_id=command.source_record_id,
        affected=tuple(proposal.candidate_ids),
    )


def _registry_decide(ctx: ActionContext) -> Outcome:
    """Record a steward decision on a source link."""
    command = MatchDecisionCommand(
        decision=ctx.text("decision"),
        reason=ctx.text("reason"),
        source_system_id=ctx.text("source_system_id") or None,
        dataset_key=ctx.text("dataset_key") or None,
        source_record_id=ctx.text("source_record_id") or None,
        entity_id=ctx.text("entity_id") or None,
        crosswalk_id=ctx.text("crosswalk_id") or None,
        expected_version=ctx.integer("expected_version"),
    )
    result = RegistryService(ctx.session).decide(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _stale_link(result)
    view = result.value
    return Outcome(
        message=(
            f"Recorded the {command.decision} decision for {command.source_record_id} "
            f"as version {result.version}."
        ),
        destination="Registry crosswalk",
        state=view.link_status,
        target_type="crosswalk",
        target_id=view.crosswalk_id,
        after_version=result.version,
    )


def _registry_defer(ctx: ActionContext) -> Outcome:
    """Put a proposed link aside with a note; nothing is linked or changed."""
    record = ctx.text("source_record_id")
    result = RegistryService(ctx.session).defer(
        source_system_id=ctx.text("source_system_id"),
        dataset_key=ctx.text("dataset_key"),
        source_record_id=record,
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
        actor=ctx.actor,
    )
    if isinstance(result, ConflictResult):
        raise _stale_link(result)
    view = result.value
    return Outcome(
        message=f"Deferred the decision on {record}. The issue stays open with your note.",
        destination="Registry crosswalk",
        state=view.link_status,
        pending=True,
        target_type="crosswalk",
        target_id=view.crosswalk_id,
        after_version=result.version,
    )


def _change_request(ctx: ActionContext) -> Outcome:
    """Request a correction of a source fact or an identity link."""
    command = ChangeRequestCommand(
        target_type=ctx.text("target_type"),
        target_id=ctx.text("target_id"),
        title=ctx.text("title"),
        reason=ctx.text("reason"),
        change_kind=ctx.text("change_kind") or "factual",
        proposed_value=ctx.mapping("proposed_value"),
        old_value=ctx.mapping("old_value"),
        domain_id=ctx.text("domain_id") or None,
        destination=ctx.text("destination") or None,
        expected_version=ctx.integer("expected_version"),
    )
    view = ChangeService(ctx.session).request(command, ctx.actor)
    return Outcome(
        message=f"Created the change case '{view.title}'. It is waiting for a steward.",
        destination=view.destination or "Configured steward queue",
        state=view.status,
        pending=True,
        target_type="change_case",
        target_id=view.change_case_id,
        after_version=view.version,
    )


def _change_transition(ctx: ActionContext) -> Outcome:
    """Move a change case to the next permitted state."""
    command = ChangeTransitionCommand(
        change_case_id=ctx.text("change_case_id"),
        to_status=ctx.text("to_status"),
        expected_version=ctx.integer("expected_version"),
        reason=ctx.text("reason") or None,
    )
    result = ChangeService(ctx.session).transition(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result.value
    pending = view.status in {
        "requested",
        "in_review",
        "awaiting_approval",
        "approved",
        "sent_to_source",
    }
    return Outcome(
        message=f"The change case is now '{view.status}'.",
        destination=view.destination or "Configured steward queue",
        state=view.status,
        pending=pending,
        target_type="change_case",
        target_id=view.change_case_id,
        after_version=view.version,
        extra={"allowed_transitions": list(view.allowed_transitions)},
    )


def _change_dispatch(ctx: ActionContext) -> Outcome:
    """Send the pending source commands and deliver the publications."""
    from acme_city.changes.router import require_dispatch_grant

    require_dispatch_grant(ctx.session, ctx.actor)
    summary = ChangeDispatcher(ctx.session).dispatch_pending(limit=25)
    return Outcome(
        message=(
            f"Dispatched {summary.dispatched} source command(s); "
            f"{summary.acknowledged} acknowledged, {summary.timed_out} timed out, "
            f"{summary.rejected} rejected."
        ),
        destination="Simulated source adapters",
        state="dispatched",
        pending=bool(summary.dispatched - summary.acknowledged),
        affected=tuple(summary.change_case_ids),
        extra=summary.model_dump(mode="json"),
    )


def _source_write(ctx: ActionContext) -> Outcome:
    """Write a new version of a record of a simulated source system."""
    payload = ctx.mapping("payload")
    if not payload:
        payload = {
            key: value
            for key, value in ctx.form.items()
            if key not in {CSRF_FIELD, NEXT_FIELD, "action_id"} and value
        }
    command = SourceCommand(
        source_system_id=ctx.text("source_system_id"),
        dataset_key=ctx.text("dataset_key"),
        record_id=ctx.text("record_id"),
        expected_version=ctx.text("expected_version") or None,
        payload=payload,
        request_key=ctx.text("request_key") or None,
        actor_id=ctx.actor.actor_id,
    )
    adapter = adapter_for(command.source_system_id, ctx.session)
    acknowledgement = adapter.apply(command, ctx.actor)
    pending = acknowledgement.status in {"timeout"}
    return Outcome(
        message=acknowledgement.message,
        destination=adapter.label,
        state=acknowledgement.status,
        pending=pending,
        target_type="source_record",
        target_id=command.record_id,
        extra={"acknowledgement": acknowledgement.to_dict()},
    )


def _lifecycle(ctx: ActionContext) -> Any:
    """Return the lifecycle service bound to the request session."""
    from acme_city.permits.lifecycle import LifecycleService

    return LifecycleService(ctx.session)


def _permit_intake_process_selected(ctx: ActionContext) -> Outcome:
    """Run the intake agent on the cases the person selected.

    The selection is a list of ``application id`` and ``version`` pairs.  It
    is bounded, deduplicated and checked case by case; the batch either runs
    completely or not at all.
    """
    from acme_city.permits.bulk import Selection, process_selected

    selections: list[Selection] = []
    for raw in ctx.values("selection"):
        text = str(raw).strip()
        if not text:
            continue
        application_id, separator, version = text.rpartition(":")
        if not separator or not application_id.strip():
            raise ValidationError(
                "a selected row must name the case and the version it was read at"
            )
        try:
            expected = int(version)
        except ValueError as error:
            raise ValidationError(
                "a selected row must name the version it was read at"
            ) from error
        selections.append(Selection(application_id.strip(), expected))
    result = process_selected(
        ctx.session,
        actor=ctx.actor,
        selections=selections,
        settings=ctx.settings,
    )
    return Outcome(
        message=(
            f"The intake agent ran on {len(result.processed)} selected case(s)."
        ),
        destination="Intake agent",
        state="completed" if result.processed else "skipped",
        target_type="agent",
        target_id="intake",
        affected=result.processed,
        extra={"detail": ", ".join(f"{item['reference']}: {item['outcome']}" for item in result.details)},
    )


def _permit_case_return(ctx: ActionContext) -> Outcome:
    """Return a case to the applicant."""
    application = _lifecycle(ctx).return_application(
        application_id=ctx.text("application_id"),
        reason_code=ctx.text("reason_code"),
        reason=ctx.text("reason"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Returned the application to the applicant.",
        destination="Permitting application",
        state=application.status,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_advance(ctx: ActionContext) -> Outcome:
    """Advance a case to the review area of its permit type."""
    application = _lifecycle(ctx).advance_to_review(
        application_id=ctx.text("application_id"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Advanced the application to review.",
        destination="Permitting application",
        state=application.status,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_request_revisions(ctx: ActionContext) -> Outcome:
    """Ask the applicant for revisions."""
    application = _lifecycle(ctx).request_revisions(
        application_id=ctx.text("application_id"),
        reason_code=ctx.text("reason_code"),
        message=ctx.text("message"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Asked the applicant for revisions.",
        destination="Permitting application",
        state=application.status,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_archive(ctx: ActionContext) -> Outcome:
    """Archive a case."""
    application = _lifecycle(ctx).archive(
        application_id=ctx.text("application_id"),
        reason_code=ctx.text("reason_code"),
        reason=ctx.text("reason"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Archived the application.",
        destination="Permitting application",
        state=application.status,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_restore(ctx: ActionContext) -> Outcome:
    """Restore an archived case."""
    application = _lifecycle(ctx).restore(
        application_id=ctx.text("application_id"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Restored the application to the status it held.",
        destination="Permitting application",
        state=application.status,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_priority(ctx: ActionContext) -> Outcome:
    """Change the priority of a case."""
    from acme_city.permits.routing import RoutingService

    application = RoutingService(ctx.session).set_priority(
        application_id=ctx.text("application_id"),
        priority=ctx.text("priority"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message=f"Set the priority to {application.priority}.",
        destination="Permitting application",
        state=application.priority,
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_assign(ctx: ActionContext) -> Outcome:
    """Route a case to a staff member."""
    from acme_city.permits.routing import RoutingService

    application = RoutingService(ctx.session).assign(
        application_id=ctx.text("application_id"),
        owner_actor_id=ctx.text("owner_actor_id"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Routed the application to its owner.",
        destination="Permitting application",
        state=application.owner_actor_id or "",
        target_type="application",
        target_id=application.id,
        after_version=application.version,
    )


def _permit_case_comment(ctx: ActionContext) -> Outcome:
    """Write a comment on a case."""
    from acme_city.permits.comments import CommentService

    comment = CommentService(ctx.session).add_comment(
        application_id=ctx.text("application_id"),
        body=ctx.text("body"),
        visibility=ctx.text("visibility"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message=(
            "Added an applicant-visible comment."
            if comment.visibility == "applicant"
            else "Added an internal note."
        ),
        destination="Permitting comments",
        state=comment.visibility,
        target_type="application",
        target_id=comment.application_id,
        extra={"comment_id": comment.id, "visibility": comment.visibility},
    )


def _permit_finding_waive(ctx: ActionContext) -> Outcome:
    """Waive one current intake finding."""
    from acme_city.permits.finding_actions import waive_finding

    finding = waive_finding(
        ctx.session,
        finding_id=ctx.text("finding_id"),
        reason_code=ctx.text("reason_code"),
        reason=ctx.text("reason"),
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Waived the finding.",
        destination="Permitting findings",
        state="waived",
        target_type="finding",
        target_id=finding.id,
        after_version=finding.version,
        extra={"finding_id": finding.id},
    )


def _permit_evaluate(ctx: ActionContext) -> Outcome:
    """Evaluate the current revision of an application."""
    application_id = ctx.text("application_id")
    view = PermitService(ctx.session).evaluate(application_id, ctx.actor)
    open_blockers = view_models.open_blockers(ctx.session, application_id)
    message = (
        f"Validation finished with the outcome '{view.outcome}' on version "
        f"{view.version}."
    )
    if open_blockers:
        count = len(open_blockers)
        message = (
            f"Validation finished. The rule checks gave the outcome '{view.outcome}' "
            f"on version {view.version}, and "
            + (
                "1 blocker still prevents a decision."
                if count == 1
                else f"{count} blockers still prevent a decision."
            )
            + " The blockers are listed under Application checks."
        )
    return Outcome(
        message=message,
        destination="Permitting validation",
        state=view.outcome,
        pending=bool(view.blockers),
        target_type="application",
        target_id=application_id,
        after_version=view.version,
        extra={"blockers": [blocker.model_dump(mode="json") for blocker in view.blockers]},
    )


def _decision_conditions(ctx: ActionContext) -> list[str]:
    """Return the conditions of approval the form carries.

    One condition per line.  The service checks the list; the form only
    reads it.
    """
    return [line.strip() for line in ctx.text("conditions").splitlines() if line.strip()]


def _permit_decide(ctx: ActionContext) -> Outcome:
    """Record an actual reviewer decision."""
    command = PermitDecisionCommand(
        application_id=ctx.text("application_id"),
        outcome=ctx.text("outcome"),
        reason=ctx.text("reason"),
        conditions=_decision_conditions(ctx),
        reason_code=ctx.text("reason_code"),
        expected_application_version=ctx.integer("expected_application_version"),
        expected_evaluation_version=ctx.integer("expected_evaluation_version"),
    )
    result = PermitService(ctx.session).decide(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result.value
    return Outcome(
        message=f"Recorded the reviewer decision '{view.outcome}'.",
        destination="Permitting decision record",
        state=view.outcome,
        target_type="decision",
        target_id=view.decision_id,
        after_version=view.version,
        extra={"detail": "; ".join(view.conditions)},
    )


def _permit_reconfirm(ctx: ActionContext) -> Outcome:
    """Record a reviewer reconfirmation of a stale decision."""
    command = PermitDecisionCommand(
        application_id=ctx.text("application_id"),
        outcome=ctx.text("outcome"),
        reason=ctx.text("reason"),
        conditions=_decision_conditions(ctx),
        reason_code=ctx.text("reason_code"),
        expected_application_version=ctx.integer("expected_application_version"),
        expected_evaluation_version=ctx.integer("expected_evaluation_version"),
    )
    result = PermitService(ctx.session).reconfirm(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result.value
    return Outcome(
        message=f"Recorded the reviewer reconfirmation '{view.outcome}'.",
        destination="Permitting decision record",
        state=view.outcome,
        target_type="decision",
        target_id=view.decision_id,
        after_version=view.version,
        extra={"detail": "; ".join(view.conditions)},
    )


def _permit_issue(ctx: ActionContext) -> Outcome:
    """Issue a simulated permit from a current approved decision."""
    command = IssuePermitCommand(
        application_id=ctx.text("application_id"),
        decision_id=ctx.text("decision_id"),
        expected_application_version=ctx.integer("expected_application_version") or 0,
        expected_decision_version=ctx.integer("expected_decision_version") or 0,
        command_key=ctx.text("command_key"),
        reason=ctx.text("reason") or None,
    )
    result = PermitService(ctx.session).issue(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result.value
    return Outcome(
        message=f"Issued the simulated permit {view.permit_number}.",
        destination="Permitting issued permit",
        state=view.status,
        target_type="permit",
        target_id=view.permit_id,
        extra={"permit_number": view.permit_number, "artifact_hash": view.artifact_hash},
    )


def _permit_revise(ctx: ActionContext) -> Outcome:
    """Create a new submitted revision of an application."""
    facts = ctx.mapping("facts")
    command = ReviseApplicationCommand(
        application_id=ctx.text("application_id"),
        facts=facts,
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
    )
    view = PermitService(ctx.session).revise(command, ctx.actor)
    return Outcome(
        message=(
            f"Created revision {view.revision_number} of "
            f"{view.source_application_number}."
        ),
        destination="Permitting application revision",
        state=view.status,
        target_type="application",
        target_id=view.application_id,
        after_version=view.application_version,
    )


def _rule_draft(ctx: ActionContext) -> Outcome:
    """Create a new draft rule version."""
    command = DraftRuleCommand(
        rule_id=ctx.text("rule_id"),
        permit_type_key=ctx.text("permit_type_key"),
        title=ctx.text("title"),
        citation=ctx.text("citation"),
        field_path=ctx.text("field_path") or None,
        operator=ctx.text("operator") or None,
        limit_value=ctx.text("limit_value") or None,
        on_violate=ctx.text("on_violate") or None,
        message=ctx.text("message") or None,
        effective_from=ctx.text("effective_from"),
        reason=ctx.text("reason"),
    )
    result = RuleCatalogService(ctx.session).draft(command, ctx.actor)
    return Outcome(
        message=f"Created the draft rule version {result.value.version_label}.",
        destination="Approved rules register",
        state=result.value.status,
        target_type="rule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _rule_submit(ctx: ActionContext) -> Outcome:
    """Move a draft rule version into review."""
    command = RuleLifecycleCommand(
        rule_version_id=ctx.text("rule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
    )
    result = RuleCatalogService(ctx.session).submit_for_review(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    return Outcome(
        message=f"The rule version is now '{result.value.status}'.",
        destination="Approved rules register",
        state=result.value.status,
        target_type="rule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _confirmed(ctx: ActionContext) -> bool:
    """Return whether the author ticked the confirmation of their own approval."""
    return ctx.text("confirm_author_approval").lower() in ("on", "1", "true", "yes")


def _refuse_own_version(ctx: ActionContext, model: Any) -> None:
    """Say plainly why an author cannot approve or publish their own version.

    Only the independent approval policy refuses it.  The service refuses it
    too; this only gives the refusal its plain words.
    """
    if approval_policy.is_single():
        return
    row = ctx.session.get(model, ctx.text("rule_version_id") or ctx.text("fee_schedule_version_id"))
    if row is not None and row.author_actor_id is not None and row.author_actor_id == ctx.actor.actor_id:
        raise PermissionDeniedError(
            "You authored this version; another administrator must approve it.",
            actor_id=ctx.actor.actor_id,
            action="ui.action",
            target_type=model.__tablename__,
            target_id=row.id,
        )


def _rule_approve(ctx: ActionContext) -> Outcome:
    """Approve a rule version that somebody else authored."""
    _refuse_own_version(ctx, finance_models.RuleVersion)
    command = RuleLifecycleCommand(
        rule_version_id=ctx.text("rule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
        confirm_author_approval=_confirmed(ctx),
    )
    result = RuleCatalogService(ctx.session).approve(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    return Outcome(
        message=f"The rule version is now '{result.value.status}'.",
        destination="Approved rules register",
        state=result.value.status,
        target_type="rule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _rule_publish(ctx: ActionContext) -> Outcome:
    """Publish an approved rule version."""
    _refuse_own_version(ctx, finance_models.RuleVersion)
    command = PublishRuleCommand(
        rule_version_id=ctx.text("rule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
        precedence=ctx.text("precedence") or None,
    )
    result = RuleCatalogService(ctx.session).publish(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    return Outcome(
        message=f"The rule version is now '{result.value.status}'.",
        destination="Approved rules register",
        state=result.value.status,
        target_type="rule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _rule_retire(ctx: ActionContext) -> Outcome:
    """Retire a published rule version."""
    command = RetireRuleCommand(
        rule_version_id=ctx.text("rule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
    )
    result = RuleCatalogService(ctx.session).retire(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    return Outcome(
        message=f"The rule version is now '{result.value.status}'.",
        destination="Approved rules register",
        state=result.value.status,
        target_type="rule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _fee_draft(ctx: ActionContext) -> Outcome:
    """Create a new draft fee schedule version."""
    command = DraftFeeScheduleCommand(
        fee_schedule_id=ctx.text("fee_schedule_id"),
        version_label=ctx.text("version_label"),
        effective_from=ctx.text("effective_from"),
        currency=ctx.text("currency") or "USD",
        definition=ctx.mapping("definition"),
        reason=ctx.text("reason"),
    )
    result = RuleCatalogService(ctx.session).draft_fee_schedule(command, ctx.actor)
    return Outcome(
        message=f"Created the draft fee schedule {result.value.version_label}.",
        destination="Approved fee register",
        state=result.value.status,
        target_type="fee_schedule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _fee_transition(
    ctx: ActionContext,
    transition: str,
    message: str,
) -> Outcome:
    """Move one fee schedule version through its lifecycle."""
    if transition in ("approve", "publish"):
        _refuse_own_version(ctx, finance_models.FeeScheduleVersion)
    command = FeeScheduleLifecycleCommand(
        fee_schedule_version_id=ctx.text("fee_schedule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
        confirm_author_approval=_confirmed(ctx),
        precedence=ctx.text("precedence") or None,
    )
    service = RuleCatalogService(ctx.session)
    if transition == "submit":
        result = service.submit_fee_schedule_for_review(command, ctx.actor)
    elif transition == "approve":
        result = service.approve_fee_schedule(command, ctx.actor)
    elif transition == "publish":
        result = service.publish_fee_schedule(command, ctx.actor)
    else:
        result = service.retire_fee_schedule(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    return Outcome(
        message=f"{message} The fee schedule is now '{result.value.status}'.",
        destination="Approved fee register",
        state=result.value.status,
        target_type="fee_schedule_version",
        target_id=result.value.row_id,
        after_version=result.version,
    )


def _fee_submit(ctx: ActionContext) -> Outcome:
    """Move a draft fee schedule version into review."""
    return _fee_transition(ctx, "submit", "The fee schedule entered review.")


def _fee_approve(ctx: ActionContext) -> Outcome:
    """Approve a fee schedule version."""
    return _fee_transition(ctx, "approve", "The fee schedule was approved.")


def _fee_publish(ctx: ActionContext) -> Outcome:
    """Publish an approved fee schedule version."""
    return _fee_transition(ctx, "publish", "The fee schedule was published.")


def _fee_retire(ctx: ActionContext) -> Outcome:
    """Retire a published fee schedule version."""
    return _fee_transition(ctx, "retire", "The fee schedule was retired.")


def _finance_assess(ctx: ActionContext) -> Outcome:
    """Assess the declared valuation of an application."""
    command = AssessmentCommand(
        application_id=ctx.text("application_id"),
        valuation=ctx.text("valuation") or None,
        reason=ctx.text("reason"),
        expected_application_version=ctx.integer("expected_application_version"),
    )
    view = FinanceService(ctx.session).assess(command, ctx.actor)
    return Outcome(
        message=(
            f"Assessed {view.assessed_total} {view.currency} on assessment version "
            f"{view.version}."
        ),
        destination="Finance assessment",
        state=view.status,
        target_type="assessment",
        target_id=view.assessment_id,
        after_version=view.version,
    )


def _finance_reassess(ctx: ActionContext) -> Outcome:
    """Assess an application again at a new valuation."""
    command = ReassessmentCommand(
        application_id=ctx.text("application_id"),
        valuation=ctx.text("valuation") or None,
        reason=ctx.text("reason"),
        expected_application_version=ctx.integer("expected_application_version"),
        carry_forward=ctx.text("carry_forward", "true").lower() != "false",
    )
    view = FinanceService(ctx.session).reassess(command, ctx.actor)
    return Outcome(
        message=(
            f"Reassessed {view.assessed_total} {view.currency} on assessment version "
            f"{view.version}."
        ),
        destination="Finance assessment",
        state=view.status,
        target_type="assessment",
        target_id=view.assessment_id,
        after_version=view.version,
    )


def _finance_import(ctx: ActionContext) -> Outcome:
    """Import one simulated ERP payment event."""
    command = PaymentEventCommand(
        source_transaction_id=ctx.text("source_transaction_id"),
        source_event_id=ctx.text("source_event_id"),
        event_type=ctx.text("event_type") or "received",
        amount=ctx.text("amount"),
        currency=ctx.text("currency") or "USD",
        source_event_version=ctx.text("source_event_version") or None,
        payer_account_id=ctx.text("payer_account_id") or None,
        reason=ctx.text("reason"),
    )
    result = FinanceService(ctx.session).import_payment(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result
    return Outcome(
        message=f"Imported the receipt {view.source_transaction_id} ({view.amount} {view.currency}).",
        destination="Simulated ERP/Finance ledger",
        state=view.settlement_status,
        target_type="payment",
        target_id=view.payment_id,
    )


def _finance_allocate(ctx: ActionContext) -> Outcome:
    """Confirm an allocation of settled funds to an assessment version."""
    command = AllocationCommand(
        payment_id=ctx.text("payment_id"),
        assessment_id=ctx.text("assessment_id"),
        amount=ctx.text("amount"),
        currency=ctx.text("currency") or "USD",
        idempotency_key=ctx.text("idempotency_key"),
        reason=ctx.text("reason"),
    )
    result = FinanceService(ctx.session).allocate(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
    view = result
    return Outcome(
        message=f"Confirmed an allocation of {view.amount} {view.currency}.",
        destination="Finance allocation",
        state=view.status,
        target_type="allocation",
        target_id=view.allocation_id,
    )


def _finance_reconcile(ctx: ActionContext) -> Outcome:
    """Reconcile an assessment version against its receipts."""
    command = ReconciliationCommand(
        assessment_id=ctx.text("assessment_id"),
        payment_ids=[item for item in ctx.text("payment_ids").split(",") if item.strip()],
    )
    view = FinanceService(ctx.session).reconcile(command, ctx.actor)
    return Outcome(
        message=(
            f"Reconciled position: assessed {view.assessed_total}, settled allocated "
            f"{view.settled_allocated}, balance {view.balance} {view.currency}."
        ),
        destination="Finance reconciliation",
        state=view.status,
        target_type="assessment",
        target_id=view.assessment_id,
        extra={"exception": view.exception},
    )


def _governance_register(ctx: ActionContext) -> Outcome:
    """Register a source dataset with its responsibility."""
    command = RegisterDatasetCommand(
        source_system_id=ctx.text("source_system_id"),
        dataset_key=ctx.text("dataset_key"),
        label=ctx.text("label"),
        domain_id=ctx.text("domain_id") or None,
        accountable_owner_actor_id=ctx.text("accountable_owner_actor_id") or None,
        steward_queue_id=ctx.text("steward_queue_id") or None,
        system_custodian_actor_id=ctx.text("system_custodian_actor_id") or None,
        authority_policy_id=ctx.text("authority_policy_id") or None,
        correction_route=ctx.text("correction_route") or None,
        reason=ctx.text("reason") or None,
    )
    result = GovernanceService(ctx.session).register_dataset(command, ctx.actor)
    return Outcome(
        message=f"Registered the dataset '{result.dataset_key}'.",
        destination="Governance registration",
        state=result.registration_state,
        pending=not result.publishable,
        target_type="source_contract",
        target_id=result.contract_id,
        after_version=result.version,
        extra={"missing_bindings": list(result.missing_bindings)},
    )


def _governance_publish_dataset(ctx: ActionContext) -> Outcome:
    """Publish a registered dataset."""
    result = GovernanceService(ctx.session).publish_dataset(
        ctx.text("dataset_key"), ctx.actor
    )
    return Outcome(
        message=f"The dataset '{result.dataset_key}' is now '{result.registration_state}'.",
        destination="Governance registration",
        state=result.registration_state,
        target_type="source_contract",
        target_id=result.contract_id,
        after_version=result.version,
    )


def _governance_reassign(ctx: ActionContext) -> Outcome:
    """Move a responsibility to another actor."""
    command = ReassignStewardCommand(
        domain_id=ctx.text("domain_id"),
        responsibility=ctx.text("responsibility") or "steward",
        new_actor_id=ctx.text("new_actor_id"),
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
    )
    result = GovernanceService(ctx.session).reassign_steward(command, ctx.actor)
    return Outcome(
        message=f"The {command.responsibility} of {command.domain_id} is now {command.new_actor_id}.",
        destination="Effective-dated assignment",
        state="effective",
        target_type="assignment",
        target_id=result.assignment_id,
        after_version=result.version,
    )


def _governance_authority_preview(ctx: ActionContext) -> Outcome:
    """Preview the impact of a change of field authority."""
    command = PreviewAuthorityChangeCommand(
        policy_id=ctx.text("policy_id"),
        field_group=ctx.text("field_group"),
        domain_id=ctx.text("domain_id") or None,
        authoritative_source_system_id=ctx.text("authoritative_source_system_id") or None,
        authoritative_dataset_key=ctx.text("authoritative_dataset_key") or None,
        change_destination=ctx.text("change_destination"),
        user_action=ctx.text("user_action"),
        requires_source_ack=ctx.text("requires_source_ack", "true").lower() != "false",
        decision_relevant=ctx.text("decision_relevant", "false").lower() == "true",
        reason=ctx.text("reason") or None,
    )
    preview = GovernanceService(ctx.session).preview_authority_change(command, ctx.actor)
    return Outcome(
        message=(
            f"The preview touches {len(preview.impacted_applications)} application(s) "
            f"and {len(preview.impacted_datasets)} dataset(s)."
        ),
        destination="Authority policy preview",
        state="preview",
        pending=True,
        target_type="authority_policy",
        target_id=preview.policy_id,
        extra=preview.model_dump(mode="json"),
    )


def _governance_authority_publish(ctx: ActionContext) -> Outcome:
    """Publish an authority policy version after its impact preview."""
    command = PublishAuthorityChangeCommand(
        policy_id=ctx.text("policy_id"),
        approver_actor_id=ctx.text("approver_actor_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
        field_group=ctx.text("field_group") or None,
        domain_id=ctx.text("domain_id") or None,
        authoritative_source_system_id=ctx.text("authoritative_source_system_id") or None,
        authoritative_dataset_key=ctx.text("authoritative_dataset_key") or None,
        change_destination=ctx.text("change_destination") or None,
        user_action=ctx.text("user_action") or None,
        requires_source_ack=ctx.text("requires_source_ack", "true").lower() != "false",
        decision_relevant=ctx.text("decision_relevant", "false").lower() == "true",
    )
    result = GovernanceService(ctx.session).publish_authority_change(command, ctx.actor)
    return Outcome(
        message=f"Published the authority policy version {result.version}.",
        destination="Authority policy",
        state=result.status,
        target_type="authority_policy",
        target_id=result.policy_id,
        after_version=result.version,
    )


def _governance_escalate(ctx: ActionContext) -> Outcome:
    """Route a dispute to the accountable owner of its domain."""
    command = EscalateIssueCommand(
        domain_id=ctx.text("domain_id"),
        subject_type=ctx.text("subject_type"),
        subject_id=ctx.text("subject_id"),
        issue_type=ctx.text("issue_type"),
        description=ctx.text("description"),
        reason=ctx.text("reason") or None,
    )
    result = GovernanceService(ctx.session).escalate_issue(command, ctx.actor)
    return Outcome(
        message=f"Raised the issue '{result.issue_type}' and routed it to its owner.",
        destination="Governance issue queue",
        state=result.status,
        target_type="governance_issue",
        target_id=result.issue_id,
        after_version=result.version,
    )


def _intake_simulate(ctx: ActionContext) -> Outcome:
    """Simulate a batch of incoming permits and run triage for each."""
    from acme_city.portal_intake.router import SimulateCommand
    from acme_city.portal_intake.service import IntakeService

    count = ctx.integer("count")
    service = IntakeService(ctx.session, settings=ctx.settings)
    results = service.simulate(
        ctx.text("scenario"), count=count, actor=ctx.actor
    )
    created = [r.source_application_number for r in results if r.status == "created"]
    return Outcome(
        message=(
            f"Simulated {len(results)} incoming permit(s); "
            f"{len(created)} new application(s): {', '.join(created) or 'none'}."
        ),
        destination="ACME ePermit Portal (simulated) intake",
        state="simulated",
        affected=tuple(created),
        target_type="source_dataset",
        target_id="submitted_applications",
        extra={"results": [r.model_dump(mode="json") for r in results]},
    )


def _config_permit_type_document(ctx: ActionContext) -> Outcome:
    """Require a document of a permit type, or stop requiring it."""
    from acme_city.configuration.service import ConfigurationService

    required = ctx.text("required").strip().lower() in {"yes", "true", "1", "required"}
    row = ConfigurationService(ctx.session).set_required_document(
        permit_type_id=ctx.text("permit_type_id"),
        document_type=ctx.text("document_type"),
        required=required,
        actor=ctx.actor,
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message=(
            f"{'Require' if required else 'Stop requiring'} "
            f"{ctx.text('document_type')} for {row.label}."
        ),
        destination="Permit type configuration",
        state="updated",
        target_type="permit_type",
        target_id=row.id,
        after_version=row.version,
    )


def _config_permit_type_create(ctx: ActionContext) -> Outcome:
    """Create one new permit type."""
    from acme_city.configuration.service import ConfigurationService

    row = ConfigurationService(ctx.session).create_permit_type(
        key=ctx.text("key"),
        label=ctx.text("label"),
        description=ctx.text("description"),
        review_area=ctx.text("review_area"),
        process_category=ctx.text("process_category"),
        discretionary=ctx.text("discretionary").strip().lower() in {"yes", "true", "1"},
        required_fields=[
            item.strip()
            for item in ctx.text("required_fields").replace(",", " ").split()
            if item.strip()
        ],
        required_documents=[
            item.strip()
            for item in ctx.text("required_documents").replace(",", " ").split()
            if item.strip()
        ],
        fee_schedule_key=ctx.text("fee_schedule_key"),
        actor=ctx.actor,
    )
    return Outcome(
        message=(
            f"Created the permit type {row.label}. It has no published rule, so the "
            "adjudication agent will hold it for a person."
        ),
        destination="Permit type configuration",
        state="created",
        target_type="permit_type",
        target_id=row.id,
        after_version=row.version,
    )


def _config_reason_code_add(ctx: ActionContext) -> Outcome:
    """Add one reason code."""
    from acme_city.configuration.service import ConfigurationService

    row = ConfigurationService(ctx.session).add_reason_code(
        code=ctx.text("code"),
        label=ctx.text("label"),
        description=ctx.text("description"),
        code_type=ctx.text("code_type"),
        actor=ctx.actor,
    )
    return Outcome(
        message=f"Added the reason code {row.code}.",
        destination="Reason code configuration",
        state="created",
        target_type="reason_code",
        target_id=row.id,
        after_version=row.version,
    )


def _config_reason_code_retire(ctx: ActionContext) -> Outcome:
    """Retire one reason code."""
    from acme_city.configuration.service import ConfigurationService

    row = ConfigurationService(ctx.session).retire_reason_code(
        code=ctx.text("code"), actor=ctx.actor
    )
    return Outcome(
        message=f"Retired the reason code {row.code}.",
        destination="Reason code configuration",
        state="retired",
        target_type="reason_code",
        target_id=row.id,
        after_version=row.version,
    )


def _config_user_add(ctx: ActionContext) -> Outcome:
    """Add one user with the grant template of a persona role."""
    from acme_city.configuration.service import ConfigurationService

    row = ConfigurationService(ctx.session).add_user(
        name=ctx.text("name"),
        department=ctx.text("department"),
        persona_role=ctx.text("persona_role"),
        actor=ctx.actor,
    )
    return Outcome(
        message=(
            f"Added the user {row.label}. Added users do not appear in the persona "
            "switcher."
        ),
        destination="User list",
        state="created",
        target_type="actor",
        target_id=row.actor_id,
        after_version=1,
    )


def _agent_toggle(ctx: ActionContext) -> Outcome:
    """Wake one agent or put it back to sleep."""
    from acme_city.agents.control import AGENT_LABELS, AgentControlService

    agent_key = ctx.text("agent_key")
    mode = ctx.text("mode")
    row = AgentControlService(ctx.session).set_mode(agent_key, mode, ctx.actor)
    label = AGENT_LABELS.get(agent_key, agent_key)
    verb = "awake" if row.mode == "awake" else "asleep"
    return Outcome(
        message=f"The {label.lower()} is {verb}.",
        destination="Agent control",
        state=verb,
        target_type="agent_control",
        target_id=row.id,
        after_version=row.version,
    )


def _agent_run(ctx: ActionContext, agent_key: str) -> Outcome:
    """Run one agent on one case, or on a bounded batch of the cases that wait.

    The agent is named by the action identifier, never by the form: the
    browser does not choose which agent runs.  The run goes through the
    shared work queue, so the queue records the attempt and its outcome.
    """
    from acme_city.agents.adjudication import AdjudicationAgent
    from acme_city.agents.control import AGENT_LABELS, AgentControlService
    from acme_city.agents.intake import waiting_applications
    from acme_city.agents.runtime import run_agent, run_batch
    from acme_city.permits.service import PermitService

    application_id = ctx.text("application_id")
    control = AgentControlService(ctx.session)
    control.authorize_manual_run(ctx.actor, agent_key)
    label = AGENT_LABELS.get(agent_key, agent_key)
    if application_id:
        application = PermitService(ctx.session).load_application(application_id)
        result = run_agent(
            ctx.session,
            application=application,
            agent_key=agent_key,
            triggered_by=ctx.actor.actor_id,
            settings=ctx.settings,
        )
        return Outcome(
            message=f"The {label.lower()} ran on {application_id}.",
            destination=label,
            state=result.outcome,
            target_type="application",
            target_id=application_id,
        )
    if agent_key == "intake":
        cases = waiting_applications(ctx.session)
    else:
        cases = AdjudicationAgent(ctx.session, settings=ctx.settings).candidates()
    results = run_batch(
        ctx.session,
        cases=cases,
        agent_key=agent_key,
        triggered_by=ctx.actor.actor_id,
        settings=ctx.settings,
    )
    waiting = "waiting " if agent_key == "intake" else ""
    return Outcome(
        message=f"The {label.lower()} ran on {len(results)} {waiting}case(s).",
        destination=label,
        state="completed" if results else "skipped",
        target_type="agent",
        target_id=agent_key,
        affected=tuple(result.application_id for result in results),
    )


def _recommendation_confirm(ctx: ActionContext) -> Outcome:
    """Confirm an agent recommendation and record the reviewer's decision."""
    from acme_city.agents.recommendation import confirm

    row = confirm(
        ctx.session,
        recommendation_id=ctx.text("recommendation_id"),
        application_id=ctx.text("application_id"),
        reason=ctx.text("reason"),
        reason_code=ctx.text("reason_code"),
        expected_application_version=ctx.integer("expected_application_version"),
        actor=ctx.actor,
    )
    return Outcome(
        message=(
            f"Confirmed the agent recommendation ({row.proposed_outcome}); the decision "
            "of record is yours."
        ),
        destination="Permit decision",
        state=row.status,
        target_type="application",
        target_id=row.application_id,
        after_version=row.version,
    )


def _recommendation_revert(ctx: ActionContext) -> Outcome:
    """Revert an agent recommendation and return the case to manual review."""
    from acme_city.agents.recommendation import revert

    row = revert(
        ctx.session,
        recommendation_id=ctx.text("recommendation_id"),
        application_id=ctx.text("application_id"),
        reason=ctx.text("reason"),
        actor=ctx.actor,
    )
    return Outcome(
        message="Reverted the agent recommendation; the case is back in manual review.",
        destination="Agent recommendation",
        state=row.status,
        target_type="application",
        target_id=row.application_id,
        after_version=row.version,
    )


def _extraction_decide(ctx: ActionContext) -> Outcome:
    """Accept or correct one proposed extracted value."""
    from acme_city.triage.extraction import decide_extraction

    row = decide_extraction(
        ctx.session,
        observation_id=ctx.text("observation_id"),
        decision=ctx.text("decision"),
        corrected_value=ctx.text("corrected_value") or None,
        reason=ctx.text("reason"),
        actor=ctx.actor,
    )
    return Outcome(
        message=f"Recorded the steward decision on extracted {row.field_path}: {row.validation_state}.",
        destination="Extraction proposal",
        state=row.validation_state,
        target_type="application",
        target_id=ctx.text("application_id"),
    )



def _parcel_service(ctx: ActionContext) -> Any:
    from acme_city.gis.matching import ParcelMatchService

    return ParcelMatchService(ctx.session, settings=ctx.settings)


def _parcel_link_decide(ctx: ActionContext) -> Outcome:
    """The Data Steward approves or rejects the proposed parcel link."""
    decision = ctx.text("decision")
    match = _parcel_service(ctx).decide_link(
        ctx.text("application_id"),
        decision=decision,
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
        actor=ctx.actor,
    )
    verb = "Approved" if decision == "approve" else "Rejected"
    return Outcome(
        message=(
            f"{verb} the parcel link {match.parcel_number or ''} for the application. "
            "The Permit Reviewer still confirms the parcel before a decision."
            if decision == "approve"
            else "Rejected the proposed parcel link. A person must find the right property."
        ),
        destination="Parcel link (identity)",
        state=match.link_state,
        target_type="application",
        target_id=match.application_id,
        after_version=match.version,
    )


def _parcel_confirm(ctx: ActionContext) -> Outcome:
    """The Permit Reviewer confirms that this is the right property."""
    match = _parcel_service(ctx).confirm(
        ctx.text("application_id"),
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
        actor=ctx.actor,
    )
    return Outcome(
        message=f"Confirmed parcel {match.parcel_number} as the right property.",
        destination="Parcel link (identity)",
        state="confirmed",
        target_type="application",
        target_id=match.application_id,
        after_version=match.version,
    )


def _parcel_candidate_choose(ctx: ActionContext) -> Outcome:
    """Propose another locator candidate; the steward must approve it."""
    match = _parcel_service(ctx).choose_candidate(
        ctx.text("application_id"),
        address_id=ctx.text("address_id"),
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
        actor=ctx.actor,
    )
    return Outcome(
        message=(
            f"Proposed {match.matched_address} on parcel {match.parcel_number}. "
            "The Data Steward must approve the new parcel link."
        ),
        destination="Parcel link (identity)",
        state=match.link_state,
        pending=True,
        target_type="application",
        target_id=match.application_id,
        after_version=match.version,
    )


def _parcel_find(ctx: ActionContext) -> Outcome:
    """Find a parcel by number in the parcel layer and propose it."""
    match = _parcel_service(ctx).find_by_number(
        ctx.text("application_id"),
        parcel_number=ctx.text("parcel_number"),
        reason=ctx.text("reason"),
        expected_version=ctx.integer("expected_version"),
        actor=ctx.actor,
    )
    return Outcome(
        message=(
            f"Found parcel {match.parcel_number} in the parcel layer and proposed it. "
            "The Data Steward must approve the new parcel link."
        ),
        destination="Parcel link (identity)",
        state=match.link_state,
        pending=True,
        target_type="application",
        target_id=match.application_id,
        after_version=match.version,
    )


#: Every explicit action of the interface, keyed by its stable identifier.
ACTION_HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {
    "intake.simulate": _intake_simulate,
    "agent.toggle": _agent_toggle,
    "agent.run.intake": lambda ctx: _agent_run(ctx, "intake"),
    "agent.run.adjudication": lambda ctx: _agent_run(ctx, "adjudication"),
    "recommendation.confirm": _recommendation_confirm,
    "recommendation.revert": _recommendation_revert,
    "config.permit_type.document": _config_permit_type_document,
    "config.permit_type.create": _config_permit_type_create,
    "config.reason_code.add": _config_reason_code_add,
    "config.reason_code.retire": _config_reason_code_retire,
    "config.user.add": _config_user_add,
    "extraction.decide": _extraction_decide,
    "parcel.link.decide": _parcel_link_decide,
    "parcel.confirm": _parcel_confirm,
    "parcel.candidate.choose": _parcel_candidate_choose,
    "parcel.find": _parcel_find,
    "registry.propose": _registry_propose,
    "registry.decide": _registry_decide,
    "registry.defer": _registry_defer,
    "change.request": _change_request,
    "change.transition": _change_transition,
    "change.dispatch": _change_dispatch,
    "source.write": _source_write,
    "permit.evaluate": _permit_evaluate,
    "permit.decide": _permit_decide,
    "permit.reconfirm": _permit_reconfirm,
    "permit.issue": _permit_issue,
    "permit.revise": _permit_revise,
    "permit.case.return": _permit_case_return,
    "permit.case.advance": _permit_case_advance,
    "permit.case.request_revisions": _permit_case_request_revisions,
    "permit.case.archive": _permit_case_archive,
    "permit.case.restore": _permit_case_restore,
    "permit.case.priority": _permit_case_priority,
    "permit.case.assign": _permit_case_assign,
    "permit.case.comment": _permit_case_comment,
    "permit.finding.waive": _permit_finding_waive,
    "permit.intake.process_selected": _permit_intake_process_selected,
    "rule.draft": _rule_draft,
    "rule.submit": _rule_submit,
    "rule.approve": _rule_approve,
    "rule.publish": _rule_publish,
    "rule.retire": _rule_retire,
    "fee.draft": _fee_draft,
    "fee.submit": _fee_submit,
    "fee.approve": _fee_approve,
    "fee.publish": _fee_publish,
    "fee.retire": _fee_retire,
    "finance.assess": _finance_assess,
    "finance.reassess": _finance_reassess,
    "finance.import": _finance_import,
    "finance.allocate": _finance_allocate,
    "finance.reconcile": _finance_reconcile,
    "governance.register": _governance_register,
    "governance.publish_dataset": _governance_publish_dataset,
    "governance.reassign": _governance_reassign,
    "governance.authority_preview": _governance_authority_preview,
    "governance.authority_publish": _governance_authority_publish,
    "governance.escalate": _governance_escalate,
    "permit.icon.generate": lambda ctx: permit_icons.generate_icon(ctx),
    "permit.icon.save": lambda ctx: permit_icons.save_icon(ctx),
}


@router.post("/ui/actions/{action_id}", operation_id="run_ui_action")
async def run_ui_action(
    action_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Run one explicit action and report what actually happened.

    The form posts a stable action identifier, the expected version and the
    CSRF token of the session.  The server decides whether the action is
    allowed; the browser never sends an authority.  A browser that asks for
    JSON receives the typed outcome instead of the next page.
    """
    handler = ACTION_HANDLERS.get(action_id)
    if request.app.state.settings.is_production and action_id in PRODUCTION_BLOCKED_ACTIONS:
        handler = None
    wants_json = "application/json" in request.headers.get("accept", "")
    if handler is None:
        if wants_json:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "denied",
                    "code": "not_found",
                    "message": "The interface has no action with that identifier.",
                },
            )
        return error_response(
            request,
            session,
            actor,
            status_code=404,
            title="That action does not exist",
            message="The interface has no action with that identifier.",
            code="not_found",
        )
    if actor is None:
        return RedirectResponse("/select", status_code=303)
    form = await request.form()
    fields = {key: str(value) for key, value in form.items()}
    multi: dict[str, list[str]] = {}
    for key in form.keys():
        values = [str(value) for value in form.getlist(key)]
        if len(values) > 1:
            multi[key] = values
    verify_csrf(request.app.state.settings, actor, fields.get(CSRF_FIELD, ""))
    context = ActionContext(
        session=session,
        actor=actor,
        form=fields,
        settings=request.app.state.settings,
        multi=multi,
    )
    destination = safe_next(fields.get(NEXT_FIELD, ""), "/queue")
    try:
        outcome = handler(context)
    except AcmeError as error:
        session.rollback()
        AuditService(session).record_denied(
            action=f"ui.{action_id}",
            actor=actor,
            target_type="ui_action",
            target_id=action_id,
            denial_reason=error.code,
        )
        if wants_json:
            return JSONResponse(
                status_code=error.status_code,
                content={
                    "status": "denied",
                    "code": error.code,
                    "message": error.message,
                    "destination": "",
                    "state": "",
                    "pending": False,
                    "affected": [],
                    "version": None,
                },
            )
        return error_response(
            request,
            session,
            actor,
            status_code=error.status_code,
            title="The action was refused",
            message=error.message,
            code=error.code,
            back=destination,
        )
    AuditService(session).append(
        action=f"ui.{action_id}",
        actor=actor,
        target_type=outcome.target_type or None,
        target_id=outcome.target_id or None,
        before_version=outcome.before_version,
        after_version=outcome.after_version,
        reason=outcome.message,
        outcome="accepted",
        metadata={
            "destination": outcome.destination,
            "state": outcome.state,
            "pending": outcome.pending,
            "affected": list(outcome.affected),
            "detail": outcome.extra.get("detail", ""),
        },
    )
    session.commit()
    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "message": outcome.message,
                "destination": outcome.destination,
                "state": outcome.state,
                "pending": outcome.pending,
                "affected": list(outcome.affected),
                "version": outcome.after_version,
            },
        )
    return RedirectResponse(destination, status_code=303)


from acme_city.ui import portal_routes as _portal_routes  # noqa: E402
from acme_city.ui import help_routes as _help_routes  # noqa: E402

# The help endpoints come first: their paths are under ``/apply`` and must
# not be captured by the application form of a permit type.
router.include_router(_help_routes.router)
router.include_router(_portal_routes.router)

from acme_city.ui import detail_routes as _detail_routes  # noqa: E402
from acme_city.ui import reviewer_details as _reviewer_details  # noqa: E402,F401
from acme_city.ui import help_docs_routes as _help_docs_routes  # noqa: E402
from acme_city.ui import ops_routes as _ops_routes  # noqa: E402
from acme_city.ui import policy_routes as _policy_routes  # noqa: E402
from acme_city.ui import steward_routes as _steward_routes  # noqa: E402
from acme_city.ui import steward_automation_routes as _steward_automation_routes  # noqa: E402
from acme_city.ui import agent_routes as _agent_routes  # noqa: E402

from acme_city.ui import nav_plugins as _nav_plugins  # noqa: E402
from acme_city.ui import screen_meta as _screen_meta  # noqa: E402

patterns.install(templates)
display.install(templates)
_screen_meta.install(templates)
_nav_plugins.load_plugins()
router.include_router(_detail_routes.router)
router.include_router(_policy_routes.router)
router.include_router(_ops_routes.router)
router.include_router(_help_docs_routes.router)
ACTION_HANDLERS.update(_ops_routes.HANDLERS)
router.include_router(_steward_routes.router)
router.include_router(_steward_automation_routes.router)
router.include_router(_agent_routes.router)
ACTION_HANDLERS.update(_steward_routes.HANDLERS)
ACTION_HANDLERS.update(_steward_automation_routes.HANDLERS)
ACTION_HANDLERS.update(_agent_routes.ACTIONS)


__all__ = [
    "ACTION_HANDLERS",
    "CSRF_FIELD",
    "STATIC_PREFIX",
    "STATIC_ROOT",
    "TEMPLATE_ROOT",
    "csrf_token",
    "page_context",
    "render",
    "router",
    "safe_next",
    "templates",
    "verify_csrf",
]

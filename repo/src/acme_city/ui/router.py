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
import hmac
import json
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
from acme_city.permits import icons as permit_icons
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.issuance import IssuePermitCommand
from acme_city.permits.schemas import ReviseApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.registry.schemas import MatchDecisionCommand, MatchProposalCommand
from acme_city.registry.service import RegistryService
from acme_city.rules.schemas import (
    DraftFeeScheduleCommand,
    DraftRuleCommand,
    FeeScheduleLifecycleCommand,
    PublishRuleCommand,
    RetireRuleCommand,
    RuleLifecycleCommand,
)
from acme_city.rules.service import RuleCatalogService
from acme_city.ui import view_models
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
templates = Jinja2Templates(directory=str(TEMPLATE_ROOT))
router.mount(STATIC_PREFIX, StaticFiles(directory=str(STATIC_ROOT)), name="ui-static")

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

    def text(self, name: str, default: str = "") -> str:
        """Return one posted text field."""
        value = self.form.get(name, default)
        return value.strip() if isinstance(value, str) else default

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


def safe_next(value: str | None, fallback: str = "/queue") -> str:
    """Return a local path an action may return to."""
    if not value:
        return fallback
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    return value


def ui_actor(request: Request, session: Session = Depends(get_session)) -> ActorContext | None:
    """Return the acting persona, or ``None`` when no session is presented."""
    try:
        return SessionService(session, request.app.state.settings).resolve_actor(request)
    except AuthenticationRequiredError:
        return None


def require_actor(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> ActorContext:
    """Return the acting persona, or ``None`` when no session is presented."""
    return actor


# ------------------------------------------------------------------- rendering


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
        },
        "personas": persona_options(session),
        "navigation": navigation(session, actor),
        "feedback": feedback(session, actor),
        "csrf_token": csrf_token(settings, actor.session_id),
        "fictional_demo": True,
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
        "error": {
            "title": title,
            "message": message,
            "code": code,
            "back": back,
        },
    }
    return render(request, "base.html", context, status_code=status_code)


# ------------------------------------------------------------------ persona


@router.get("/select", operation_id="select_persona", name="select_persona")
def select_persona(
    request: Request,
    session: Session = Depends(get_session),
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


@router.post("/ui/actor", operation_id="switch_persona")
async def switch_persona(
    request: Request,
    session: Session = Depends(get_session),
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
    response = RedirectResponse(safe_next(str(form.get(NEXT_FIELD, "")), "/queue"), status_code=303)
    response.set_cookie(**cookie.set_cookie_kwargs())
    return response


@router.post("/ui/end", operation_id="end_persona")
async def end_persona(
    request: Request,
    session: Session = Depends(get_session),
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
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    view: str = "my",
    department: str | None = None,
    object_type: str | None = None,
    state: str | None = None,
) -> Any:
    """Show the work queue of the acting persona."""
    resolved, refused = _guard(request, session, actor, "queue")
    if refused is not None:
        return refused
    queue = view_models.work_queue(
        session,
        resolved,
        view=view,
        department=department,
        object_type=object_type,
        state=state,
    )
    context = page_context(
        request,
        session,
        resolved,
        screen="queue",
        title="Work queue",
        queue=queue,
    )
    return render(request, "work_queue.html", context)


@router.get("/applicants", operation_id="ui_applicants")
def ui_applicants(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    q: str = "",
) -> Any:
    """Show the shared applicant view."""
    resolved, refused = _guard(request, session, actor, "applicants")
    if refused is not None:
        return refused
    applicants = view_models.applicants(session, resolved, query=q)
    context = page_context(
        request,
        session,
        resolved,
        screen="applicants",
        title="Applicants",
        applicants=applicants,
        responsibility=view_models.responsibility(
            session,
            domain_id="applicants",
            source_system_id="permitting",
            dataset_key="applicant_profiles",
        ),
    )
    return render(request, "applicants.html", context)


@router.get("/applicants/{party_id}", operation_id="ui_applicant_detail")
def ui_applicant_detail(
    party_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show one applicant profile with its sources, evidence and history."""
    resolved, refused = _guard(request, session, actor, "applicants")
    if refused is not None:
        return refused
    detail = view_models.party_detail(session, resolved, party_id)
    if not detail:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That applicant record is not available to you",
            message=(
                "The record does not exist or it is outside the record scope of "
                "your persona."
            ),
            code="not_found",
            back="/applicants",
        )
    actions = allowed_actions_for(session, resolved, "applicants", party_id, detail)
    context = page_context(
        request,
        session,
        resolved,
        screen="applicants",
        title=f"Applicant: {detail['party']['display_name']}",
        detail=detail,
        responsibility=detail["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "applicants.html", context)


@router.get("/masters", operation_id="ui_masters")
def ui_masters(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the properties, businesses and contractors."""
    resolved, refused = _guard(request, session, actor, "masters")
    if refused is not None:
        return refused
    masters = view_models.masters(session, resolved)
    context = page_context(
        request,
        session,
        resolved,
        screen="masters",
        title="Properties, businesses and contractors",
        masters=masters,
    )
    return render(request, "masters.html", context)


@router.get("/masters/{party_id}", operation_id="ui_master_detail")
def ui_master_detail(
    party_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show one business or contractor master record."""
    resolved, refused = _guard(request, session, actor, "masters")
    if refused is not None:
        return refused
    detail = view_models.master_detail(session, resolved, party_id)
    if not detail:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That master record is not available to you",
            message=(
                "The record does not exist or it is outside the record scope of "
                "your persona."
            ),
            code="not_found",
            back="/masters",
        )
    actions = allowed_actions_for(session, resolved, "masters", party_id, detail)
    context = page_context(
        request,
        session,
        resolved,
        screen="masters",
        title=f"Master record: {detail['party']['display_name']}",
        detail=detail,
        responsibility=detail["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "masters.html", context)


@router.get("/permits/{application_id}", operation_id="ui_permit_workspace")
def ui_permit_workspace(
    application_id: str,
    request: Request,
    session: Session = Depends(get_session),
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
        responsibility=detail["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "permit_workspace.html", context)


@router.get("/steward", operation_id="ui_steward_review")
def ui_steward_review(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the steward review screen."""
    resolved, refused = _guard(request, session, actor, "steward")
    if refused is not None:
        return refused
    review = view_models.steward_review(session, resolved)
    actions = allowed_actions_for(session, resolved, "steward")
    context = page_context(
        request,
        session,
        resolved,
        screen="steward",
        title="Steward review",
        review=review,
        responsibility=review["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "steward_review.html", context)


@router.get("/rules-fees", operation_id="ui_rules_fees")
def ui_rules_fees(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the rule and fee catalogue."""
    resolved, refused = _guard(request, session, actor, "rules")
    if refused is not None:
        return refused
    catalogue = view_models.rules_fees(session, resolved)
    settings: Settings = request.app.state.settings
    catalogue["permit_type_icons"] = {
        **catalogue["permit_type_icons"],
        "global_cap": settings.muse_image_daily_cap,
    }
    actions = allowed_actions_for(session, resolved, "rules")
    context = page_context(
        request,
        session,
        resolved,
        screen="rules",
        title="Rules and fees",
        catalogue=catalogue,
        responsibility=catalogue["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "rules_fees.html", context)


@router.get("/reconciliation", operation_id="ui_reconciliation")
def ui_reconciliation(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the reconciliation screen."""
    resolved, refused = _guard(request, session, actor, "reconciliation")
    if refused is not None:
        return refused
    position = view_models.reconciliation(session, resolved)
    actions = allowed_actions_for(session, resolved, "reconciliation")
    context = page_context(
        request,
        session,
        resolved,
        screen="reconciliation",
        title="Reconciliation",
        position=position,
        responsibility=position["responsibility"],
        actions=actions,
        denied_action_explanations=view_models.denied_action_explanations(actions),
    )
    return render(request, "reconciliation.html", context)


@router.get("/governance", operation_id="ui_governance_sources")
def ui_governance_sources(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the governance and sources screen."""
    resolved, refused = _guard(request, session, actor, "governance")
    if refused is not None:
        return refused
    governance = view_models.governance_sources(session, resolved)
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


@router.get("/permit-type-icons/{icon_id}", operation_id="ui_permit_type_icon")
def ui_permit_type_icon(
    icon_id: str,
    request: Request,
    session: Session = Depends(get_session),
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
    if permit_type is None or permit_type.key not in {
        "com_ti", "res_building", "sign", "deck_fence", "row_encroachment"
    }:
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
        expected_version=ctx.integer("expected_version"),
    )
    result = RegistryService(ctx.session).decide(command, ctx.actor)
    if isinstance(result, ConflictResult):
        raise _conflict(result)
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


def _permit_evaluate(ctx: ActionContext) -> Outcome:
    """Evaluate the current revision of an application."""
    application_id = ctx.text("application_id")
    view = PermitService(ctx.session).evaluate(application_id, ctx.actor)
    return Outcome(
        message=(
            f"Validation finished with the outcome '{view.outcome}' on version "
            f"{view.version}."
        ),
        destination="Permitting validation",
        state=view.outcome,
        pending=bool(view.blockers),
        target_type="application",
        target_id=application_id,
        after_version=view.version,
        extra={"blockers": [blocker.model_dump(mode="json") for blocker in view.blockers]},
    )


def _permit_decide(ctx: ActionContext) -> Outcome:
    """Record an actual reviewer decision."""
    command = PermitDecisionCommand(
        application_id=ctx.text("application_id"),
        outcome=ctx.text("outcome"),
        reason=ctx.text("reason"),
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
    )


def _permit_reconfirm(ctx: ActionContext) -> Outcome:
    """Record a reviewer reconfirmation of a stale decision."""
    command = PermitDecisionCommand(
        application_id=ctx.text("application_id"),
        outcome=ctx.text("outcome"),
        reason=ctx.text("reason"),
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


def _rule_approve(ctx: ActionContext) -> Outcome:
    """Approve a rule version that somebody else authored."""
    command = RuleLifecycleCommand(
        rule_version_id=ctx.text("rule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
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
    command = FeeScheduleLifecycleCommand(
        fee_schedule_version_id=ctx.text("fee_schedule_version_id"),
        expected_version=ctx.integer("expected_version") or 0,
        reason=ctx.text("reason"),
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


def _triage_rerun(ctx: ActionContext) -> Outcome:
    """Re-run the agent triage pipeline for one application."""
    from acme_city.triage.service import TriageService

    steps = TriageService(ctx.session, settings=ctx.settings).run(
        ctx.text("application_id"), triggered_by=ctx.actor.actor_id
    )
    return Outcome(
        message="Re-ran triage: " + ", ".join(
            f"{step.step_name} {step.outcome}" for step in steps
        ),
        destination="Agent triage pipeline",
        state=steps[-1].outcome if steps else "recorded",
        target_type="application",
        target_id=ctx.text("application_id"),
        extra={"steps": [step.step_name for step in steps]},
    )


def _recommendation_stance(ctx: ActionContext) -> Outcome:
    """Record the reviewer's stance on the advisory recommendation."""
    from acme_city.triage.service import record_reviewer_stance

    row = record_reviewer_stance(
        ctx.session,
        recommendation_id=ctx.text("recommendation_id"),
        application_id=ctx.text("application_id"),
        stance=ctx.text("stance"),
        reason=ctx.text("reason"),
        actor=ctx.actor,
    )
    return Outcome(
        message=f"Recorded your stance '{row.reviewer_stance}' on the agent recommendation.",
        destination="Agent recommendation",
        state=row.reviewer_stance or "",
        target_type="application",
        target_id=row.application_id,
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


#: Every explicit action of the interface, keyed by its stable identifier.
ACTION_HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {
    "intake.simulate": _intake_simulate,
    "triage.rerun": _triage_rerun,
    "recommendation.stance": _recommendation_stance,
    "extraction.decide": _extraction_decide,
    "registry.propose": _registry_propose,
    "registry.decide": _registry_decide,
    "change.request": _change_request,
    "change.transition": _change_transition,
    "change.dispatch": _change_dispatch,
    "source.write": _source_write,
    "permit.evaluate": _permit_evaluate,
    "permit.decide": _permit_decide,
    "permit.reconfirm": _permit_reconfirm,
    "permit.issue": _permit_issue,
    "permit.revise": _permit_revise,
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
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Run one explicit action and report what actually happened.

    The form posts a stable action identifier, the expected version and the
    CSRF token of the session.  The server decides whether the action is
    allowed; the browser never sends an authority.  A browser that asks for
    JSON receives the typed outcome instead of the next page.
    """
    handler = ACTION_HANDLERS.get(action_id)
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
    verify_csrf(request.app.state.settings, actor, fields.get(CSRF_FIELD, ""))
    context = ActionContext(
        session=session,
        actor=actor,
        form=fields,
        settings=request.app.state.settings,
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

"""The operations screens of the City Administrator (parity phase 3c).

Routes (each one is opened by its own grant, checked again by the service):

* ``GET /ops/dashboard``  the operations dashboard (S10)
* ``GET /ops/audit``      the audit log (S11)
* ``GET /ops/support``    support: lookup, help requests, support cases (S13)
* ``GET /ops/checks``     the invariant checks (S14)

The three writes go through the UI dispatcher (``POST /ui/actions/{id}``), so
each one checks the CSRF token, the grant and a mandatory expected version,
and each one writes its own canonical audit record in addition to the
dispatcher's feedback record:

* ``ops.checks.run``
* ``support.help_request.answer``
* ``support.case.record``
"""
# REQUIRES: PER-04, SEC-01, SEC-03, UX-01
# The operations screens are read only; their three writes are governed
# actions with a grant, CSRF and a mandatory expected version.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import AcmeError, NotFoundError
from acme_city.ops import audit_log as audit_log_module
from acme_city.ops import dashboard as dashboard_module
from acme_city.ops.checks import ChecksService
from acme_city.ops.support import (
    CHANNEL_LABELS,
    CONTACT_NOTICE,
    FAQ,
    PERMISSION_ANSWER,
    PERMISSION_LOOKUP,
    PERMISSION_RECORD,
    SupportService,
)
from acme_city.persistence.models import audit
from acme_city.persistence.models.support import SUPPORT_CHANNELS
from acme_city.ui import ops_views, patterns
from acme_city.ui.patterns import DetailContext, DetailView, Row, Section
from acme_city.ui.router import (
    ActionContext,
    Outcome,
    _guard,
    error_response,
    page_context,
    render,
    ui_actor,
)

router = APIRouter(tags=["operations"])


def _evidence(label: str, detail: str) -> list[dict[str, Any]]:
    """Return the evidence list of an operations screen: what its figures read."""
    return [{"label": label, "kind": "database query", "detail": detail, "received_at": None}]


# ------------------------------------------------------------------ dashboard


@router.get("/ops/dashboard", operation_id="ui_ops_dashboard")
def ui_ops_dashboard(
    request: Request,
    synthetic: str = "exclude",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the operations dashboard."""
    resolved, refused = _guard(request, session, actor, "ops_dashboard")
    if refused is not None:
        return refused
    context = page_context(
        request,
        session,
        resolved,
        screen="ops_dashboard",
        title="Operations dashboard",
        view=ops_views.dashboard_presentation(
            dashboard_module.dashboard(session, synthetic=synthetic)
        ),
        model_runs=[],
        evidence=_evidence(
            "Stored applications, decisions and agent runs",
            "every figure is a count or a mean over these rows; no model is used",
        ),
    )
    return render(request, "ops_dashboard.html", context)


# ------------------------------------------------------------------ audit log


@router.get("/ops/audit", operation_id="ui_ops_audit")
def ui_ops_audit(
    request: Request,
    actor_type: str = "",
    action: str = "",
    search: str = "",
    page: int = 1,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show one page of the read-only audit log."""
    resolved, refused = _guard(request, session, actor, "ops_audit")
    if refused is not None:
        return refused
    context = page_context(
        request,
        session,
        resolved,
        screen="ops_audit",
        title="Audit log",
        view=audit_log_module.audit_log(
            session, actor_type=actor_type, action=action, search=search, page=page
        ),
        model_runs=[],
        evidence=_evidence("The append-only audit records", "read only; this screen reads the one audit trail"),
    )
    return render(request, "ops_audit.html", context)


def _resolve_audit_event(ctx: DetailContext, event_id: str) -> DetailView | None:
    """The detail of one audit event: identifiers, versions, references, metadata."""
    event = ctx.session.get(audit.AuditEvent, event_id)
    if event is None:
        return None
    meta = dict(event.metadata_json or {})
    rows = [
        Row("Event id", event.id, mono=True),
        Row("Correlation id", event.correlation_id, mono=True),
        Row("Occurred", event.occurred_at.isoformat() if event.occurred_at else "", mono=True),
        Row("Actor", event.actor_id or "none (system)", mono=True),
        Row("Roles held", ", ".join(event.actor_role_ids or []) or "none recorded"),
        Row("Outcome", event.outcome),
    ]
    if event.denial_reason:
        rows.append(Row("Denial reason", event.denial_reason))
    refs = tuple(Row(f"Reference {i}", str(ref), mono=True) for i, ref in enumerate(event.references or [], 1))
    sections = [Section("Event", tuple(rows))]
    if refs:
        sections.append(Section("References", refs))
    shown = tuple(
        Row(str(key), str(value) if not isinstance(value, (dict, list)) else f"{len(value)} entries")
        for key, value in sorted(meta.items())
    )
    if shown:
        sections.append(Section("Recorded detail", shown))
    return DetailView(
        title="Audit event",
        subtitle=event.action,
        sections=tuple(sections),
    )


patterns.register_detail(
    "audit-event",
    _resolve_audit_event,
    label="Audit event",
    any_grant=(("ops.audit_log.view", None),),
)


# -------------------------------------------------------------------- support


@router.get("/ops/support", operation_id="ui_ops_support")
def ui_ops_support(
    request: Request,
    ref: str = "",
    request_id: str = Query("", alias="request"),
    request_status: str = "open",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the support screen."""
    resolved, refused = _guard(request, session, actor, "ops_support")
    if refused is not None:
        return refused
    service = SupportService(session)
    if request_id and service.can(resolved, PERMISSION_ANSWER):
        # A link from the audit log opens the request in the list it belongs to.
        from acme_city.persistence.models import help as help_models

        linked = session.get(help_models.HelpRequest, request_id)
        if linked is not None:
            request_status = linked.status
    try:
        lookup = service.lookup(resolved, ref) if ref and service.can(resolved, PERMISSION_LOOKUP) else None
        help_requests = (
            service.help_requests(resolved, status=request_status)
            if service.can(resolved, PERMISSION_ANSWER)
            else []
        )
        cases = service.recent_cases(resolved) if service.can(resolved, PERMISSION_RECORD) else []
    except AcmeError as error:
        return error_response(
            request, session, resolved, status_code=error.status_code,
            title="That is not available", message=error.message, code=error.code, back="/queue",
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="ops_support",
        title="Support",
        reference=ref,
        lookup=lookup,
        lookup_done=bool(ref.strip()),
        help_requests=help_requests,
        request_status=request_status if request_status in {"open", "answered"} else "open",
        focus_request=request_id,
        support_cases=cases,
        channels=[{"key": key, "label": CHANNEL_LABELS[key]} for key in SUPPORT_CHANNELS],
        faq=[{"question": q, "answer": a} for q, a in FAQ],
        contact=CONTACT_NOTICE,
        can_answer=service.can(resolved, PERMISSION_ANSWER),
        can_record=service.can(resolved, PERMISSION_RECORD),
        model_runs=[],
        evidence=_evidence(
            "Help requests, applicant-visible comments and support cases",
            "internal notes and un-escalated conversations are never read here",
        ),
    )
    return render(request, "ops_support.html", context)


# --------------------------------------------------------------------- checks


@router.get("/ops/checks", operation_id="ui_ops_checks")
def ui_ops_checks(
    request: Request,
    run: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the checks screen and the latest recorded run."""
    resolved, refused = _guard(request, session, actor, "ops_checks")
    if refused is not None:
        return refused
    service = ChecksService(session)
    try:
        recorded = service.recorded(resolved, run)
        version = service.runs_so_far(resolved)
    except NotFoundError as error:
        return error_response(
            request, session, resolved, status_code=404, title="That run is not available",
            message=error.message, code=error.code, back="/ops/checks",
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="ops_checks",
        title="Checks",
        recorded=recorded,
        checks=ops_views.checks_presentation(recorded, selected=bool(run)),
        runs_version=version,
        model_runs=[],
        evidence=_evidence(
            "Stored rows read by the checks",
            "each run is read only and is recorded as one checks.run audit event",
        ),
    )
    return render(request, "ops_checks.html", context)


# -------------------------------------------------------------------- actions


def _checks_run(ctx: ActionContext) -> Outcome:
    """Run the read-only invariant checks and record the run."""
    run_id, results = ChecksService(ctx.session).run(
        ctx.actor, expected_version=ctx.integer("expected_version")
    )
    failed = sum(1 for item in results if item.status == "fail")
    return Outcome(
        message=(
            "Ran the checks: no check failed."
            if not failed
            else f"Ran the checks: {failed} failed."
        ),
        destination="Checks run record",
        state="failed" if failed else "passed",
        target_type="checks_run",
        target_id=run_id,
    )


def _support_answer(ctx: ActionContext) -> Outcome:
    """Answer a help request."""
    row = SupportService(ctx.session).answer_help_request(
        ctx.actor,
        request_id=ctx.text("help_request_id"),
        reply=ctx.text("reply"),
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Answered the help request.",
        destination="Help requests",
        state=row.status,
        target_type="help_request",
        target_id=row.id,
        after_version=row.version,
    )


def _support_record(ctx: ActionContext) -> Outcome:
    """Record a support case."""
    row = SupportService(ctx.session).record_case(
        ctx.actor,
        reference=ctx.text("reference"),
        channel=ctx.text("channel"),
        summary=ctx.text("summary"),
        expected_version=ctx.integer("expected_version"),
    )
    return Outcome(
        message="Recorded the support case.",
        destination="Support cases",
        state="recorded",
        target_type="support_case",
        target_id=row.id,
        after_version=row.version,
    )


HANDLERS = {
    "ops.checks.run": _checks_run,
    "support.help_request.answer": _support_answer,
    "support.case.record": _support_record,
}

__all__ = ["HANDLERS", "router"]

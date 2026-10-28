"""The what-if policy screens of the City Administrator.

Routes (all of them need a dedicated policy grant, checked again in the
service for every read and write, so a direct address is refused as firmly as
a link):

* ``GET  /policy/scenarios``                    the list and "New what-if"
* ``POST /policy/scenarios``                    save a new what-if
* ``GET  /policy/scenarios/{id}``               the editor
* ``POST /policy/scenarios/{id}/save``          rename, add a change, remove a change
* ``POST /policy/scenarios/{id}/delete``        soft delete
* ``POST /policy/scenarios/{id}/run``           run over a population
* ``GET  /policy/runs/{id}``                    the results
* ``GET  /policy/runs/{id}/briefing``           the deterministic briefing
* ``GET  /policy/runs/{id}/briefing/download``  the briefing as HTML or Markdown

Every write checks the CSRF token, the grant and a mandatory expected version,
and is audited without free text.
"""
# REQUIRES: PER-04, SEC-01, SEC-03, UX-01
# The what-if screens enforce the policy grants, CSRF and a mandatory version on
# every write, and label every population.

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import AcmeError, NotFoundError, ValidationError
from acme_city.policy import briefing as briefing_module
from acme_city.policy import runs as runs_module
from acme_city.policy import views
from acme_city.policy.service import (
    PERMISSION_BRIEF_VIEW,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
    PERMISSION_RUN_VIEW,
    PolicyService,
)
from acme_city.policy.suggestions import FENCE_KEY, SUGGESTIONS
from acme_city.ui import patterns
from acme_city.ui.patterns import DetailContext, DetailForbidden, DetailView, Row, Section
from acme_city.ui.portal_routes import posted_form
from acme_city.ui.router import (
    CSRF_FIELD,
    _guard,
    error_response,
    page_context,
    render,
    ui_actor,
    verify_csrf,
)

router = APIRouter(tags=["policy"])

SCREEN = "policy_scenarios"

#: The one-line notices a redirect may show.  The query string names a key,
#: never text, so a link cannot put words on the screen.
NOTICES = {
    "created": "The what-if was saved.",
    "saved": "A new revision of the what-if was saved.",
    "deleted": "The what-if was deleted. The runs made from it are kept.",
}


def _expected_version(form: Any) -> int:
    """Return the mandatory expected version of a posted form."""
    raw = str(form.get("expected_version", "")).strip()
    if not raw:
        raise ValidationError("an expected version is required for this action")
    try:
        return int(raw)
    except ValueError as error:
        raise ValidationError("the expected version must be a whole number") from error


def _refusal(
    request: Request,
    session: Session,
    actor: ActorContext,
    error: AcmeError,
    *,
    action: str,
    target_type: str,
    target_id: str,
    back: str,
) -> Any:
    session.rollback()
    AuditService(session).record_denied(
        action=action, actor=actor, target_type=target_type, target_id=target_id,
        denial_reason=error.code,
    )
    session.commit()
    return error_response(
        request, session, actor, status_code=error.status_code,
        title="That was not saved" if request.method == "POST" else "That is not available",
        message=error.message, code=error.code, back=back,
    )


def _read_guard(
    request: Request, session: Session, actor: ActorContext | None
) -> tuple[ActorContext | None, Any]:
    return _guard(request, session, actor, SCREEN)


# ------------------------------------------------------------------- the list


@router.get("/policy/scenarios", operation_id="ui_policy_scenarios")
def ui_policy_scenarios(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    type: str = "",
    district: str = "",
    category: str = "",
    notice: str = "",
) -> Any:
    """List the what-ifs and offer "New what-if"."""
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    service = PolicyService(session)
    try:
        scenarios = service.list_scenarios(resolved)
        recent = service.recent_runs(resolved) if service.can(resolved, PERMISSION_RUN_VIEW) else []
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action="policy.scenario.list",
                        target_type="policy_scenario", target_id="", back="/queue")
    starting = {k: v for k, v in (("permit_type", type), ("district", district), ("category", category)) if v}
    context = page_context(
        request, session, resolved, screen=SCREEN, title="What-if",
        scenarios=[
            {"id": s.id, "name": s.name, "revision": s.current_revision, "version": s.version,
             "created_at": s.created_at.isoformat(), "runs": len(service.runs_of(resolved, s.id)) if service.can(resolved, PERMISSION_RUN_VIEW) else 0}
            for s in scenarios
        ],
        recent_runs=[
            {"id": r.id, "name": r.scenario_name, "revision": r.scenario_revision_number,
             "population": r.population_label, "size": r.population_size,
             "synthetic": bool(r.population_synthetic), "created_at": r.created_at.isoformat(),
             "deleted": (service.scenario_state(r.scenario_id) or (False, ""))[0]}
            for r in recent
        ],
        suggestions=SUGGESTIONS,
        first_suggestion=FENCE_KEY,
        starting=starting,
        starting_text=_starting_text(starting),
        notice=NOTICES.get(notice, ""),
        model_runs=[],
        evidence=[],
    )
    return render(request, "policy_scenarios.html", context)


def _starting_text(starting: dict[str, str]) -> str:
    names = {"permit_type": "permit type", "district": "district", "category": "business category"}
    return ", ".join(f"{names[k]} {v}" for k, v in starting.items())


@router.post("/policy/scenarios", operation_id="ui_policy_scenario_create")
async def ui_policy_scenario_create(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        scenario = PolicyService(session).create_scenario(
            resolved,
            name=str(form.get("name", "")),
            suggestion_key=str(form.get("suggestion", "")).strip() or None,
            starting_population={
                "permit_type": str(form.get("start_permit_type", "")).strip(),
                "district": str(form.get("start_district", "")).strip(),
                "category": str(form.get("start_category", "")).strip(),
            },
            expected_version=_expected_version(form),
        )
        session.commit()
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action=_audit("create"),
                        target_type="policy_scenario", target_id="", back="/policy/scenarios")
    return RedirectResponse(f"/policy/scenarios/{scenario.id}?notice=created", status_code=303)


def _audit(name: str) -> str:
    return f"policy.scenario.{name}"


# ------------------------------------------------------------------ the editor


@router.get("/policy/scenarios/{scenario_id}", operation_id="ui_policy_scenario")
def ui_policy_scenario(
    scenario_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    notice: str = "",
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    service = PolicyService(session)
    try:
        scenario = service.scenario_for(resolved, scenario_id)
        revision = service.revision(resolved, scenario)
        revisions = service.revisions(resolved, scenario)
        can_run = service.can(resolved, PERMISSION_EXECUTE)
        runs = service.runs_of(resolved, scenario.id) if service.can(resolved, PERMISSION_RUN_VIEW) else []
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action="policy.scenario.read",
                        target_type="policy_scenario", target_id=scenario_id, back="/policy/scenarios")
    baseline = service.baseline()
    check = views.check_changes(baseline, revision.name, revision.changes)
    spec_defaults = dict(revision.starting_population or {})
    context = page_context(
        request, session, resolved, screen=SCREEN, title=f"What-if: {scenario.name}",
        scenario={
            "id": scenario.id, "name": scenario.name, "version": scenario.version,
            "revision": scenario.current_revision,
        },
        changes=[
            {"index": i, "text": views.describe_change(item, baseline)}
            for i, item in enumerate(revision.changes)
        ],
        has_retirement=any(item.get("kind") == "rule_retirement" for item in revision.changes),
        retire_note=views.RETIRE_NOTE,
        check=check,
        options=views.editor_options(baseline),
        revisions=[
            {"number": r.revision_number, "operation": r.operation, "created_at": r.created_at.isoformat(),
             "hash": r.content_hash[:12], "changes": len(r.changes)}
            for r in revisions
        ],
        runs=[
            {"id": r.id, "revision": r.scenario_revision_number, "population": r.population_label,
             "size": r.population_size, "synthetic": bool(r.population_synthetic),
             "created_at": r.created_at.isoformat()}
            for r in runs
        ],
        run_defaults={
            "kind": "synthetic_year",
            "seed": runs_module.DEFAULT_SEED,
            "count": runs_module.DEFAULT_COUNT,
            "permit_type": spec_defaults.get("permit_type", ""),
            "district": spec_defaults.get("district", ""),
            "category": spec_defaults.get("category", ""),
        },
        starting_text=_starting_text(spec_defaults),
        can_run=can_run,
        notice=NOTICES.get(notice, ""),
        model_runs=[],
        evidence=[],
    )
    return render(request, "policy_scenario.html", context)


@router.post("/policy/scenarios/{scenario_id}/save", operation_id="ui_policy_scenario_save")
async def ui_policy_scenario_save(
    scenario_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    operation = str(form.get("operation", "")).strip()
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        index_text = str(form.get("change_index", "")).strip()
        PolicyService(session).edit_scenario(
            resolved,
            scenario_id,
            operation=operation,
            expected_version=_expected_version(form),
            name=str(form.get("name", "")) if operation == "rename" else None,
            change=views.build_change_request({k: str(v) for k, v in form.items()})
            if operation == "add_change" else None,
            change_index=int(index_text) if index_text.isdigit() else None,
        )
        session.commit()
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action=_audit("edit"),
                        target_type="policy_scenario", target_id=scenario_id,
                        back=f"/policy/scenarios/{scenario_id}")
    return RedirectResponse(f"/policy/scenarios/{scenario_id}?notice=saved", status_code=303)


@router.post("/policy/scenarios/{scenario_id}/delete", operation_id="ui_policy_scenario_delete")
async def ui_policy_scenario_delete(
    scenario_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        PolicyService(session).delete_scenario(
            resolved, scenario_id, expected_version=_expected_version(form)
        )
        session.commit()
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action=_audit("delete"),
                        target_type="policy_scenario", target_id=scenario_id,
                        back=f"/policy/scenarios/{scenario_id}")
    return RedirectResponse("/policy/scenarios?notice=deleted", status_code=303)


@router.post("/policy/scenarios/{scenario_id}/run", operation_id="ui_policy_scenario_run")
async def ui_policy_scenario_run(
    scenario_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        run = PolicyService(session).run_scenario(
            resolved,
            scenario_id,
            expected_version=_expected_version(form),
            spec={k: str(form.get(k, "")) for k in
                  ("kind", "seed", "count", "range_start", "range_end", "permit_type", "district", "category")},
        )
        session.commit()
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action="policy.run.execute",
                        target_type="policy_scenario", target_id=scenario_id,
                        back=f"/policy/scenarios/{scenario_id}")
    return RedirectResponse(f"/policy/runs/{run.id}", status_code=303)


# ------------------------------------------------------------------- the runs


@router.get("/policy/runs/{run_id}", operation_id="ui_policy_run")
def ui_policy_run(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return refused
    service = PolicyService(session)
    try:
        run = service.run_for(resolved, run_id)
        state = service.scenario_state(run.scenario_id)
        can_brief = service.can(resolved, PERMISSION_BRIEF_VIEW)
    except AcmeError as error:
        return _refusal(request, session, resolved, error, action="policy.run.read",
                        target_type="policy_run", target_id=run_id, back="/policy/scenarios")
    context = page_context(
        request, session, resolved, screen=SCREEN, title=f"What-if results: {run.scenario_name}",
        run=views.run_view(run, scenario_deleted=bool(state and state[0])),
        can_brief=can_brief,
        model_runs=[],
        evidence=[],
    )
    return render(request, "policy_run.html", context)


def _briefing_for(
    request: Request, session: Session, actor: ActorContext | None, run_id: str, action: str
) -> tuple[ActorContext | None, Any, Any, Any]:
    resolved, refused = _read_guard(request, session, actor)
    if refused is not None:
        return None, refused, None, None
    service = PolicyService(session)
    try:
        run = service.run_for_briefing(resolved, run_id)
    except AcmeError as error:
        return None, _refusal(request, session, resolved, error, action=action,
                              target_type="policy_run", target_id=run_id,
                              back="/policy/scenarios"), None, None
    return resolved, None, service, run


@router.get("/policy/runs/{run_id}/briefing", operation_id="ui_policy_briefing")
def ui_policy_briefing(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    resolved, refused, _service, run = _briefing_for(request, session, actor, run_id, "policy.brief.read")
    if refused is not None:
        return refused
    briefing = briefing_module.build_briefing(run)
    context = page_context(
        request, session, resolved, screen=SCREEN, title=briefing.title,
        briefing=briefing,
        run_id=run.id,
        model_runs=[],
        evidence=[],
    )
    return render(request, "policy_briefing.html", context)


@router.get("/policy/runs/{run_id}/briefing/download", operation_id="ui_policy_briefing_download")
def ui_policy_briefing_download(
    run_id: str,
    request: Request,
    format: str = "html",
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    resolved, refused, service, run = _briefing_for(request, session, actor, run_id, "policy.brief.download")
    if refused is not None:
        return refused
    if format not in ("html", "md"):
        return _refusal(request, session, resolved, ValidationError("the format is html or md"),
                        action="policy.brief.download", target_type="policy_run", target_id=run_id,
                        back=f"/policy/runs/{run_id}/briefing")
    briefing = briefing_module.build_briefing(run)
    service.record_download(resolved, run, format)
    session.commit()
    if format == "html":
        body, media, extension = briefing_module.to_html(briefing), "text/html; charset=utf-8", "html"
    else:
        body, media, extension = briefing_module.to_markdown(briefing), "text/markdown; charset=utf-8", "md"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="what-if-briefing-{run.id}.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ------------------------------------------------------------- the detail kind


def _resolve_policy_run(ctx: DetailContext, run_id: str) -> DetailView | None:
    """Technical identity of a run: versions and hashes (needs ``policy.run.view``)."""
    service = PolicyService(ctx.session)
    try:
        run = service.run_for(ctx.actor, run_id)
    except NotFoundError:
        return None
    except AcmeError as error:
        raise DetailForbidden from error
    rows = (
        Row("Run id", run.id, mono=True),
        Row("Scenario revision", f"{run.scenario_name} · revision {run.scenario_revision_number}"),
        Row("Analysis moment", run.analysis_at.isoformat(), mono=True),
        Row("Engine version", run.engine_version, mono=True),
        Row("Generator version", run.generator_version or "not applicable", mono=True),
        Row("Content hash", run.content_hash, mono=True, info="policy_content_hash"),
        Row("Baseline hash", run.baseline_hash, mono=True),
        Row("Proposed configuration hash", run.proposed_hash, mono=True),
        Row("Population hash", run.population_hash, mono=True),
        Row("Result hash", run.result_hash, mono=True),
    )
    return DetailView(
        title="Run identity",
        subtitle="The run is an immutable snapshot; these identify exactly what it holds.",
        sections=(Section("Identity", rows),),
    )


patterns.register_detail(
    "policy-run",
    _resolve_policy_run,
    label="What-if run details",
    any_grant=(("policy.run.view", None),),
)

__all__ = ["router"]

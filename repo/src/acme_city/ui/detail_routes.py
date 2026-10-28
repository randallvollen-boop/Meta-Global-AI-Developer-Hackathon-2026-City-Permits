"""The detail flyout route and the detail kinds that ship with the app.

``GET /detail/{kind}/{item_id}`` returns the HTML of the drawer for one
address.  It resolves through ``patterns.resolve``, so the same grants and the
same record scope apply as when a page is opened with ``?detail=``.  A refusal
returns its status (401, 403, 404) and a body that names no record value.

To add a kind, call ``patterns.register_detail`` with a resolver (see the
docstring there); nothing else changes.
"""
# REQUIRES: UX-01, UX-02, SEC-01

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.muse.schemas import PRIVATE_TASKS
from acme_city.auth.router import get_session
from acme_city.persistence.models import model_run, permit, registry, source
from acme_city.ui import patterns, view_models
from acme_city.ui.patterns import (
    DetailContext,
    DetailForbidden,
    DetailView,
    Row,
    Section,
)

router = APIRouter(tags=["ui"])


def render_drawer_inner(templates: Any, state: dict[str, Any]) -> str:
    """Render the inside of the drawer for one resolved state."""
    module = templates.env.get_template("_ui.html").module
    return str(module.drawer_inner(state))


@router.get("/detail/{kind}/{item_id}", operation_id="ui_detail", include_in_schema=False)
def ui_detail(
    kind: str,
    item_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Return the drawer fragment for one detail address."""
    from acme_city.ui.router import safe_next, templates, ui_actor

    resolved_actor = ui_actor(request, session)
    outcome = patterns.resolve(request, session, resolved_actor, kind, item_id)
    state = {
        "status": outcome.status,
        "kind": kind,
        "id": item_id,
        "view": outcome.view,
        "message": outcome.message,
        "close_href": safe_next(request.query_params.get("from"), "/"),
    }
    state["tabs"] = patterns.tab_links(outcome.view, str(state["close_href"]))
    return HTMLResponse(
        render_drawer_inner(templates, state),
        status_code=outcome.status,
        headers={"Cache-Control": "no-store"},
    )


# ------------------------------------------------------------------------ help


def _resolve_help(ctx: DetailContext, screen: str) -> DetailView | None:
    entry = patterns.screen_help(screen)
    if entry is None:
        return None
    # A staff screen's help is shown only to a persona that may open the screen.
    needed = view_models.SCREEN_PERMISSIONS.get(screen)
    if needed and not any(
        view_models.holds_grant(ctx.session, ctx.actor, permission, domain)
        for permission, domain in needed
    ):
        raise DetailForbidden
    sections = [Section("What this screen is for", lines=(entry["purpose"],))]
    if entry.get("can_do"):
        sections.append(Section("What you can do here", lines=tuple(entry["can_do"])))
    if entry.get("next"):
        sections.append(Section("What usually happens next", lines=(entry["next"],)))
    links = tuple((item["label"], item["href"]) for item in entry.get("links", ()))
    return DetailView(title=f"Help: {entry['title']}", sections=tuple(sections), links=links)


patterns.register_detail("help", _resolve_help, label="Help", public=True)


# --------------------------------------------------------------- Muse run detail


def _resolve_muse_run(ctx: DetailContext, run_id: str) -> DetailView | None:
    """Muse run details: model, usage, latency, prompt version and hashes.

    Staff only.  The run must belong to an application inside the persona's
    record scope; otherwise the answer is "not available", never the run.
    """
    from acme_city.permits.comments import is_staff

    if not is_staff(ctx.session, ctx.actor):
        raise DetailForbidden
    run = ctx.session.execute(
        select(model_run.ModelRun).where(model_run.ModelRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        return None
    refs = run.input_refs if isinstance(run.input_refs, dict) else {}
    if str(refs.get("task") or "") in PRIVATE_TASKS:
        # A run of the applicant help assistant is the record of a private
        # conversation.  Staff never open it.
        return None
    application = ctx.session.execute(
        select(permit.Application).where(permit.Application.id == refs.get("application_id"))
    ).scalar_one_or_none()
    if application is None or not view_models._application_in_scope(ctx.actor, application):
        return None
    usage = dict(run.usage or {})
    iso = view_models._iso
    run_rows = [
        Row("Result label", run.mode.capitalize(), info="muse_provenance"),
        Row("Outcome", run.status),
        Row("Provider", run.provider or "not recorded"),
        Row("Model", run.model or "not recorded"),
        Row("Prompt version", run.prompt_version or "not recorded", info="prompt_version"),
        Row("Schema version", run.schema_version or "not recorded"),
        Row("Latency", f"{run.latency_ms} ms" if run.latency_ms is not None else "not recorded"),
        Row("Input tokens", str(usage.get("input_tokens", 0))),
        Row("Output tokens", str(usage.get("output_tokens", 0))),
    ]
    if usage.get("reasoning_tokens") is not None:
        run_rows.append(Row("Reasoning tokens", str(usage["reasoning_tokens"])))
    id_rows = [Row("Run id", run.id, mono=True, info="muse_run")]
    if run.provider_response_id:
        id_rows.append(Row("Response id", run.provider_response_id, mono=True))
    if run.replay_of_run_id:
        id_rows.append(Row("Replay of run", run.replay_of_run_id, mono=True))
    id_rows += [
        Row("Application", application.source_application_number, mono=True),
        Row("Started", iso(run.started_at) or "not recorded", mono=True),
        Row("Completed", iso(run.completed_at) or "not recorded", mono=True),
        Row("Run by", view_models.actor_label(ctx.session, run.actor_id)),
    ]
    sections = [Section("Run", tuple(run_rows)), Section("Identifiers and times", tuple(id_rows))]
    documents = refs.get("documents") or []
    if documents:
        sections.append(
            Section(
                "Documents read",
                tuple(
                    Row(
                        f"{doc.get('document_type', 'document')} v{doc.get('version', '?')}",
                        str(doc.get("content_hash", "")),
                        mono=True,
                        info="content_hash",
                    )
                    for doc in documents
                    if isinstance(doc, dict)
                ),
            )
        )
    return DetailView(
        title="Muse run details",
        subtitle=f"{run.mode.capitalize()} result for {application.source_application_number}",
        sections=tuple(sections),
    )


patterns.register_detail(
    "muse-run",
    _resolve_muse_run,
    label="Muse run details",
    any_grant=view_models.SCREEN_PERMISSIONS["permit"],
)

# ------------------------------------------------------------ My permits record


def _resolve_my_permit(ctx: DetailContext, reference: str) -> DetailView | None:
    """The applicant's own record details: reference, id, full times and revision.

    Only an application inside the persona's record scope is readable; any
    other reference answers "not available".  Nothing the City wrote internally
    is read.
    """
    from acme_city.applicant_portal.permits_view import long_stamp
    from acme_city.applicant_portal.service import STATUS_WORDS

    application = ctx.session.execute(
        select(permit.Application).where(permit.Application.source_application_number == reference)
    ).scalar_one_or_none()
    if application is None or not view_models._application_in_scope(ctx.actor, application):
        return None
    permit_type = ctx.session.get(permit.PermitType, application.permit_type_id)
    rows = [
        Row("Reference", application.source_application_number, mono=True),
        Row("Project type", permit_type.label if permit_type else "not recorded"),
        Row("Status", STATUS_WORDS.get(application.status, application.status), info="application_status"),
        Row("First submitted", long_stamp(application.initial_submitted_at) or "not recorded"),
        Row("Latest response sent", long_stamp(application.revision_submitted_at) or "none yet"),
        Row("Revision", str(application.revision)),
        Row("Application id", application.id, mono=True),
    ]
    return DetailView(
        title="Application record",
        subtitle=application.source_application_number,
        sections=(Section("Record", tuple(rows)),),
    )


patterns.register_detail(
    "my-permit",
    _resolve_my_permit,
    label="Application record",
    any_grant=(("application.submit", "permits"),),
)


# ----------------------------------------------------------- property context


def _resolve_property_context(ctx: DetailContext, application_id: str) -> DetailView | None:
    """The property context of one application: parcel, address, documents,
    related applications and the rule versions that apply.

    The detail is the same one the planning overview lists.  It is read under
    the same scope as the overview, so an application outside the persona's
    scope answers "not available".
    """
    from acme_city.permits.service import PermitService
    from acme_city.rules.service import RuleCatalogService

    application = ctx.session.execute(
        select(permit.Application).where(permit.Application.id == application_id)
    ).scalar_one_or_none()
    if application is None or not view_models._application_in_scope(
        ctx.actor, application
    ):
        return None
    service = PermitService(ctx.session)
    type_row = service.permit_type(application)
    facts = dict(application.submitted_facts or {})
    site = ctx.session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id,
            permit.ApplicationSite.is_primary.is_(True),
        )
    ).scalar_one_or_none()

    parcel_row = (
        ctx.session.get(registry.Parcel, site.parcel_id)
        if site is not None and site.parcel_id
        else None
    )
    address_row = (
        ctx.session.get(registry.Address, site.address_id)
        if site is not None and site.address_id
        else None
    )

    record_rows = [
        Row("Application", application.source_application_number, mono=True),
        Row("Project type", type_row.label if type_row else "not recorded"),
        Row(
            "Project description",
            str(facts.get("project_description") or application.description or "not recorded"),
        ),
        Row(
            "Submitted site text",
            (site.submitted_address_text if site is not None else "") or "not recorded",
        ),
        Row(
            "Site resolution",
            (site.resolution_status if site is not None else "no site record") or "not recorded",
        ),
        Row(
            "Official address",
            (address_row.source_string if address_row is not None else "") or "not resolved",
        ),
        Row(
            "Parcel",
            (parcel_row.source_parcel_number if parcel_row is not None else "") or "not resolved",
            mono=True,
        ),
        Row(
            "First submitted",
            view_models._iso(application.initial_submitted_at) or "not recorded",
        ),
    ]
    sections = [Section("Application and property", tuple(record_rows))]

    if parcel_row is not None:
        sections.append(
            Section(
                "Parcel record",
                (
                    Row("Parcel", parcel_row.source_parcel_number, mono=True),
                    Row("Use", parcel_row.use_description or "not recorded"),
                    Row("Zoning", parcel_row.zoning_code or "not recorded"),
                    Row(
                        "Area",
                        f"{parcel_row.area_acres} acres"
                        if parcel_row.area_acres is not None
                        else "not recorded",
                    ),
                    Row("Owner", parcel_row.owner_name or "not recorded"),
                ),
            )
        )

    documents = ctx.session.execute(
        select(permit.Document).where(permit.Document.application_id == application.id)
    ).scalars().all()
    sections.append(
        Section(
            "Site documents",
            tuple(
                Row(
                    f"{row.document_type} v{row.version}",
                    row.content_hash,
                    mono=True,
                    info="content_hash",
                )
                for row in documents
            )
            or (Row("Documents", "no document is stored for this application"),),
        )
    )

    related: list[Row] = []
    if site is not None and (site.parcel_id or site.address_id):
        for other in ctx.session.execute(
            select(permit.ApplicationSite).where(
                permit.ApplicationSite.application_id != application.id,
                permit.ApplicationSite.is_primary.is_(True),
            )
        ).scalars().all():
            if (site.parcel_id and other.parcel_id == site.parcel_id) or (
                site.address_id and other.address_id == site.address_id
            ):
                sibling = ctx.session.get(permit.Application, other.application_id)
                if sibling is None:
                    continue
                related.append(
                    Row(
                        sibling.source_application_number,
                        other.submitted_address_text or "same parcel or address",
                        mono=False,
                    )
                )
    sections.append(
        Section(
            "Related applications",
            tuple(related) or (Row("Related applications", "none recorded"),),
        )
    )

    basis = application.initial_submitted_at
    rule_rows: list[Row] = []
    rule_set = None
    if basis is not None and type_row is not None:
        rule_set = RuleCatalogService(ctx.session).resolve(
            "executable", type_row.key, basis, basis_label="initial_submitted_at"
        )
        for rule in rule_set.rules:
            rule_rows.append(
                Row(
                    f"{rule.title} ({rule.citation})",
                    f"limit {rule.limit_value or 'not set'}"
                    + (f" on {rule.field_path}" if rule.field_path else ""),
                )
            )
    sections.append(
        Section(
            "Rule versions that apply",
            tuple(rule_rows)
            or (
                Row(
                    "Rule versions",
                    "no published rule version is in force for this application",
                ),
            ),
        )
    )
    if rule_set is not None:
        sections.append(
            Section(
                "How the version was chosen",
                (
                    Row(
                        "Date basis",
                        "the initial submission time of the application; a later "
                        "revision does not switch the schedule",
                    ),
                    Row("Basis date", view_models._iso(basis) or "not recorded"),
                ),
            )
        )
    return DetailView(
        title="Property context",
        subtitle=application.source_application_number,
        sections=tuple(sections),
    )


patterns.register_detail(
    "property-context",
    _resolve_property_context,
    label="Property context",
    any_grant=view_models.SCREEN_PERMISSIONS["overview"],
)


# ------------------------------------------------------------------- a source


def _resolve_source(ctx: DetailContext, source_system_id: str) -> DetailView | None:
    """One source system: its records, its freshness, its team and its route."""
    from acme_city.ui import admin_views

    row = ctx.session.execute(
        select(source.SourceSystem).where(
            source.SourceSystem.source_system_id == source_system_id
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    overview = next(
        (
            item
            for item in admin_views._source_overview(ctx.session)
            if item["source_system_id"] == source_system_id
        ),
        None,
    )
    if overview is None:
        return None
    snapshots = ctx.session.execute(
        select(source.SourceSnapshot)
        .where(source.SourceSnapshot.source_system_id == source_system_id)
        .order_by(source.SourceSnapshot.ingested_at.desc())
    ).scalars().all()
    datasets = sorted({snapshot.source_dataset_id for snapshot in snapshots})
    rows = [
        Row("Source", row.label),
        Row("Description", row.description or "not recorded"),
        Row("Simulated", "yes" if row.simulated else "no"),
        Row("Incoming", "yes" if row.incoming else "no"),
        Row("Stored records", str(len(snapshots))),
        Row("Datasets", ", ".join(datasets) or "none recorded"),
        Row(
            "Source last changed",
            overview["last_changed"] or "Freshness information unavailable",
        ),
        Row(
            "Last received or checked",
            overview["last_received"] or "Freshness information unavailable",
        ),
        Row("Open recorded issues", str(overview["open_issues"])),
        Row("Responsible team", overview["responsible_team"]),
        Row("Change this in", overview["correction_path"] or "not declared"),
    ]
    return DetailView(
        title=f"{row.label} — source",
        subtitle=overview["records"],
        sections=(Section("Source", tuple(rows)),),
    )


patterns.register_detail(
    "source",
    _resolve_source,
    label="Source",
    any_grant=view_models.SCREEN_PERMISSIONS["governance"],
)

__all__ = ["router"]

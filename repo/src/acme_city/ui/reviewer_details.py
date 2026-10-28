"""Detail flyouts of the permit reviewer screens.

Each kind is registered with ``patterns.register_detail`` and answers through
the same grant and record-scope checks as the page.  Staff only: an applicant
never reads internal ids, document hashes or revision diffs from here.
"""
# REQUIRES: UX-01, UX-02, SEC-01

from __future__ import annotations

from sqlalchemy import select

from acme_city.ui import patterns, reviewer_views, view_models
from acme_city.ui.patterns import DetailContext, DetailForbidden, DetailView, Row, Section


def _application(ctx: DetailContext, key: str):
    """Return an application inside the persona's scope, else ``None``.

    Raises ``DetailForbidden`` for a persona that is not City staff.
    """
    from acme_city.persistence.models import permit
    from acme_city.permits.comments import is_staff

    if not is_staff(ctx.session, ctx.actor):
        raise DetailForbidden
    application = ctx.session.execute(
        select(permit.Application).where(
            (permit.Application.id == key)
            | (permit.Application.source_application_number == key)
        )
    ).scalar_one_or_none()
    if application is None or not view_models._application_in_scope(ctx.actor, application):
        return None
    return application


def _resolve_case_tech(ctx: DetailContext, key: str) -> DetailView | None:
    """Technical ids and the exact issue codes of one case."""
    from acme_city.permits.service import PermitService

    application = _application(ctx, key)
    if application is None:
        return None
    service = PermitService(ctx.session)
    type_row = service.permit_type(application)
    parties = service.parties(application.id)
    blockers = view_models._application_blockers(service, application)
    ids = [
        Row("Reference", application.source_application_number, mono=True),
        Row("Application id", application.id, mono=True),
        Row("Permit type key", type_row.key, mono=True),
        Row("Record version", str(application.version)),
        Row("Revision", str(application.revision)),
        Row("Status code", application.status, mono=True, info="record_status"),
    ]
    sections = [
        Section("Technical ids", tuple(ids)),
        Section(
            "Parties (internal keys)",
            tuple(Row(party.party_role.replace("_", " ").capitalize(), party.party_id, mono=True) for party in parties)
            or (),
            lines=() if parties else ("No party is recorded.",),
        ),
    ]
    if blockers:
        sections.append(
            Section(
                "Issues (exact codes)",
                tuple(
                    Row(reviewer_views.issue_label(b["code"]), f"{b['code']}: {b['detail']}", mono=True, info="reason_code")
                    for b in blockers
                ),
            )
        )
    else:
        sections.append(Section("Issues (exact codes)", lines=("No issue is recorded.",)))
    return DetailView(
        title="Technical details",
        subtitle=application.source_application_number,
        sections=tuple(sections),
        links=((f"Open {application.source_application_number}", f"/permits/{application.id}"),),
    )


patterns.register_detail(
    "case-tech",
    _resolve_case_tech,
    label="Technical details",
    any_grant=view_models.SCREEN_PERMISSIONS["permit"],
)


def _resolve_doc_history(ctx: DetailContext, document_id: str) -> DetailView | None:
    """Document history: every version of the document, with uploader and hash."""
    from acme_city.persistence.models import permit

    row = ctx.session.get(permit.Document, document_id)
    if row is None or row.application_id is None:
        return None
    application = _application(ctx, row.application_id)
    if application is None:
        return None
    versions = ctx.session.execute(
        select(permit.Document)
        .where(
            permit.Document.application_id == row.application_id,
            permit.Document.document_type == row.document_type,
        )
        .order_by(permit.Document.version)
    ).scalars().all()
    sections = []
    for version in versions:
        sections.append(
            Section(
                f"Version {version.version}" + (" (this view)" if version.id == row.id else ""),
                (
                    Row("Received", view_models._iso(version.received_at) or "not recorded", mono=True),
                    Row(
                        "Uploaded by",
                        view_models.actor_label(ctx.session, version.uploaded_by_actor_id)
                        if version.uploaded_by_actor_id
                        else "not recorded",
                    ),
                    Row("Content hash", version.content_hash, mono=True, info="content_hash"),
                    Row("Document id", version.id, mono=True),
                ),
            )
        )
    return DetailView(
        title=f"{row.document_type}: history",
        subtitle=application.source_application_number,
        sections=tuple(sections),
    )


patterns.register_detail(
    "doc-history",
    _resolve_doc_history,
    label="Document history",
    any_grant=(("records.document.view", None),) + view_models.SCREEN_PERMISSIONS["permit"],
)


def _resolve_revision(ctx: DetailContext, key: str) -> DetailView | None:
    """What changed in one revision of a case, key ``<application id>:<number>``."""
    if ":" not in key:
        return None
    application_key, _, number = key.rpartition(":")
    application = _application(ctx, application_key)
    if application is None:
        return None
    rows = reviewer_views._revision_rows(ctx.session, application)
    revision = next((r for r in rows if str(r["number"]) == number), None)
    if revision is None:
        return None
    sections = [
        Section(
            "Revision",
            (
                Row("Number", str(revision["number"])),
                Row("Submitted", revision["submitted_at"] or "not recorded", mono=True),
                Row("Status", revision["label"]),
                Row("Application checks", revision["checks_state"]),
                Row("Needs re-review", "Yes" if revision["needs_rereview"] else "No"),
            ),
        )
    ]
    if revision["changed"]:
        sections.append(
            Section(
                "Changed since the previous revision",
                tuple(Row(item["field"], f"{item['before'] or '(none)'} -> {item['after'] or '(none)'}") for item in revision["changed"]),
            )
        )
    else:
        sections.append(Section("Changed since the previous revision", lines=("No submitted fact changed (or this is the first revision).",)))
    sections.append(
        Section(
            "Documents received",
            lines=tuple(revision["documents"]) or ("No new document.",),
        )
    )
    return DetailView(
        title=f"Revision {revision['number']}",
        subtitle=application.source_application_number,
        sections=tuple(sections),
    )


patterns.register_detail(
    "revision",
    _resolve_revision,
    label="Revision",
    any_grant=view_models.SCREEN_PERMISSIONS["permit"],
)

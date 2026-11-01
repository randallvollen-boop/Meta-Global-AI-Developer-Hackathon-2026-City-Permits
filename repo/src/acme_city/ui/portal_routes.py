"""The applicant portal pages: choose, fill in, submit and track.

Server-rendered forms.  The submission is governed: the CSRF token, the acting
persona's own ``application.submit`` grant and an audit record.  The script on
the page only mirrors the server's completeness answer while the applicant
types; the server decides again on every preview, save and submit.

The help panel is part of the portal.  It answers from the City's published
rules and from the applicant's own case, it keeps its conversation private to
the applicant, and it hands the applicant to a person when it cannot answer.
The panel works without JavaScript: the question is a form of its own, never
part of the application form, so the applicant's typed fields and files stay
untouched.
"""
# REQUIRES: PORTAL-01, PORTAL-02, PORTAL-03, PORTAL-04, PER-04, SEC-03

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from acme_city.applicant_portal import content as portal_content
from acme_city.applicant_portal import forms, permits_view
from acme_city.applicant_portal.presubmit import ANYWAY_WHY, override_record
from acme_city.applicant_portal.service import (
    MAX_UPLOAD_BYTES,
    UPLOAD_EXTENSIONS,
    PortalService,
    applicant_display_name,
    applicant_party,
)
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.core.errors import AcmeError, NotFoundError, ValidationError
from acme_city.ui import view_models
from acme_city.ui.router import (
    CSRF_FIELD,
    error_response,
    _guard,
    page_context,
    render,
    ui_actor,
    verify_csrf,
)

router = APIRouter(tags=["portal"])


async def posted_form(request: Request) -> Any:
    """Read a posted form and close its temporary upload files afterwards."""
    form = await request.form()
    try:
        yield form
    finally:
        await form.close()


def _portal_guard(
    request: Request, session: Session, actor: ActorContext | None
) -> tuple[ActorContext | None, Any]:
    """Return the acting applicant, or the refused response.

    The portal is the applicant's own self-service: it needs the
    ``application.submit`` grant *and* a grant that is limited to the actor's
    own records.  Staff who may file on behalf of others use the intake screens.
    """
    resolved, refused = _guard(request, session, actor, "portal")
    if refused is not None:
        return None, refused
    if not resolved.record_scope:
        return None, error_response(
            request,
            session,
            resolved,
            status_code=403,
            title="The applicant portal is for applicants",
            message=(
                "The portal is the applicant's own self-service. Staff personas "
                "work from the work queue and the agent screens."
            ),
            code="permission_denied",
            back="/queue",
        )
    return resolved, None

#: Names the form posts that are not application fields.
_RESERVED = {CSRF_FIELD, "intent", "draft", "certification_accepted", "next", "override_reason"}


class _Incomplete(Exception):
    """The applicant pressed Submit with something still missing."""


class _Rejected(Exception):
    """A file was refused; the draft is kept and nothing is submitted."""


class _Held(Exception):
    """A complete application still has a Must fix."""

    def __init__(self, review: dict[str, Any], error: str = "") -> None:
        self.review = review
        self.error = error


def _upload_rules() -> str:
    """Return the accepted formats and the size limit, from the upload rules."""
    megabytes = MAX_UPLOAD_BYTES // (1024 * 1024)
    return f"Accepted: PDF, PNG, JPG or plain text (.txt), up to {megabytes} MB each."


def _declared(form: Any, spec: forms.FormSpec) -> set[str]:
    """Return the document types the applicant ticked "Sent to the City separately"."""
    return {
        doc_type
        for doc_type, _label in spec.documents
        if str(form.get(f"sent_separately__{doc_type}", "")).lower() in {"on", "true", "1"}
    }


def _values(form: Any, spec: forms.FormSpec) -> dict[str, str]:
    """Return the typed values of a posted form (text only)."""
    names = {field.key for field in spec.fields} | {
        "applicant_name",
        "applicant_email",
        "applicant_phone",
        "business_name",
        "address_text",
    }
    out: dict[str, str] = {}
    for name in names:
        value = form.get(name)
        out[name] = str(value).strip() if isinstance(value, str) else ""
    return spec.with_defaults(out)


async def _files(form: Any, spec: forms.FormSpec) -> list[tuple[str, str, bytes]]:
    """Return the files posted in the document slots of a form."""
    files = []
    for doc_type, _label in spec.documents:
        upload = form.get(f"file__{doc_type}")
        if upload is None or not hasattr(upload, "read") or not getattr(upload, "filename", ""):
            continue
        content = await upload.read()
        if content:
            files.append((doc_type, upload.filename, content))
    return files


def _form_context(
    request: Request,
    session: Session,
    actor: ActorContext,
    service: PortalService,
    spec: forms.FormSpec,
    *,
    values: dict[str, str],
    certification_accepted: bool,
    draft: Any,
    sent_separately: set[str] | None = None,
    attempted: bool = False,
    error: str = "",
    notice: str = "",
    upload_problems: dict[str, str] | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = spec.with_defaults(values)
    documents = service.draft_documents(draft)
    declared = set(sent_separately or ())
    state = service.completeness(
        spec, values, set(documents), certification_accepted=certification_accepted, sent_separately=declared
    )
    symbols = portal_content.content().get("type_icons", {})
    return page_context(
        request,
        session,
        actor,
        screen="portal",
        title=f"Apply: {spec.label}",
        spec=spec,
        values=values,
        draft=draft,
        draft_documents={key: doc.filename for key, doc in documents.items()},
        state=state,
        sent_separately=declared,
        attempted=attempted and not state["can_submit"],
        icon_symbol=str(symbols.get(spec.type_key, "c-permit")),
        certification=forms.CERTIFICATION_TEXT,
        form_error=error,
        form_notice=notice,
        located=service.locate(values.get("address_text", "")),
        rule_hints=service.rule_hints(spec),
        upload_rules=_upload_rules(),
        upload_accept=",".join(sorted(UPLOAD_EXTENSIONS)),
        upload_problems=dict(upload_problems or {}),
        document_purposes={
            doc_type: portal_content.document_purpose(doc_type) for doc_type, _label in spec.documents
        },
        review=review,
    )


def _default_values(session: Session, actor: ActorContext) -> dict[str, str]:
    return {
        "applicant_name": applicant_display_name(session, actor),
        "applicant_email": "",
        "applicant_phone": "",
        "address_text": "",
        "business_name": "",
    }


def _service(request: Request, session: Session) -> PortalService:
    return PortalService(session, settings=request.app.state.settings)


def _persona_home(session: Session, actor: ActorContext) -> str:
    """Return the screen the persona lands on, the way back into the application.

    It is the screen of the persona card of the landing: the City website for
    the Applicant, the own home of a staff persona.
    """
    label = view_models.actor_label(session, actor.actor_id)
    options = {option["label"]: option for option in view_models.persona_options(session)}
    return options.get(label, {}).get("next") or "/city/"


@router.get("/apply", operation_id="ui_portal_chooser")
def ui_portal_chooser(
    request: Request,
    saved: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show "Start an application": the groups of permit types."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    groups = service.chooser()
    type_labels = {card["type_key"]: card["label"] for group in groups for card in group["all"]}
    context = page_context(
        request,
        session,
        resolved,
        screen="portal",
        title="Start an application",
        groups=groups,
        drafts=[
            {
                "reference": row.reference,
                "type_key": row.permit_type_key,
                "type_label": type_labels.get(row.permit_type_key, row.permit_type_key),
            }
            for row in service.my_drafts(resolved)
        ],
        saved=saved,
        portal_notice=forms.PORTAL_NOTICE,
    )
    return render(request, "portal_chooser.html", context)


@router.get("/apply/locate", operation_id="ui_portal_locate")
def ui_portal_locate(
    request: Request,
    text: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Return "Did you mean" for typed address text."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    return JSONResponse({**_service(request, session).locate(text), "simulated": True})


@router.get("/apply/suggest", operation_id="ui_portal_suggest")
def ui_portal_suggest(
    request: Request,
    text: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Return address suggestions as the applicant types."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    from acme_city.gis.adapter import GisServiceError, get_locator

    try:
        suggestions = (
            get_locator(request.app.state.settings).suggest(text, 6) if text.strip() else []
        )
    except GisServiceError:
        suggestions = []
    return JSONResponse({"suggestions": suggestions, "simulated": True})


@router.get("/apply/track", operation_id="ui_portal_track")
def ui_portal_track(
    request: Request,
    ref: str = "",
    revised: str = "",
    resubmitted: str = "",
    saved: str = "",
    tab: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show "My permits"; with a reference, show that application in full."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    tracked = service.track(ref, resolved) if ref.strip() else None
    pm = None if tracked else permits_view.my_permits(session, resolved, tab=tab)
    context = page_context(
        request,
        session,
        resolved,
        screen="portal",
        title="My permits",
        ref=ref,
        tracked=tracked,
        pm=pm,
        next_step=(
            tracked["card"]["next_step"]
            if tracked
            else (pm or {}).get("next_step", "")
        ),
        not_found=bool(ref.strip()) and tracked is None,
        revised=revised,
        resubmitted=resubmitted,
        saved=saved,
        portal_notice=forms.PORTAL_NOTICE,
    )
    if tracked is None and pm is None:  # pragma: no cover - pm is built whenever tracked is not
        raise AssertionError
    return render(request, "portal_track.html", context)


@router.post("/apply/track/{application_id}/revise", operation_id="ui_portal_revise")
async def ui_portal_revise(
    application_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Submit revised documents for an application the City asked about."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    back = "/apply/track"
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        application_ref = str(form.get("reference", ""))
        back = f"/apply/track?ref={application_ref}"
        uploads = []
        for key, upload in form.multi_items():
            if key.startswith("file__") and hasattr(upload, "read") and upload.filename:
                content = await upload.read()
                if content:
                    uploads.append((key[len("file__"):], upload.filename, content))
        if not uploads:
            raise NotFoundError("choose at least one revised file")
        count = service.revise_documents(application_id, uploads, resolved)
        session.commit()
    except AcmeError as error:
        session.rollback()
        AuditService(session).record_denied(
            action="portal.documents.revise",
            actor=resolved,
            target_type="application",
            target_id=application_id,
            denial_reason=error.code,
        )
        session.commit()
        return error_response(
            request,
            session,
            resolved,
            status_code=error.status_code,
            title="The revised documents were refused",
            message=error.message,
            code=error.code,
            back=back,
        )
    return RedirectResponse(f"{back}&revised={count}", status_code=303)


@router.post("/apply/track/{application_id}/resubmit", operation_id="ui_portal_resubmit")
async def ui_portal_resubmit(
    application_id: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Answer the City and send the case back to intake.

    The resubmission is atomic: the revised documents and the new submitted
    revision move together, and the case returns to the intake agent.
    """
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    back = "/apply/track"
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        application_ref = str(form.get("reference", ""))
        back = f"/apply/track?ref={application_ref}"
        uploads = []
        for key, upload in form.multi_items():
            if key.startswith("file__") and hasattr(upload, "read") and upload.filename:
                content = await upload.read()
                if content:
                    uploads.append((key[len("file__"):], upload.filename, content))
        expected_version = str(form.get("expected_version", "")).strip()
        service.resubmit(
            application_id,
            resolved,
            uploads=uploads,
            answers={},
            expected_version=int(expected_version) if expected_version else None,
        )
        session.commit()
    except AcmeError as error:
        session.rollback()
        AuditService(session).record_denied(
            action="portal.application.resubmit",
            actor=resolved,
            target_type="application",
            target_id=application_id,
            denial_reason=error.code,
        )
        session.commit()
        return error_response(
            request,
            session,
            resolved,
            status_code=error.status_code,
            title="The answer was refused",
            message=error.message,
            code=error.code,
            back=back,
        )
    return RedirectResponse(f"{back}&resubmitted=1", status_code=303)


@router.get("/apply/submitted/{reference}", operation_id="ui_portal_submitted")
def ui_portal_submitted(
    reference: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Confirm a submitted application."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    tracked = _service(request, session).track(reference, resolved)
    if tracked is None:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That application is not available to you",
            message="No application with that reference is in your records.",
            code="not_found",
            back="/apply",
        )
    context = page_context(
        request,
        session,
        resolved,
        screen="portal",
        title="Application received",
        tracked=tracked,
        receipt=portal_content.content()["receipt"],
    )
    return render(request, "portal_submitted.html", context)


@router.get("/apply/submitted/{reference}/copy", operation_id="ui_portal_copy")
def ui_portal_copy(
    reference: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Download a printable copy of what the applicant submitted.

    The copy holds the applicant's own entries and the received documents. It
    carries no finding, no comment and no staff name, and it is not a permit.
    """
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    record = _service(request, session).copy_record(reference, resolved)
    if record is None:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That application is not available to you",
            message="No application with that reference is in your records.",
            code="not_found",
            back="/apply/track",
        )
    from acme_city.ui.router import templates

    body = templates.get_template("portal_copy.html").render(
        record=record,
        copy_note=portal_content.content()["receipt"]["copy_note"],
        back_href=_persona_home(session, resolved),
    )
    return Response(
        body,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="application-{record["reference"]}.html"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/apply/permit/{reference}", operation_id="ui_portal_permit_download")
def ui_portal_permit_download(
    reference: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Download the printable permit of an issued application the applicant owns."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    issued = _service(request, session).issued_permit(reference, resolved)
    if issued is None:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="No permit is available for that application",
            message="The permit can be downloaded once it has been issued.",
            code="not_found",
            back="/apply/track",
        )
    from acme_city.permits.issuance import render_permit_artifact

    return Response(
        render_permit_artifact(session, issued.id),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="permit-{issued.permit_number}.html"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/apply/{type_key}", operation_id="ui_portal_form")
def ui_portal_form(
    type_key: str,
    request: Request,
    draft: str = "",
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the application form of one permit type."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    try:
        spec = service.form(type_key)
    except NotFoundError as error:
        return error_response(
            request,
            session,
            resolved,
            status_code=404,
            title="That permit type is not available",
            message=error.message,
            code="not_found",
            back="/apply",
        )
    row = service.draft(draft, resolved) if draft else None
    values = _default_values(session, resolved)
    certification_accepted = False
    declared: set[str] = set()
    if row is not None:
        values.update(dict(row.data.get("values") or {}))
        certification_accepted = bool(row.data.get("certification_accepted"))
        declared = {str(item) for item in row.data.get("sent_separately") or []}
    context = _form_context(
        request, session, resolved, service, spec, values=values,
        certification_accepted=certification_accepted, draft=row, sent_separately=declared,
    )
    return render(request, "portal_form.html", context)


@router.post("/apply/{type_key}/check", operation_id="ui_portal_check")
async def ui_portal_check(
    type_key: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Return the server's completeness answer for the typed values (writes nothing)."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    spec = service.form(type_key)
    row = service.draft(str(form.get("draft", "")), resolved) if form.get("draft") else None
    have = set(service.draft_documents(row))
    for doc_type, _filename, _content in await _files(form, spec):
        have.add(doc_type)
    have |= {key[len("have__"):] for key in form.keys() if key.startswith("have__")}
    state = service.completeness(
        spec,
        _values(form, spec),
        have,
        certification_accepted=str(form.get("certification_accepted", "")).lower() in {"on", "true", "1"},
        sent_separately=_declared(form, spec),
    )
    return JSONResponse(state)


def _posted_types(form: Any, draft_types: set[str]) -> set[str]:
    """Return document types the request already has, without storing a new file."""
    have = set(draft_types)
    have |= {str(key)[len("have__"):] for key in form.keys() if str(key).startswith("have__")}
    return have


def _run_review(
    request: Request,
    service: PortalService,
    spec: forms.FormSpec,
    values: dict[str, str],
    actor: ActorContext,
    *,
    certification_accepted: bool,
    declared: set[str],
    uploaded_types: set[str],
    documents: dict[str, Any],
    muse: bool,
    posted_files: list[tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Run the rules layer.  Muse runs only for Check my application."""
    return service.presubmit_review(
        spec,
        values,
        actor=actor,
        certification_accepted=certification_accepted,
        sent_separately=declared,
        uploaded_types=uploaded_types,
        documents=documents,
        posted_files=posted_files or (),
        muse=muse,
        muse_client=getattr(request.app.state, "presubmit_muse_client", None),
    )


@router.post("/apply/{type_key}/review", operation_id="ui_portal_review")
async def ui_portal_review(
    type_key: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Return the pre-submit panel.  This writes no case."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    spec = service.form(type_key)
    row = service.draft(str(form.get("draft", "")), resolved) if form.get("draft") else None
    documents = service.draft_documents(row)
    posted = await _files(form, spec)
    have = _posted_types(form, set(documents))
    for doc_type, _filename, _content in posted:
        have.add(doc_type)
    review = _run_review(
        request,
        service,
        spec,
        _values(form, spec),
        resolved,
        certification_accepted=str(form.get("certification_accepted", "")).lower() in {"on", "true", "1"},
        declared=_declared(form, spec),
        uploaded_types=have,
        documents=documents,
        muse=True,
        posted_files=posted,
    )
    return JSONResponse(review)


@router.post("/apply/{type_key}", operation_id="ui_portal_post")
async def ui_portal_post(
    type_key: str,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext | None = Depends(ui_actor),
    form: Any = Depends(posted_form),
) -> Any:
    """Preview, save a draft, or submit an application."""
    resolved, refused = _portal_guard(request, session, actor)
    if refused is not None:
        return refused
    service = _service(request, session)
    try:
        spec = service.form(type_key)
    except NotFoundError as error:
        return error_response(
            request, session, resolved, status_code=404, title="That permit type is not available",
            message=error.message, code="not_found", back="/apply",
        )
    values = _values(form, spec)
    certification_accepted = str(form.get("certification_accepted", "")).lower() in {"on", "true", "1"}
    intent = str(form.get("intent", "update"))
    declared = _declared(form, spec)
    attempted = False
    held = False
    draft = None
    review: dict[str, Any] | None = None
    error_text = ""
    notice = ""
    upload_problems: dict[str, str] = {}
    try:
        verify_csrf(request.app.state.settings, resolved, str(form.get(CSRF_FIELD, "")))
        draft = service.save_draft(
            spec, values, certification_accepted, resolved,
            reference=str(form.get("draft", "")), sent_separately=declared,
        )
        removing = str(form.get("remove_doc", ""))
        if removing and removing in dict(spec.documents):
            if service.remove_upload(draft, removing, resolved):
                labels = dict(spec.documents)
                notice = f"Removed the file for {labels[removing][:1].lower() + labels[removing][1:]}. Your other entries are kept in a draft."
        posted = await _files(form, spec)
        for doc_type, filename, content in posted:
            try:
                service.store_upload(draft, doc_type, filename, content, resolved)
            except ValidationError as problem:
                upload_problems[doc_type] = problem.message
        if upload_problems:
            # Keep the draft and every other entry; the refused file is simply not stored.
            session.commit()
            error_text = next(iter(upload_problems.values()))
            raise _Rejected
        documents = service.draft_documents(draft)
        if intent == "review":
            review = _run_review(
                request, service, spec, values, resolved,
                certification_accepted=certification_accepted,
                declared=declared,
                uploaded_types=set(documents),
                documents=documents,
                muse=True,
                posted_files=posted,
            )
            session.commit()
            notice = notice or "Checked the application. Nothing has been submitted."
        elif intent in {"submit", "override"}:
            incomplete = service.completeness(
                spec,
                values,
                set(documents),
                certification_accepted=certification_accepted,
                sent_separately=declared,
            )
            if not incomplete["can_submit"]:
                # Nothing is submitted. Keep what was entered (and any file) as a draft
                # and show the person what is missing, beside each field.
                session.commit()
                attempted = True
                notice = "Nothing has been submitted. Your entries are kept in a draft."
                raise _Incomplete
            # Submit itself does not ask the assistant.  Check my application does.
            review = _run_review(
                request, service, spec, values, resolved,
                certification_accepted=certification_accepted,
                declared=declared,
                uploaded_types=set(documents),
                documents=documents,
                muse=False,
            )
            reason = " ".join(str(form.get("override_reason", "") or "").split())
            override = None
            if review["must_fix"]:
                if intent != "override" or not reason:
                    session.commit()
                    raise _Held(review, "" if intent != "override" else ANYWAY_WHY)
                override = override_record(review, reason, recorded_at=service._now.isoformat())
            application = service.submit(
                spec, values, certification_accepted, draft, resolved,
                sent_separately=declared, override=override,
            )
            session.commit()
            return RedirectResponse(
                f"/apply/submitted/{application.source_application_number}", status_code=303
            )
        else:
            session.commit()
            if intent == "save":
                return RedirectResponse(
                    f"/apply/track?tab=drafts&saved={draft.reference}", status_code=303
                )
            notice = notice or "Your changes are kept in a draft. Nothing has been submitted."
    except _Held as held_error:
        review = held_error.review
        held = True
        if held_error.error:
            error_text = held_error.error
    except (_Incomplete, _Rejected):
        pass
    except AcmeError as error:
        session.rollback()
        error_text = error.message
        draft = service.draft(str(form.get("draft", "")), resolved) if form.get("draft") else None
        if error.code == "permission_denied":
            return error_response(
                request, session, resolved, status_code=error.status_code,
                title="The action was refused", message=error.message, code=error.code, back="/apply",
            )
    context = _form_context(
        request, session, resolved, service, spec,
        values=values, certification_accepted=certification_accepted, draft=draft,
        sent_separately=declared, attempted=attempted, error=error_text, notice=notice,
        upload_problems=upload_problems, review=review,
    )
    return render(
        request, "portal_form.html", context, status_code=422 if (error_text or attempted or held) else 200
    )

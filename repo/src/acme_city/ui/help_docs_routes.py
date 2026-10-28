"""The help and documentation pages.

Routes:

* ``GET /help``                          the hub
* ``GET /help/tutorial``                 the guided walk through the demo story
* ``GET /help/how-to``                   the list of task guides
* ``GET /help/how-to/{slug}``            one task guide
* ``GET /help/glossary``                 the terms of the information popovers
* ``GET /help/technical``                the list of technical documents
* ``GET /help/technical/{slug}``         one document, read only
* ``GET /help/technical/{slug}/file``    an HTML document, in a script-free sandbox

The hub, the tutorial, the guides and the glossary are open to anyone who
visits, signed in or not, because they describe the demonstration and hold no
record.  The technical documents need a signed-in persona.  Staff see the
pages in the staff frame and applicants (and visitors) in the City website
frame.  All words come from ``config/help_content.json``.
"""
# REQUIRES: UX-01, SEC-01
# The help pages are read only, hold no record and are served with the same
# session rules as the other screens; an HTML document is sandboxed.

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.help_docs import content, markdown
from acme_city.ui import patterns
from acme_city.ui.router import error_response, page_context, render, ui_actor
from acme_city.ui.view_models import actor_label

router = APIRouter(tags=["help"])

#: The security headers of an HTML document.  ``sandbox`` without any allow
#: token gives the document an opaque origin and turns scripts, forms, popups
#: and top navigation off, whether the file is framed or opened on its own.
#: The remaining directives close every other way to load or send anything.
SANDBOX_CSP = (
    "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def _context(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    *,
    title: str,
    **extra: Any,
) -> dict[str, Any]:
    """Return the context of a help page, in the frame that suits the visitor."""
    persona = actor_label(session, actor.actor_id) if actor is not None else ""
    staff = actor is not None and persona != "Applicant"
    base: dict[str, Any]
    if actor is None:
        from acme_city.city.router import city_context

        base = city_context(request, session, None, title=title, active_nav="help")
    else:
        base = page_context(request, session, actor, screen="help", title=title)
        if not staff:
            base["active_nav"] = "help"
    base["help_layout"] = "base.html" if staff else "city/layout.html"
    base["help_persona_id"] = actor.actor_id if actor is not None else ""
    base["help_persona"] = persona
    base["help_hub"] = content.hub()
    return {**base, **extra}


def _needs_sign_in(actor: ActorContext | None) -> Any:
    return RedirectResponse("/select", status_code=303) if actor is None else None


@router.get("/help", operation_id="ui_help_hub")
def ui_help_hub(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the hub: the tutorial, the guides, the technical documents, the glossary."""
    hub = content.hub()
    return render(
        request,
        "help.html",
        _context(request, session, actor, title=hub["title"], help_view="hub"),
    )


@router.get("/help/tutorial", operation_id="ui_help_tutorial")
def ui_help_tutorial(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show the tutorial."""
    tutorial = content.tutorial()
    return render(
        request,
        "help.html",
        _context(
            request,
            session,
            actor,
            title="Tutorial",
            help_view="tutorial",
            tutorial=tutorial,
        ),
    )


@router.get("/help/how-to", operation_id="ui_help_howto_index")
def ui_help_howto_index(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """List the task guides, those for the visitor's own role first."""
    persona_id = actor.actor_id if actor is not None else "persona_applicant"
    return render(
        request,
        "help.html",
        _context(
            request,
            session,
            actor,
            title="How-to guides",
            help_view="howto_index",
            guides=content.guides(persona_id),
            howto_intro=content.howto_intro(),
            first_persona=persona_id,
        ),
    )


@router.get("/help/how-to/{slug}", operation_id="ui_help_howto")
def ui_help_howto(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show one task guide."""
    entry = content.guide(slug)
    if entry is None:
        return _not_found(request, session, actor, "That guide does not exist.", "/help/how-to")
    return render(
        request,
        "help.html",
        _context(request, session, actor, title=entry["title"], help_view="howto", guide=entry),
    )


@router.get("/help/glossary", operation_id="ui_help_glossary")
def ui_help_glossary(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """List the terms of the information popovers."""
    terms = [dict(patterns.term(key) or {}, key=key) for key in patterns.term_keys()]
    terms.sort(key=lambda item: str(item.get("label", "")).lower())
    return render(
        request,
        "help.html",
        _context(request, session, actor, title="Glossary", help_view="glossary", terms=terms),
    )


@router.get("/help/technical", operation_id="ui_help_technical")
def ui_help_technical(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """List the technical documents."""
    if (gate := _needs_sign_in(actor)) is not None:
        return gate
    technical = content.technical()
    documents = []
    for entry in technical["documents"]:
        documents.append({**entry, "available": content.read_document(entry).text is not None})
    return render(
        request,
        "help.html",
        _context(
            request,
            session,
            actor,
            title=technical["title"],
            help_view="technical",
            technical=technical,
            documents=documents,
        ),
    )


@router.get("/help/technical/{slug}", operation_id="ui_help_document")
def ui_help_document(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Show one technical document: Markdown rendered, or an HTML page in a sandbox."""
    if (gate := _needs_sign_in(actor)) is not None:
        return gate
    entry = content.document(slug)
    if entry is None:
        return _not_found(request, session, actor, "That document does not exist.", "/help/technical")
    loaded = content.read_document(entry)
    body = ""
    if loaded.text is not None and entry["format"] == "markdown":
        body = markdown.render(loaded.text)
    return render(
        request,
        "help.html",
        _context(
            request,
            session,
            actor,
            title=entry["title"],
            help_view="document",
            document=entry,
            document_body=body,
            document_message=loaded.message,
            document_available=loaded.text is not None,
            technical_note=content.technical()["html_note"],
        ),
        status_code=200 if loaded.text is not None else 404,
    )


@router.get("/help/technical/{slug}/file", operation_id="ui_help_document_file")
def ui_help_document_file(
    slug: str,
    request: Request,
    download: bool = False,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
) -> Any:
    """Serve an HTML document with a sandboxing policy, or as a download."""
    if (gate := _needs_sign_in(actor)) is not None:
        return gate
    entry = content.document(slug)
    if entry is None or entry["format"] != "html":
        return _not_found(request, session, actor, "That document does not exist.", "/help/technical")
    loaded = content.read_document(entry)
    if loaded.text is None:
        return Response(loaded.message, status_code=404, media_type="text/plain; charset=utf-8")
    headers = {
        "Content-Security-Policy": SANDBOX_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, no-store",
    }
    if download:
        name = str(entry["path"]).rsplit("/", 1)[-1]
        headers["Content-Disposition"] = f'attachment; filename="{html.escape(name, quote=True)}"'
        # A download is saved, not shown, so it is also labelled as plain bytes.
        return Response(loaded.text, media_type="application/octet-stream", headers=headers)
    return Response(loaded.text, media_type="text/html; charset=utf-8", headers=headers)


def _not_found(
    request: Request,
    session: Session,
    actor: ActorContext | None,
    message: str,
    back: str,
) -> Any:
    """Render a plain not-found page in the frame of the visitor."""
    if actor is None:
        return render(
            request,
            "help.html",
            _context(request, session, None, title="Not found", help_view="missing", missing=message, back=back),
            status_code=404,
        )
    return error_response(
        request, session, actor, status_code=404, title="Not found", message=message, back=back
    )

"""Routes of the fictional City of Acme public website.

The website is a presentation layer on the same origin as the permit
application.  It holds no data of its own and grants nothing: the Permits
entry reaches the applicant portal through the existing persona selector
(``POST /ui/actor``), and the portal keeps its own server-side checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.insight import public as community
from acme_city.ui.router import _applicant_name, render, templates, ui_actor
from acme_city.ui.view_models import SCREENS, actor_label, persona_options

router = APIRouter(prefix="/city", tags=["city-website"])

#: Where the Permits entry lands once the applicant persona is active.
PERMITS_HOME = "/apply"

#: Where "Track or resume an application" lands: My permits.
TRACK_HOME = "/apply/track"

#: Simple informational pages.  All content is fictional.
SERVICE_PAGES: dict[str, dict[str, Any]] = {
    "trash-recycling": {
        "title": "Trash and recycling",
        "icon": "trash",
        "summary": "Collection days, what goes in each cart, and bulk pickup.",
        "intro": "The Department of Public Works collects household trash and recycling every week.",
        "sections": [
            {"heading": "Collection schedule", "items": [
                "Trash: every Monday in the North districts, every Tuesday in the South districts.",
                "Recycling: alternate Thursdays, shown on the printed calendar.",
                "Place carts at the curb by 6:30 a.m. with the handles facing the house.",
            ]},
            {"heading": "What goes in the blue cart", "items": [
                "Clean paper, cardboard, glass jars and bottles, metal cans, and rigid plastic containers.",
                "No plastic bags, food waste, or garden hoses.",
            ]},
            {"heading": "Bulk pickup", "items": [
                "Large items are collected on the first Saturday of each month.",
                "Call Public Works to book a slot at least two days ahead.",
            ]},
        ],
        "aside": {"heading": "Public Works", "lines": ["(555) 010-0140", "Weekdays, 7:30 a.m. to 4:00 p.m."]},
    },
    "parks": {
        "title": "Parks and recreation",
        "icon": "tree",
        "summary": "Parks, shelter bookings, and programs for every age.",
        "intro": "Acme maintains neighborhood parks, a riverside trail, and a community pool.",
        "sections": [
            {"heading": "Featured parks", "items": [
                "Mill Pond Park: playground, picnic shelter, and a fishing dock.",
                "Lantern Hill: sledding in winter and an open lawn for events.",
                "Riverside Trail: a paved four-mile path with benches every half mile.",
            ]},
            {"heading": "Reserve a shelter", "items": [
                "Shelters seat up to 40 guests and can be booked up to six months ahead.",
                "Reservations are handled by phone or at the Recreation Office during the demonstration.",
            ]},
            {"heading": "Programs", "items": [
                "Youth swim lessons, evening pickleball, and a seniors walking club.",
            ]},
        ],
        "aside": {"heading": "Recreation Office", "lines": ["(555) 010-0170", "22 Example Lane, Acme"]},
    },
    "pay-a-bill": {
        "title": "Pay a bill",
        "icon": "card",
        "summary": "Water, sewer, and permit fee payment options.",
        "intro": "Residents can pay City bills in person, by mail, or by phone.",
        "sections": [
            {"heading": "Utility bills", "items": [
                "Water and sewer bills are issued monthly and are due 21 days after the bill date.",
                "Keep your account number from the top of the bill ready when you call.",
            ]},
            {"heading": "Permit fees", "items": [
                "Permit fees are calculated when your application is reviewed.",
                "The City tells you the amount and how to pay it once your application is approved.",
            ]},
            {"heading": "Demonstration notice", "items": [
                "This fictional website takes no payments and stores no card or bank details.",
            ]},
        ],
        "aside": {"heading": "Finance Office", "lines": ["(555) 010-0110", "Weekdays, 8:30 a.m. to 4:30 p.m."]},
    },
    "contact": {
        "title": "Contact the City",
        "icon": "phone",
        "summary": "Departments, phone numbers, and office hours.",
        "intro": "Reach the right department directly, or visit City Hall during office hours.",
        "sections": [
            {"heading": "Departments", "items": [
                "City Clerk: (555) 010-0100",
                "Planning and Permits: (555) 010-0120",
                "Finance Office: (555) 010-0110",
                "Public Works: (555) 010-0140",
                "Recreation Office: (555) 010-0170",
            ]},
            {"heading": "Visit City Hall", "items": [
                "1 Example Plaza, Acme (fictional address).",
                "Open weekdays, 8:30 a.m. to 4:30 p.m.; closed on public holidays.",
            ]},
            {"heading": "Write to us", "items": [
                "contact@city.example.invalid (a placeholder address; nothing is monitored).",
            ]},
        ],
        "aside": {"heading": "After hours", "lines": ["Non-emergency line: (555) 010-0199", "In an emergency, use your local emergency number."]},
    },
}

#: Footer pages.  They are on the website but not in its navigation.
INFO_PAGES: dict[str, dict[str, Any]] = {
    "accessibility": {
        "title": "Accessibility",
        "intro": "This is a fictional demonstration site. If any part of it is hard to use, tell Planning and Permits and ask for the same service another way.",
        "sections": [
            {"heading": "Ask for help", "items": [
                "Call Planning and Permits at (555) 010-0120 (a fictional number).",
                "Visit City Hall at 1 Example Plaza, Acme (fictional address), weekdays 8:30 a.m. to 4:30 p.m.",
            ]},
        ],
        "aside": {"heading": "Planning and Permits", "lines": ["(555) 010-0120", "Weekdays, 8:30 a.m. to 4:30 p.m."]},
    },
    "privacy": {
        "title": "Privacy",
        "intro": "This demonstration holds only fictional records. Please do not type real personal information into it.",
        "sections": [
            {"heading": "What the demonstration keeps", "items": [
                "What you enter in an application, the files you add and the actions you take are stored in the demonstration's own database so you can track them.",
                "Nothing is sent to a real city or to a real source system.",
            ]},
        ],
        "aside": {"heading": "Questions", "lines": ["Planning and Permits", "(555) 010-0120"]},
    },
}

NEWS: tuple[dict[str, str], ...] = (
    {"date": "Oct 24", "title": "Fall leaf collection begins next week", "body": "Bag leaves in paper yard-waste bags and leave them at the curb on your regular trash day."},
    {"date": "Oct 20", "title": "Online permit applications now open", "body": "Homeowners and contractors can start, save, and track permit applications from the Permits page."},
    {"date": "Oct 15", "title": "Mill Pond Park shelter closed for repairs", "body": "The picnic shelter reopens in early November. Other park areas remain open."},
)


# The layout also frames the applicant portal, whose context has no website data.
templates.env.globals["city_services"] = SERVICE_PAGES

from acme_city.applicant_portal import content as _portal_content  # noqa: E402

templates.env.globals["portal_content"] = _portal_content.content


def city_context(
    request: Request, session: Session, actor: ActorContext | None, **extra: Any
) -> dict[str, Any]:
    """Return the context every website page shares."""
    moved = request.query_params.get("moved_from", "")
    known = {screen["key"]: screen["label"] for screen in SCREENS}
    notice = (
        f"{actor_label(session, actor.actor_id)} can't open {known[moved]}, "
        "so you're on the City website instead."
        if actor is not None and moved in known
        else ""
    )
    return {
        "moved_notice": notice,
        "actor": (
            {"actor_id": actor.actor_id, "label": actor_label(session, actor.actor_id)}
            if actor is not None
            else None
        ),
        "personas": persona_options(session),
        "applicant_name": _applicant_name(session, actor),
        "fictional_demo": True,
        **extra,
    }


@router.get("/", operation_id="city_home", include_in_schema=False)
def city_home(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """The home page of the City website."""
    context = city_context(
        request, session, actor, title="Home", active_nav="home", news=NEWS
    )
    return render(request, "city/home.html", context)


@router.get("/permits", operation_id="city_permits", include_in_schema=False)
def city_permits(
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Permits and applications: where an applicant starts or resumes.

    An applicant sees two links.  Anyone else sees two buttons that post to the
    existing persona selector for the Applicant persona, so signing in happens
    behind the buttons; no grant is given here.
    """
    is_applicant = actor is not None and actor_label(session, actor.actor_id) == "Applicant"
    applicant = next(
        (p for p in persona_options(session) if p["label"] == "Applicant"), None
    )
    from acme_city.applicant_portal import content as portal_content

    context = city_context(
        request,
        session,
        actor,
        title="Permits and applications",
        active_nav="permits",
        applicant=applicant,
        is_applicant=is_applicant,
        permits_home=PERMITS_HOME,
        track_home=TRACK_HOME,
        what_you_need=portal_content.content().get("what_you_need", []),
        help_href=portal_content.content().get("share", {}).get("contact_href", "/city/contact"),
    )
    return render(request, "city/permits_entry.html", context)


def _wants_json(request: Request, format: str) -> bool:
    return format == "json" or "application/json" in request.headers.get("accept", "")


def _community_gate(
    request: Request, session: Session, actor: ActorContext | None, as_json: bool
):
    """Return a 429 response when the caller is over the rate limit, else ``None``."""
    client = request.scope.get("acme_client_ip") or (
        request.client.host if request.client else "unknown"
    )
    if community.COMMUNITY_LIMITER.allow(client):
        return None
    headers = {"Retry-After": "60"}
    if as_json:
        return JSONResponse({"detail": "Too many requests. Try again in a minute."}, 429, headers)
    context = city_context(
        request, session, actor, title="Too many requests", active_nav="permits",
        permits_crumb="/city/permits",
    )
    response = render(request, "city/rate_limited.html", context, status_code=429)
    response.headers["Retry-After"] = "60"
    return response


@router.get("/community", operation_id="city_community", include_in_schema=False)
def city_community(
    request: Request,
    q: str = "",
    type: str = "",
    format: str = "",
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """Permits in my community: public lookup and district totals (read-only)."""
    from acme_city.ui.community_view_models import (
        community_url,
        display_date,
        public_record_url,
        status_badge_class,
    )

    as_json = _wants_json(request, format)
    limited = _community_gate(request, session, actor, as_json)
    if limited is not None:
        return limited
    summary = community.community_summary(session, type=type)
    result = community.lookup(session, q) if q.strip() else None
    if as_json:
        body: dict[str, Any] = {
            "fields": list(community.PUBLIC_FIELDS),
            "total": summary["total"],
            "districts": summary["districts"],
            "synthetic_present": summary["synthetic_present"],
        }
        if result is not None:
            body["query"] = result["query"]
            body["result_total"] = result["total"]
            body["permits"] = [r.as_dict() for r in result["records"]]
        return JSONResponse(body)
    context = city_context(
        request,
        session,
        actor,
        title="Permits in my community",
        active_nav="permits",
        permits_crumb="/city/permits",
        summary=summary,
        lookup=result,
        display_date=display_date,
        status_badge_class=status_badge_class,
        public_record_url=public_record_url,
        community_url=community_url,
    )
    return render(request, "city/community.html", context)


@router.get(
    "/community/permit/{reference}", operation_id="city_community_permit", include_in_schema=False
)
def city_community_permit(
    reference: str,
    request: Request,
    format: str = "",
    q: str = "",
    type: str = "",
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """One public permit record.  A non-public case answers exactly like a missing one."""
    from acme_city.ui.community_view_models import (
        community_return_url,
        display_date,
        normalize_query,
        status_badge_class,
        status_explanation,
    )

    as_json = _wants_json(request, format)
    limited = _community_gate(request, session, actor, as_json)
    if limited is not None:
        return limited
    record = community.public_record(session, reference)
    if record is None:
        if as_json:
            return JSONResponse({"detail": "No public permit has that number."}, 404)
        context = city_context(
            request, session, actor, title="Page not found", active_nav="permits",
            permits_crumb="/city/permits",
        )
        return render(request, "city/not_found.html", context, status_code=404)
    if as_json:
        return JSONResponse(record.as_dict())
    context = city_context(
        request,
        session,
        actor,
        title=f"Permit {record.reference}",
        active_nav="permits",
        permits_crumb="/city/permits",
        record=record,
        back_url=community_return_url(q, type),
        has_return_context=bool(normalize_query(q)),
        display_date=display_date,
        status_explanation=status_explanation,
        status_badge_class=status_badge_class,
    )
    return render(request, "city/community_permit.html", context)


@router.get("/{slug}", operation_id="city_service_page", include_in_schema=False)
def city_service_page(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """One informational page of the City website."""
    page = SERVICE_PAGES.get(slug) or INFO_PAGES.get(slug)
    if page is None:
        context = city_context(
            request, session, actor, title="Page not found", active_nav=""
        )
        return render(request, "city/not_found.html", context, status_code=404)
    context = city_context(
        request, session, actor, title=page["title"], active_nav=slug, page=page
    )
    return render(request, "city/service.html", context)


__all__ = ["router"]

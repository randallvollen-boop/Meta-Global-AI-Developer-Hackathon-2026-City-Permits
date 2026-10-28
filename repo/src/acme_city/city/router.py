"""Routes of the fictional City of Acme public website.

The website is a presentation layer on the same origin as the permit
application.  It holds no data of its own and grants nothing: the Permits
entry reaches the applicant portal through the existing persona selector
(``POST /ui/actor``), and the portal keeps its own server-side checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_session
from acme_city.ui.router import render, templates, ui_actor
from acme_city.ui.view_models import SCREENS, actor_label, persona_options

router = APIRouter(prefix="/city", tags=["city-website"])

#: Where the Permits entry lands once the applicant persona is active.
PERMITS_HOME = "/apply"

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

NEWS: tuple[dict[str, str], ...] = (
    {"date": "Oct 24", "title": "Fall leaf collection begins next week", "body": "Bag leaves in paper yard-waste bags and leave them at the curb on your regular trash day."},
    {"date": "Oct 20", "title": "Online permit applications now open", "body": "Homeowners and contractors can start, save, and track permit applications from the Permits page."},
    {"date": "Oct 15", "title": "Mill Pond Park shelter closed for repairs", "body": "The picnic shelter reopens in early November. Other park areas remain open."},
)


# The layout also frames the applicant portal, whose context has no website data.
templates.env.globals["city_services"] = SERVICE_PAGES


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
    """Enter the permit services.

    An applicant goes straight to the portal.  Anyone else sees a short page
    whose button posts to the existing persona selector for the Applicant
    persona; no grant is given here.
    """
    if actor is not None and actor_label(session, actor.actor_id) == "Applicant":
        return RedirectResponse(PERMITS_HOME, status_code=303)
    applicant = next(
        (p for p in persona_options(session) if p["label"] == "Applicant"), None
    )
    context = city_context(
        request,
        session,
        actor,
        title="Permits",
        active_nav="permits",
        applicant=applicant,
        permits_home=PERMITS_HOME,
    )
    return render(request, "city/permits_entry.html", context)


@router.get("/{slug}", operation_id="city_service_page", include_in_schema=False)
def city_service_page(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: ActorContext | None = Depends(ui_actor),
):
    """One informational page of the City website."""
    page = SERVICE_PAGES.get(slug)
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

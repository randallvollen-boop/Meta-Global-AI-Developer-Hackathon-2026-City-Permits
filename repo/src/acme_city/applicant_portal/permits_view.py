"""The view model of "My permits" and of the receipt copy.

Everything here is read from the database for the acting applicant and only
for what the applicant may see:

* the applications inside the applicant's record scope, and the applicant's
  own open drafts;
* the City's requests, which are the current findings' "applicant must" line
  and the comments written *for the applicant*.  An internal comment, the
  internal message of a finding and the name of a staff member are never read
  into this model, so no template can show them;
* progress, status and the "what happens next" sentence, derived from the
  stored status.

Nothing is invented: a request, a date or an event that is not stored does not
appear.
"""
# REQUIRES: PORTAL-03, PORTAL-04, PER-04, SEC-03
# The tracker lists only the applicant's own records and shows only
# applicant-visible comments and the applicant-must line of findings.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.applicant_portal import content, forms
from acme_city.auth.context import ActorContext
from acme_city.persistence.models import gis, permit

#: The statuses in which the City waits for the applicant.
ACTION_STATUSES: frozenset[str] = frozenset({"needs_information", "revisions_requested"})

#: The statuses that close an application without a permit.
CLOSED_STATUSES: frozenset[str] = frozenset({"denied", "withdrawn", "returned", "archived"})

TABS: tuple[tuple[str, str], ...] = (
    ("active", "Active"),
    ("drafts", "Drafts"),
    ("closed", "Closed"),
)

#: Badge text and tone by status.  Colour is never the only signal: the badge
#: always carries its words.
BADGES: dict[str, tuple[str, str]] = {
    "draft": ("Draft", "neutral"),
    "submitted": ("Submitted", "info"),
    "needs_information": ("Action needed", "warn"),
    "revisions_requested": ("Action needed", "warn"),
    "ready_for_review": ("In review", "info"),
    "under_review": ("In review", "info"),
    "approved": ("Approved", "ok"),
    "issued": ("Permit issued", "ok"),
    "denied": ("Denied", "bad"),
    "withdrawn": ("Withdrawn", "neutral"),
    "returned": ("Returned", "neutral"),
    "archived": ("Archived", "neutral"),
}

#: The progress steps: (state of Submitted, Under review, Decision) and the
#: label of the last step.
_PROGRESS: dict[str, tuple[tuple[str, str, str], str]] = {
    "draft": (("todo", "todo", "todo"), "Decision"),
    "submitted": (("current", "todo", "todo"), "Decision"),
    "needs_information": (("done", "current", "todo"), "Decision"),
    "revisions_requested": (("done", "current", "todo"), "Decision"),
    "ready_for_review": (("done", "current", "todo"), "Decision"),
    "under_review": (("done", "current", "todo"), "Decision"),
    "approved": (("done", "done", "done"), "Approved"),
    "issued": (("done", "done", "done"), "Permit issued"),
    "denied": (("done", "done", "stopped"), "Denied"),
    "withdrawn": (("done", "todo", "stopped"), "Withdrawn"),
    "returned": (("done", "done", "stopped"), "Returned"),
    "archived": (("done", "todo", "stopped"), "Archived"),
}

_STATE_WORDS = {
    "done": "Completed",
    "current": "In progress",
    "todo": "Not yet",
    "stopped": "Ended",
}


def short_date(value: datetime | None) -> str:
    """Return ``Oct 28, 2026``, or an empty string."""
    if value is None:
        return ""
    return f"{value:%b} {value.day}, {value.year}"


def long_stamp(value: datetime | None) -> str:
    """Return ``Oct 28, 2026, 14:05 UTC``, or an empty string."""
    if value is None:
        return ""
    return f"{value:%b} {value.day}, {value.year}, {value:%H:%M} UTC"


def progress(status: str) -> dict[str, Any]:
    """Return the three-step progress of a status."""
    states, last = _PROGRESS.get(status, _PROGRESS["submitted"])
    labels = ("Submitted", "Under review", last)
    steps = [
        {"label": label, "state": state, "state_word": _STATE_WORDS[state]}
        for label, state in zip(labels, states)
    ]
    current = next((step for step in steps if step["state"] in {"current", "stopped"}), None)
    summary = (
        f"Progress: {current['label']}, {current['state_word'].lower()}"
        if current
        else "Progress: all steps completed"
        if all(step["state"] == "done" for step in steps)
        else "Progress: not started"
    )
    return {"steps": steps, "summary": summary}


def requests_for(
    session: Session, application: permit.Application, actor: ActorContext
) -> list[dict[str, str]]:
    """Return what the City is asking of the applicant, applicant-visible only.

    A request is the "applicant must" line of a current finding, or a comment
    written for the applicant.  The internal message of a finding and any
    internal comment are not read.
    """
    from acme_city.agents.findings import current_findings
    from acme_city.permits.comments import comments_for

    titles = content.content().get("request_titles", {})
    out: list[dict[str, str]] = []
    for finding in current_findings(session, application.id):
        if finding.waived_at is not None:
            continue
        must = str(finding.applicant_must or "").strip()
        if not must:
            continue
        out.append(
            {
                "kind": "finding",
                "title": titles.get(finding.finding_type, "The City needs something"),
                "text": must,
                "at": long_stamp(finding.created_at),
                "when": finding.created_at,
            }
        )
    for comment in comments_for(session, application.id, actor):
        if comment.visibility != "applicant":
            continue
        out.append(
            {
                "kind": "comment",
                "title": titles.get("comment", "A message from the City"),
                "text": comment.body,
                "at": long_stamp(comment.created_at),
                "when": comment.created_at,
            }
        )
    return out


def activity_for(
    session: Session,
    application: permit.Application,
    actor: ActorContext,
    reference: str,
) -> list[dict[str, Any]]:
    """Return the dated, applicant-visible events of one application."""
    from acme_city.permits.comments import comments_for

    events: list[tuple[datetime, str, str]] = []
    if application.initial_submitted_at is not None:
        events.append((application.initial_submitted_at, "Application submitted", ""))
    if (
        application.revision_submitted_at is not None
        and application.revision_submitted_at != application.initial_submitted_at
    ):
        events.append((application.revision_submitted_at, "You sent your response to the City", ""))
    for request in requests_for(session, application, actor):
        if request["kind"] == "finding":
            events.append((request["when"], "The City asked for something", request["text"]))
    for comment in comments_for(session, application.id, actor):
        if comment.visibility == "applicant":
            events.append((comment.created_at, "The City sent you a message", comment.body))
    decision = session.execute(
        select(permit.Decision)
        .where(permit.Decision.application_id == application.id, permit.Decision.stale.is_(False))
        .order_by(permit.Decision.decided_at.desc())
    ).scalars().first()
    if decision is not None and application.status in {"approved", "denied", "issued"}:
        events.append((decision.decided_at, "The City recorded its decision", ""))
    issued = session.execute(
        select(permit.Permit)
        .where(permit.Permit.application_id == application.id)
        .order_by(permit.Permit.issued_at.desc())
    ).scalars().first()
    if issued is not None and application.status == "issued":
        events.append((issued.issued_at, "Your permit was issued", ""))
    events.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "reference": reference,
            "when": when,
            "date": short_date(when),
            "stamp": long_stamp(when),
            "title": title,
            "text": text,
        }
        for when, title, text in events
    ]


def _address(application: permit.Application) -> str:
    facts = application.submitted_facts or {}
    return str(facts.get("submitted_site_text") or facts.get("property_address") or "")


def application_card(
    session: Session,
    application: permit.Application,
    permit_type: permit.PermitType | None,
    actor: ActorContext,
) -> dict[str, Any]:
    """Return the card of one submitted application."""
    from acme_city.applicant_portal.service import STATUS_WORDS

    status = application.status
    badge_text, badge_tone = BADGES.get(status, (status.replace("_", " ").capitalize(), "neutral"))
    reference = application.source_application_number
    requests = requests_for(session, application, actor) if status in ACTION_STATUSES else []
    if status in ACTION_STATUSES and not requests:
        # The City asked but left nothing the applicant may read: say so plainly.
        requests = [
            {
                "kind": "status",
                "title": "The City needs more from you",
                "text": "Open the application to see how to respond.",
                "at": "",
                "when": None,
            }
        ]
    base = f"/apply/track?ref={reference}"
    if status == "issued":
        primary = {"label": "Download permit", "href": f"/apply/permit/{reference}"}
    elif status in ACTION_STATUSES:
        primary = {"label": "Respond to request", "href": f"{base}#respond"}
    else:
        primary = {"label": "View application", "href": base}
    steps = progress(status)
    return {
        "kind": "application",
        "application_id": application.id,
        "reference": reference,
        "title": permit_type.label if permit_type else "Permit application",
        "type_key": permit_type.key if permit_type else "",
        "address": _address(application),
        "status": status,
        "status_word": STATUS_WORDS.get(status, status),
        "badge": {"text": badge_text, "tone": badge_tone},
        "action_needed": status in ACTION_STATUSES,
        "request": requests[0] if requests else None,
        "more_requests": max(len(requests) - 1, 0),
        "progress": steps,
        "submitted_date": short_date(application.initial_submitted_at),
        "submitted_stamp": long_stamp(application.initial_submitted_at),
        "primary": primary,
        "view_href": base,
        "request_href": f"{base}#request",
        "download_href": f"/apply/submitted/{reference}/copy",
        "next_step": content.next_step(
            status,
            target_days=int(permit_type.service_target_days or 0) if permit_type else None,
        ),
        "closed": status in CLOSED_STATUSES,
    }


def draft_card(draft: gis.ApplicationDraft, type_labels: dict[str, str]) -> dict[str, Any]:
    """Return the card of one open draft."""
    values = dict((draft.data or {}).get("values") or {})
    return {
        "kind": "draft",
        "reference": draft.reference,
        "title": type_labels.get(draft.permit_type_key, "Permit application"),
        "type_key": draft.permit_type_key,
        "address": str(values.get("address_text") or ""),
        "status": "draft",
        "status_word": "Draft",
        "badge": {"text": BADGES["draft"][0], "tone": BADGES["draft"][1]},
        "action_needed": False,
        "request": None,
        "more_requests": 0,
        "progress": progress("draft"),
        "submitted_date": "",
        "saved_date": short_date(draft.updated_at or draft.created_at),
        "primary": {
            "label": "Continue application",
            "href": f"/apply/{draft.permit_type_key}?draft={draft.reference}",
        },
        "view_href": "",
        "download_href": "",
        "next_step": content.next_step("draft"),
        "closed": False,
    }


def my_permits(
    session: Session,
    actor: ActorContext,
    *,
    tab: str = "",
) -> dict[str, Any]:
    """Return everything the "My permits" list shows, from the stored records."""
    from acme_city.applicant_portal.service import PortalService
    from acme_city.ui.view_models import visible_applications

    service = PortalService(session)
    types = {
        row.id: row
        for row in session.execute(select(permit.PermitType)).scalars().all()
    }
    cards = [
        application_card(session, row, types.get(row.permit_type_id), actor)
        for row in visible_applications(session, actor)
        if row.status != "draft"
    ]
    labels = {row.key: row.label for row in types.values()}
    drafts = [draft_card(row, labels) for row in service.my_drafts(actor)]
    active = [card for card in cards if not card["closed"]]
    closed = [card for card in cards if card["closed"]]
    by_tab = {"active": active, "drafts": drafts, "closed": closed}
    counts = {key: len(by_tab[key]) for key, _label in TABS}
    selected = tab if tab in by_tab else ""
    if not selected:
        selected = next((key for key, _label in TABS if counts[key]), "active")
    shown = by_tab[selected]
    focus = next((card for card in active if card["action_needed"]), None) or (
        active[0] if active else None
    )
    activity: list[dict[str, Any]] = []
    for row in visible_applications(session, actor):
        if row.status == "draft":
            continue
        activity.extend(activity_for(session, row, actor, row.source_application_number))
    activity.sort(key=lambda item: item["when"], reverse=True)
    return {
        "tabs": [
            {"key": key, "label": label, "count": counts[key], "selected": key == selected}
            for key, label in TABS
        ],
        "selected": selected,
        "cards": shown,
        "empty": not any(counts.values()),
        "next_step": (focus or {}).get("next_step") or content.content().get("next_step_empty", ""),
        "next_step_reference": (focus or {}).get("reference", ""),
        "activity": activity[:6],
    }


__all__ = [
    "ACTION_STATUSES",
    "BADGES",
    "CLOSED_STATUSES",
    "TABS",
    "activity_for",
    "application_card",
    "draft_card",
    "long_stamp",
    "my_permits",
    "progress",
    "requests_for",
    "short_date",
]

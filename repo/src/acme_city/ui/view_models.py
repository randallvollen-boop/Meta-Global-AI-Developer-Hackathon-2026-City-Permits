"""Server-side view models for the eight ACME City screens.

The pages are rendered from the dictionaries this module builds.  A view model
never decides anything: it reports what the domain services recorded, names
the destination of an action, and explains why an action is not available to
the acting persona.  The responsibility, evidence and history panels are built
here so that every governed view shows the same eight facts.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-02, EDIT-03, SEC-02
# The view models report the resolved responsibility, the current, submitted,
# proposed and issued values, the permitted actions with their reasons, and the
# evidence and history of every governed record.

from __future__ import annotations

import json

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.agents.findings import WAIVABLE_TYPES
from acme_city.changes.service import ChangeService
from acme_city.changes.state_machine import permitted_targets
from acme_city.core.clock import utc_now
from acme_city.finance.service import FinanceService
from acme_city.governance.service import GovernanceService
from acme_city.muse.schemas import PRIVATE_TASKS
from acme_city.permits.comments import comment_view, comments_for
from acme_city.persistence.models import (
    agent,
    audit,
    change,
    finance,
    governance,
    model_run,
    permit,
    registry,
    source,
)
from acme_city.permits.service import PermitService
from acme_city.registry.provenance import crosswalk_view
from acme_city.registry.service import RegistryService
from acme_city.rules.service import RuleCatalogService
from acme_city.ui import agent_views, property_views, reviewer_views

#: The required screens, in the order the navigation shows them.
SCREENS: tuple[dict[str, str], ...] = (
    {"key": "queue", "label": "Work queue", "href": "/queue"},
    {"key": "applicants", "label": "Applicants", "href": "/applicants"},
    {
        "key": "masters",
        "label": "Properties, businesses and contractors",
        "href": "/masters",
    },
    {"key": "permit", "label": "Permit workspace", "href": ""},
    {"key": "steward", "label": "Steward review", "href": "/steward"},
    {"key": "rules", "label": "Rules and fees", "href": "/rules-fees"},
    {"key": "reconciliation", "label": "Reconciliation", "href": "/reconciliation"},
    {"key": "governance", "label": "Governance and sources", "href": "/governance"},
    {"key": "agent_intake", "label": "Intake agent", "href": "/agent/intake"},
    {
        "key": "agent_adjudication",
        "label": "Adjudication agent",
        "href": "/agent/adjudication",
    },
    {"key": "admin", "label": "Administration", "href": "/admin"},
    {
        "key": "intake_queue",
        "label": "Intake queue",
        "href": "/queue/intake",
    },
    {
        "key": "early_resolution",
        "label": "Early resolution",
        "href": "/queue/early-resolution",
    },
    {
        "key": "review_queue",
        "label": "Review queue",
        "href": "/queue/review",
    },
    {
        "key": "insight_city",
        "label": "City view",
        "href": "/insight/city",
    },
    {
        "key": "policy_scenarios",
        "label": "What-if",
        "href": "/policy/scenarios",
    },
)

#: The labels of the four selectable personas, in selector order.
PERSONA_ORDER: tuple[str, ...] = (
    "Applicant",
    "Data Steward",
    "Permit Reviewer",
    "City Administrator",
)

#: The domain that owns each screen.
SCREEN_DOMAIN: dict[str, str] = {
    "queue": "permits",
    "applicants": "applicants",
    "masters": "parcels",
    "permit": "permits",
    "steward": "applicants",
    "rules": "building_rules",
    "reconciliation": "finance",
    "governance": "records",
    "agent_intake": "permits",
    "agent_adjudication": "permits",
    "admin": "records",
    "intake_queue": "permits",
    "early_resolution": "permits",
    "review_queue": "permits",
    "insight_city": "permits",
    "policy_scenarios": "permits",
}

#: The actions a screen may offer, with the grant and the domain each one needs.
#:
#: A screen is opened when the actor holds at least one of these grants for
#: the domain of the screen.  A grant that is not bound to a domain covers
#: every domain.
SCREEN_PERMISSIONS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "queue": (
        ("application.submit", "permits"),
        ("application.revision.submit", "permits"),
        ("application.evaluate", "permits"),
        ("permit.decide", "permits"),
        ("permit.issue", "permits"),
        ("change.case.transition", None),
        ("correction.request.submit", None),
    ),
    "applicants": (
        ("applicant.profile.edit", "applicants"),
        ("registry.provenance.view", "applicants"),
        ("correction.request.submit", None),
    ),
    "masters": (
        ("source.record.update", "parcels"),
        ("registry.provenance.view", "parcels"),
        ("finance.account.link", "finance"),
    ),
    "permit": (
        ("application.submit", "permits"),
        ("application.revision.submit", "permits"),
        ("application.evaluate", "permits"),
        ("permit.decide", "permits"),
        ("permit.issue", "permits"),
        ("records.document.view", None),
        ("correction.request.submit", None),
    ),
    "steward": (
        ("registry.crosswalk.propose", "applicants"),
        ("registry.crosswalk.decide", "applicants"),
        ("change.case.transition", None),
        ("source.record.update", "applicants"),
    ),
    "rules": (
        ("rule.version.draft", "building_rules"),
        ("rule.version.approve", "building_rules"),
        ("rule.version.publish", "building_rules"),
    ),
    "reconciliation": (
        ("finance.assessment.create", "finance"),
        ("finance.payment.import", "finance"),
        ("finance.allocation.confirm", "finance"),
    ),
    "governance": (
        ("governance.dataset.register", None),
        ("governance.assignment.manage", "records"),
        ("governance.authority_policy.manage", "records"),
        ("governance.authority_policy.publish", "records"),
        ("governance.queue.manage", None),
        ("records.audit.view", None),
    ),
    "agent_intake": (
        ("agent.run.intake", "permits"),
        ("agent.toggle", None),
    ),
    "agent_adjudication": (
        ("agent.run.adjudication", "permits"),
        ("agent.toggle", None),
    ),
    "property": (("property.view", None),),
    "portal": (("application.submit", "permits"),),
    "admin": (
        ("config.manage", None),
        ("admin.actor.manage", None),
        ("records.configuration.view", None),
    ),
    # The intake queue and the early-resolution board are the Data Steward's
    # work.  The review queue is the Permit Reviewer's.  Each is opened by a
    # grant only that persona holds, never by a persona label.
    "intake_queue": (("permit.intake.process_selected", "permits"),),
    "early_resolution": (("permit.case.advance", "permits"),),
    "review_queue": (("permit.decide", "permits"),),
    # The City view is the City Administrator's read-only picture of permit
    # activity, opened by its own grant.
    "insight_city": (("insight.city.view", None),),
    # The what-if screens are the City Administrator's, opened by their own
    # policy grants.  The run and briefing keys exist for their help entries;
    # the service checks the run and briefing grants again on every read.
    "policy_scenarios": (("policy.scenario.manage", None),),
    "policy_run": (("policy.run.view", None),),
    "policy_briefing": (("policy.brief.view", None),),
}


#: The saved queues the shared work queue links to, with the grant each one
#: needs.  The link is shown only to a persona that holds the grant.
QUEUE_LINKS: tuple[dict[str, Any], ...] = (
    {
        "key": "intake_queue",
        "label": "Intake queue",
        "href": "/queue/intake",
        "permission": "permit.intake.process_selected",
        "domain_id": "permits",
        "note": "the saved views of the cases that arrived and wait for the City",
    },
    {
        "key": "early_resolution",
        "label": "Early resolution",
        "href": "/queue/early-resolution",
        "permission": "permit.case.advance",
        "domain_id": "permits",
        "note": "the cases that wait for a person, grouped by their primary finding",
    },
    {
        "key": "review_queue",
        "label": "Review queue",
        "href": "/queue/review",
        "permission": "permit.decide",
        "domain_id": "permits",
        "note": "the cases that are with the Permit Reviewer",
    },
)


# --------------------------------------------------------------------- helpers


def _iso(value: datetime | None) -> str | None:
    """Return a display-safe timestamp."""
    return None if value is None else value.isoformat()


def _age_days(since: datetime | None, now: datetime | None = None) -> int | None:
    """Return the age of a record in whole days."""
    if since is None:
        return None
    moment = now or utc_now()
    return max((moment - since).days, 0)


def allows(
    session: Session,
    actor: ActorContext,
    permission: str,
    domain_id: str | None = None,
    record_ids: tuple[str, ...] = (),
) -> bool:
    """Return whether the actor holds a grant for one action."""
    return PermissionResolver(session).allows(
        actor,
        permission,
        ResourceContext(domain_id=domain_id, record_ids=record_ids),
    )


def holds_grant(
    session: Session,
    actor: ActorContext,
    permission: str,
    domain_id: str | None = None,
) -> bool:
    """Return whether the actor holds a grant for an action in a domain.

    The record scope of the grant is not applied here: this answers whether
    the persona may open a screen at all.  The record scope still decides
    which records the persona may read and which records it may change.
    """
    for grant in PermissionResolver(session).grants_for(actor.actor_id):
        if grant.action != permission:
            continue
        if grant.domain_id is None:
            return True
        if domain_id is not None and grant.domain_id == domain_id:
            return True
    return False


def actor_department(session: Session, actor_id: str | None) -> str:
    """Return the department on an actor record (display information only)."""
    if not actor_id:
        return ""
    row = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id == actor_id)
    ).scalar_one_or_none()
    return (row.department or "") if row is not None else ""


def actor_label(session: Session, actor_id: str | None) -> str:
    """Return the display label of one actor."""
    if not actor_id:
        return "unassigned"
    row = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id == actor_id)
    ).scalar_one_or_none()
    return row.label if row is not None else actor_id


def _lifecycle_panel(
    session: Session, actor: ActorContext, application: permit.Application
) -> dict[str, Any]:
    """Return the lifecycle panel of one case.

    The panel names the actions the acting persona may take, the reason codes
    each action may use and the people a case may be routed to.  It decides
    nothing: the server checks the grant, the version and the state again
    when the action arrives.
    """
    from acme_city.agents.findings import blocking_findings
    from acme_city.configuration.reasons import active_reason_codes
    from acme_city.permits.comments import is_staff
    from acme_city.permits.routing import RoutingService, stage_of

    routing = RoutingService(session)
    stage = stage_of(application)
    archived = application.status == "archived"
    owner = (
        actor_label(session, application.owner_actor_id)
        if application.owner_actor_id
        else ""
    )
    return {
        "archived": archived,
        "status_before_archive": application.status_before_archive or "",
        "priority": application.priority,
        "owner_actor_id": application.owner_actor_id or "",
        "owner_label": owner,
        "stage": stage or "",
        "can_return": allows(session, actor, "permit.case.return", "permits")
        and application.status in ("needs_information",),
        "can_advance": allows(session, actor, "permit.case.advance", "permits")
        and application.status in ("needs_information",),
        "can_request_revisions": allows(
            session, actor, "permit.case.request_revisions", "permits"
        )
        and application.status in ("ready_for_review", "under_review"),
        "can_archive": allows(session, actor, "permit.case.archive", "permits")
        and not archived
        and application.status != "issued",
        "can_restore": allows(session, actor, "permit.case.restore", "permits")
        and archived,
        "can_set_priority": allows(session, actor, "permit.case.priority", "permits")
        and not archived,
        "can_assign": allows(session, actor, "permit.case.assign", "permits")
        and stage is not None,
        "can_waive": allows(session, actor, "permit.finding.waive", "permits")
        and not archived,
        "can_comment": allows(session, actor, "permit.case.comment", "permits")
        and not archived,
        "is_staff": is_staff(session, actor),
        "reason_codes": {
            "return": [
                snapshot.as_dict()
                for snapshot in active_reason_codes(session, code_type="return")
            ],
            "denial": [
                snapshot.as_dict()
                for snapshot in active_reason_codes(session, code_type="denial")
            ],
            "revision": [
                snapshot.as_dict()
                for snapshot in active_reason_codes(session, code_type="revision")
            ],
            "archive": [
                snapshot.as_dict()
                for snapshot in active_reason_codes(session, code_type="archive")
            ],
            "waiver": [
                snapshot.as_dict()
                for snapshot in active_reason_codes(session, code_type="waiver")
            ],
        },
        "eligible_owners": (
            routing.eligible_owners(stage) if stage is not None else []
        ),
        "blocking_findings": [
            {
                "finding_id": row.id,
                "finding_type": row.finding_type,
                "message": row.message,
            }
            for row in blocking_findings(session, application.id)
        ],
    }


def persona_options(session: Session) -> list[dict[str, str]]:
    """Return the four selectable personas of the demonstration.

    Only an active, selectable actor is offered.  A service identity is never
    selectable and never appears in the selector.
    """
    rows = session.execute(
        select(governance.Actor)
        .where(governance.Actor.active.is_(True), governance.Actor.selectable.is_(True))
        .order_by(governance.Actor.actor_id)
    ).scalars().all()
    options = [{"actor_id": row.actor_id, "label": row.label} for row in rows]
    options.sort(key=lambda option: _persona_rank(option["label"]))
    return options


def _persona_rank(label: str) -> int:
    """Return the selector position of one persona label."""
    try:
        return PERSONA_ORDER.index(label)
    except ValueError:
        return len(PERSONA_ORDER)


def visible_applications(session: Session, actor: ActorContext) -> list[permit.Application]:
    """Return the applications the actor may see."""
    # A synthetic row is a generated historical record, not work: it never
    # appears in a queue.  The City view and the community view read it.
    rows = session.execute(
        select(permit.Application)
        .where(permit.Application.synthetic.is_(False))
        .order_by(permit.Application.source_application_number)
    ).scalars().all()
    return [row for row in rows if _application_in_scope(actor, row)]


def _application_in_scope(actor: ActorContext, application: permit.Application) -> bool:
    """Return whether an application is inside the actor's record scope."""
    if not actor.record_scope:
        return True
    return (
        application.source_application_number in actor.record_scope
        or (application.applicant_party_id or "") in actor.record_scope
        or application.id in actor.record_scope
    )


def visible_parties(session: Session, actor: ActorContext) -> list[registry.Party]:
    """Return the canonical parties the actor may see."""
    rows = session.execute(
        select(registry.Party).order_by(registry.Party.display_name)
    ).scalars().all()
    if not actor.record_scope:
        return list(rows)
    return [row for row in rows if row.id in actor.record_scope]


def navigation(session: Session, actor: ActorContext) -> list[dict[str, Any]]:
    """Return the navigation entries the acting persona may open.

    Only screens for which the persona holds at least one grant in
    ``SCREEN_PERMISSIONS`` are listed, using the exact predicate the screen
    guard uses, so the menu and a 403 can never disagree. Order and labels
    stay the canonical ``SCREENS`` order for every persona. The Permit
    workspace entry appears only when the persona may open a permit *and*
    a visible application exists to open.
    """
    permit_href = ""
    applications = visible_applications(session, actor)
    if applications:
        permit_href = f"/permits/{applications[0].id}"
    items: list[dict[str, Any]] = []
    for screen in SCREENS:
        key = screen["key"]
        permissions = SCREEN_PERMISSIONS.get(key, ())
        if not any(
            holds_grant(session, actor, permission, domain_id)
            for permission, domain_id in permissions
        ):
            continue
        if key == "permit" and not permit_href:
            continue
        item = dict(screen)
        if item["key"] == "permit":
            item["href"] = permit_href
        items.append(item)
    # Count badges come only from counts the view models already have: the
    # acting persona's work queue, scoped exactly as the queue scopes it.
    try:
        queue = work_queue(session, actor)
        total = len(queue.get("entries") or [])
    except Exception:
        total = 0
    for item in items:
        if item["key"] == "queue" and total:
            item["count"] = total
    return items


def screen_for_path(path: str) -> str | None:
    """Return the staff screen key a path belongs to, or ``None`` for any other path.

    The longest matching ``SCREENS`` href wins, so ``/queue/intake`` is the intake
    queue and not the work queue. A case page is the permit workspace.
    """
    path = path.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
    if path.startswith("/permits/"):
        return "permit"
    best: tuple[int, str] | None = None
    for screen in SCREENS:
        href = screen["href"]
        if href and (path == href or path.startswith(href + "/")):
            if best is None or len(href) > best[0]:
                best = (len(href), screen["key"])
    return best[1] if best else None


def screen_label(key: str) -> str:
    return next((screen["label"] for screen in SCREENS if screen["key"] == key), key)


def may_open_screen(session: Session, actor: ActorContext, key: str) -> bool:
    """Return whether the persona holds a grant for a screen (the guard's own predicate)."""
    return any(
        holds_grant(session, actor, permission, domain_id)
        for permission, domain_id in SCREEN_PERMISSIONS.get(key, ())
    )


def home_for(session: Session, actor: ActorContext) -> dict[str, str]:
    """Return the first screen of the persona's own navigation.

    A persona with no staff screen (the Applicant) lands on the City website.
    """
    for item in navigation(session, actor):
        if item.get("href"):
            return {"label": item["label"], "href": item["href"], "key": item["key"]}
    return {"label": "the City website", "href": "/city/", "key": "city"}


def queue_links(session: Session, actor: ActorContext) -> list[dict[str, Any]]:
    """Return the saved queues the acting persona may open from the work queue.

    A link is shown only when the persona holds the grant of the queue, so
    the shared work queue keeps the behaviour of every other persona.
    """
    links: list[dict[str, Any]] = []
    for entry in QUEUE_LINKS:
        if not holds_grant(
            session, actor, entry["permission"], entry["domain_id"]
        ):
            continue
        links.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "href": entry["href"],
                "note": entry["note"],
            }
        )
    return links


# --------------------------------------------------------------- responsibility


def correction_destination(
    session: Session,
    domain_id: str,
    source_system_id: str | None = None,
    dataset_key: str | None = None,
) -> str | None:
    """Return where a correction of one field group is actually made.

    The authority policy names the destination of a field group.  When the
    record has no policy of its own, the registered contract of the domain
    names the route.
    """
    policies = session.execute(
        select(governance.AuthorityPolicy)
        .where(governance.AuthorityPolicy.domain_id == domain_id)
        .order_by(governance.AuthorityPolicy.policy_id)
    ).scalars().all()
    if source_system_id:
        for policy in policies:
            if policy.authoritative_source_system_id != source_system_id:
                continue
            if dataset_key and policy.authoritative_dataset_key != dataset_key:
                continue
            return policy.change_destination
    if policies:
        return policies[0].change_destination
    contracts = session.execute(
        select(governance.SourceContract)
        .where(governance.SourceContract.domain_id == domain_id)
        .order_by(governance.SourceContract.contract_id)
    ).scalars().all()
    for contract in contracts:
        if contract.correction_route:
            return contract.correction_route
    return None


def source_times(
    session: Session,
    source_system_id: str | None,
    dataset_key: str | None = None,
    source_record_id: str | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Return the last source update and the last receipt of a source record.

    The two times are separate: arrival time never substitutes for the time
    the source itself reported.
    """
    if not source_system_id:
        return None, None
    statement = select(source.SourceSnapshot).where(
        source.SourceSnapshot.source_system_id == source_system_id
    )
    if dataset_key:
        statement = statement.where(source.SourceSnapshot.source_dataset_id == dataset_key)
    if source_record_id:
        statement = statement.where(source.SourceSnapshot.source_record_id == source_record_id)
    rows = session.execute(statement).scalars().all()
    last_update = max(
        (row.source_updated_at for row in rows if row.source_updated_at is not None),
        default=None,
    )
    last_received = max(
        (row.ingested_at for row in rows if row.ingested_at is not None),
        default=None,
    )
    return last_update, last_received


def open_issues(session: Session, subject_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return the open issues and open change cases of the given records."""
    if not subject_ids:
        return []
    issues = session.execute(
        select(change.GovernanceIssue).where(
            change.GovernanceIssue.subject_id.in_(subject_ids),
            change.GovernanceIssue.status == "open",
        )
    ).scalars().all()
    cases = session.execute(
        select(change.ChangeCase).where(
            change.ChangeCase.target_id.in_(subject_ids),
            change.ChangeCase.status.notin_(("closed", "rejected")),
        )
    ).scalars().all()
    entries = [
        {
            "issue_id": row.id,
            "kind": "governance issue",
            "type": row.issue_type,
            "detail": row.description,
            "blocking": bool(row.blocking),
            "assigned_actor_id": row.assigned_actor_id,
            "status": row.status,
            "version": row.version,
        }
        for row in issues
    ]
    entries.extend(
        {
            "issue_id": row.id,
            "kind": "change case",
            "type": row.change_kind,
            "detail": row.title,
            "blocking": row.status not in ("closed", "rejected"),
            "assigned_actor_id": row.assignee_actor_id,
            "status": row.status,
            "version": row.version,
        }
        for row in cases
    )
    entries.sort(key=lambda entry: (entry["status"], entry["issue_id"]))
    return entries


def responsibility(
    session: Session,
    *,
    domain_id: str,
    version: int | None = None,
    source_system_id: str | None = None,
    dataset_key: str | None = None,
    source_record_id: str | None = None,
    subject_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return the resolved responsibility panel of a governed record.

    The panel always answers the same eight questions: who owns the record,
    who stewards it, which source owns the facts, where a correction is made,
    when the source last updated the record, when it was last received, which
    version is current, and which issues are open.
    """
    service = GovernanceService(session)
    panel = service.responsibility_panel(domain_id)
    domain = session.execute(
        select(governance.Domain).where(governance.Domain.domain_id == domain_id)
    ).scalar_one_or_none()
    queue = None
    if domain is not None and domain.steward_queue_id:
        queue = session.execute(
            select(governance.StewardQueue).where(
                governance.StewardQueue.queue_id == domain.steward_queue_id
            )
        ).scalar_one_or_none()
    last_update, last_received = source_times(
        session, source_system_id, dataset_key, source_record_id
    )
    assignments = list(panel.get("assignments") or [])
    target = None
    if queue is not None:
        target = (
            f"{queue.first_review_target_quantity} {queue.first_review_target_unit}"
        )
    return {
        "domain_id": domain_id,
        "domain_label": domain.label if domain is not None else domain_id,
        "owner": panel.get("owner"),
        "owner_label": actor_label(session, panel.get("owner")),
        "steward": panel.get("steward"),
        "steward_label": actor_label(session, panel.get("steward")),
        "source": source_system_id or panel.get("source"),
        "source_label": _source_label(session, source_system_id or panel.get("source")),
        "change_this_in": correction_destination(
            session, domain_id, source_system_id, dataset_key
        ),
        "last_source_update": _iso(last_update),
        "last_received": _iso(last_received),
        "version": version if version is not None else panel.get("version"),
        "open_issues": open_issues(session, subject_ids),
        "queue": panel.get("queue"),
        "queue_label": queue.label if queue is not None else None,
        "response_target": target,
        "service_promise": bool(queue.service_promise) if queue is not None else False,
        "assignments": assignments,
        "custodian": domain.system_custodian_actor_id if domain is not None else None,
    }


def _source_label(session: Session, source_system_id: str | None) -> str | None:
    """Return the display label of a source system."""
    if not source_system_id:
        return None
    row = session.execute(
        select(source.SourceSystem).where(
            source.SourceSystem.source_system_id == source_system_id
        )
    ).scalar_one_or_none()
    return row.label if row is not None else source_system_id


# --------------------------------------------------------------------- actions


def action(
    session: Session,
    actor: ActorContext,
    *,
    action_id: str,
    label: str,
    path: str,
    permission: str,
    domain_id: str | None = None,
    record_ids: tuple[str, ...] = (),
    destination: str = "",
    description: str = "",
    expected_version: int | None = None,
    state_allowed: bool = True,
    state_reason: str = "",
    fields: tuple[dict[str, Any], ...] = (),
    method: str = "post",
    confirm: str = "",
) -> dict[str, Any]:
    """Return one explicit action and whether the actor may perform it.

    An action names the grant it needs, the destination it writes to and the
    version it expects.  When it is not permitted, the reason says whether the
    restriction is the grant, the state of the record or an open issue.
    """
    holds_grant_here = allows(session, actor, permission, domain_id, record_ids)
    permitted = state_allowed and holds_grant_here
    reasons: list[str] = []
    if not state_allowed:
        reasons.append(state_reason)
    # The grant is blamed only when the persona really lacks it.  A persona
    # that holds the grant but meets a state guard sees the state reason alone.
    if not holds_grant_here:
        reasons.append(
            f"your persona does not hold the {permission!r} grant for this record; "
            "the responsible steward or the named queue may perform it"
        )
    reason = " ".join(reasons)
    return {
        "action_id": action_id,
        "label": label,
        "path": path,
        "method": method,
        "permission": permission,
        "destination": destination,
        "description": description,
        "expected_version": expected_version,
        "permitted": permitted,
        "reason": reason,
        "fields": list(fields),
        "confirm": confirm,
    }


def denied_action_explanations(actions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return the explanations of the actions that are not permitted."""
    return [
        {
            "action_id": item["action_id"],
            "label": item["label"],
            "reason": item["reason"],
            "destination": item.get("destination", ""),
        }
        for item in actions
        if not item.get("permitted", False)
    ]


def _field(
    name: str,
    label: str,
    *,
    field_type: str = "text",
    value: str = "",
    options: tuple[str, ...] = (),
    required: bool = False,
    hint: str = "",
) -> dict[str, Any]:
    """Return one form field of an action."""
    return {
        "name": name,
        "label": label,
        "type": field_type,
        "value": value,
        "options": list(options),
        "required": required,
        "hint": hint,
    }


def allowed_actions_for(
    session: Session,
    actor: ActorContext,
    screen: str,
    record_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the explicit actions of one screen for the acting persona.

    Every action names the grant it needs, the destination it writes to and
    the fields it posts.  An action that the persona may not perform is still
    reported, with the reason it is unavailable.
    """
    actions: list[dict[str, Any]] = []
    payload = detail or {}
    from acme_city.configuration.reasons import active_reason_codes

    # A denial names an active denial reason code.  The service refuses a
    # denial that names none, so the form only offers the codes.
    denial_codes = tuple(
        snapshot.code for snapshot in active_reason_codes(session, code_type="denial")
    )

    if screen == "queue":
        actions.append(
            action(
                session,
                actor,
                action_id="change.dispatch",
                label="Dispatch pending source commands",
                path="/ui/actions/change.dispatch",
                permission="change.case.transition",
                destination="Simulated source adapters",
                description=(
                    "Send the commands that are waiting for their source and deliver "
                    "the pending publications."
                ),
                fields=(),
            )
        )

    if screen == "applicants":
        source_record = _applicant_source_record(session, record_id)
        actions.append(
            action(
                session,
                actor,
                action_id="source.write",
                label="Edit contact details",
                path="/ui/actions/source.write",
                permission="source.record.update",
                domain_id="applicants",
                record_ids=tuple(
                    item
                    for item in (record_id, source_record["record_id"] if source_record else "")
                    if item
                ),
                destination="Permitting applicant profile",
                description=(
                    "Write a new version of the applicant profile in the simulated "
                    "Permitting source and read the acknowledgement."
                ),
                expected_version=source_record["version"] if source_record else None,
                fields=(
                    _field("source_system_id", "Source system", value="permitting", field_type="hidden"),
                    _field(
                        "dataset_key",
                        "Dataset",
                        value="applicant_profiles",
                        field_type="hidden",
                    ),
                    _field(
                        "record_id",
                        "Source record",
                        value=source_record["record_id"] if source_record else "",
                        field_type="hidden",
                    ),
                    _field(
                        "expected_version",
                        "Expected source version",
                        value=source_record["version"] if source_record else "",
                        field_type="hidden",
                    ),
                    _field("payload", "New profile (JSON)", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="change.request",
                label="Request identity correction",
                path="/ui/actions/change.request",
                permission="correction.request.submit",
                destination="Configured steward queue",
                description=(
                    "Ask the responsible steward to correct the identity of this "
                    "applicant."
                ),
                fields=(
                    _field("target_type", "Target type", value="party", field_type="hidden"),
                    _field("target_id", "Target", value=record_id or "", field_type="hidden"),
                    _field("change_kind", "Change kind", value="identity", field_type="hidden"),
                    _field("title", "Summary", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                    _field("old_value", "Current value (JSON)", field_type="textarea"),
                    _field("proposed_value", "Proposed value (JSON)", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="registry.propose",
                label="Review match",
                path="/ui/actions/registry.propose",
                permission="registry.crosswalk.propose",
                domain_id="applicants",
                destination="Registry candidate comparison",
                description=(
                    "Compare a source record with the canonical parties and record "
                    "the evidence. A steward still has to decide."
                ),
                fields=(
                    _field("source_system_id", "Source system", value="permitting", required=True),
                    _field("dataset_key", "Dataset", value="applicant_profiles", required=True),
                    _field("source_record_id", "Source record", required=True),
                    _field("notes", "Note", field_type="textarea"),
                ),
            )
        )

    if screen == "masters":
        domain_id = payload.get("domain_id", "businesses")
        source = payload.get("source_record") or {}
        actions.append(
            action(
                session,
                actor,
                action_id="source.write",
                label="Open source record",
                path="/ui/actions/source.write",
                permission="source.record.update",
                domain_id=domain_id,
                record_ids=(source.get("record_id", ""),) if source else (),
                destination=source.get("destination", "Simulated source system"),
                description=(
                    "Write a new version of the source record and read the "
                    "acknowledgement of the source."
                ),
                expected_version=source.get("version"),
                fields=(
                    _field(
                        "source_system_id",
                        "Source system",
                        value=source.get("source_system_id", ""),
                        field_type="hidden",
                    ),
                    _field(
                        "dataset_key",
                        "Dataset",
                        value=source.get("dataset_key", ""),
                        field_type="hidden",
                    ),
                    _field(
                        "record_id",
                        "Source record",
                        value=source.get("record_id", ""),
                        field_type="hidden",
                    ),
                    _field(
                        "expected_version",
                        "Expected source version",
                        value=source.get("version", "") or "",
                        field_type="hidden",
                    ),
                    _field("payload", "New record (JSON)", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="change.request",
                label="Request source correction",
                path="/ui/actions/change.request",
                permission="correction.request.submit",
                destination="Configured steward queue",
                description="Ask the responsible steward to correct the source record.",
                fields=(
                    _field("target_type", "Target type", value="source_record", field_type="hidden"),
                    _field("target_id", "Target", value=record_id or "", field_type="hidden"),
                    _field("change_kind", "Change kind", value="factual", field_type="hidden"),
                    _field("title", "Summary", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                    _field("old_value", "Current value (JSON)", field_type="textarea"),
                    _field("proposed_value", "Proposed value (JSON)", field_type="textarea"),
                ),
            )
        )

    if screen == "permit":
        application = payload.get("application") or {}
        evaluation = payload.get("evaluation") or {}
        decision = payload.get("current_decision") or {}
        application_version = application.get("application_version") or 0
        for field_row in payload.get("extracted_fields") or []:
            if field_row.get("state") != "proposed":
                continue
            actions.append(
                action(
                    session,
                    actor,
                    action_id="extraction.decide",
                    label=f"Accept or correct extracted {field_row.get('field', 'value')}",
                    path="/ui/actions/extraction.decide",
                    permission="application.revision.submit",
                    domain_id="permits",
                    record_ids=(record_id or "",),
                    destination="Extraction proposal",
                    description=(
                        "Accept the proposed value, or correct it with a "
                        "replacement value and a reason."
                    ),
                    fields=(
                        _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                        _field(
                            "observation_id",
                            "Observation",
                            value=str(field_row.get("observation_id", "")),
                            field_type="hidden",
                        ),
                        _field(
                            "decision",
                            "Decision",
                            field_type="select",
                            options=("accept", "correct"),
                            required=True,
                        ),
                        _field("corrected_value", "Corrected value"),
                        _field("reason", "Reason (required when correcting)", field_type="textarea"),
                    ),
                )
            )
        match_view = payload.get("property") or {}
        if match_view:
            match_version = match_view.get("version")
            actions.append(
                action(
                    session,
                    actor,
                    action_id="parcel.confirm",
                    label="Confirm parcel",
                    path="/ui/actions/parcel.confirm",
                    permission="parcel.confirm",
                    domain_id="permits",
                    record_ids=(record_id or "",),
                    destination="Parcel link (identity)",
                    description=(
                        "Confirm that the approved parcel is the right property. A decision "
                        "needs this confirmation."
                    ),
                    expected_version=match_version,
                    state_allowed=bool(match_view.get("approved")) and not match_view.get("confirmed"),
                    state_reason=(
                        "the parcel is already confirmed"
                        if match_view.get("confirmed")
                        else "the Data Steward must approve the parcel link first"
                    ),
                    fields=(
                        _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                        _field("expected_version", "Expected version", value=str(match_version), field_type="hidden"),
                        _field("reason", "Note (optional)", field_type="textarea"),
                    ),
                )
            )
            candidate_options = tuple(
                str(item.get("address_id"))
                for item in match_view.get("candidates") or []
                if item.get("address_id")
            )
            actions.append(
                action(
                    session,
                    actor,
                    action_id="parcel.candidate.choose",
                    label="Choose another candidate",
                    path="/ui/actions/parcel.candidate.choose",
                    permission="parcel.match.propose",
                    domain_id="permits",
                    record_ids=(record_id or "",),
                    destination="Parcel link (identity)",
                    description=(
                        "Propose another address of the locator. The Data Steward approves "
                        "the new parcel link again."
                    ),
                    expected_version=match_version,
                    state_allowed=bool(candidate_options),
                    state_reason="the locator returned no other candidate",
                    fields=(
                        _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                        _field("expected_version", "Expected version", value=str(match_version), field_type="hidden"),
                        _field(
                            "address_id",
                            "Candidate address id",
                            field_type="select",
                            options=candidate_options,
                            required=True,
                        ),
                        _field("reason", "Reason", field_type="textarea", required=True),
                    ),
                )
            )
            actions.append(
                action(
                    session,
                    actor,
                    action_id="parcel.find",
                    label="Find parcel by number",
                    path="/ui/actions/parcel.find",
                    permission="parcel.match.propose",
                    domain_id="permits",
                    record_ids=(record_id or "",),
                    destination="Parcel link (identity)",
                    description=(
                        "Query the parcel layer by PARCELID and propose that parcel. The "
                        "Data Steward approves the new parcel link."
                    ),
                    expected_version=match_version,
                    fields=(
                        _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                        _field("expected_version", "Expected version", value=str(match_version), field_type="hidden"),
                        _field("parcel_number", "Parcel number (PARCELID)", required=True),
                        _field("reason", "Reason", field_type="textarea", required=True),
                    ),
                )
            )
            actions.append(
                action(
                    session,
                    actor,
                    action_id="change.request",
                    label="Flag address correction to GIS",
                    path="/ui/actions/change.request",
                    permission="correction.request.submit",
                    destination="GIS parcel register (steward queue)",
                    description=(
                        "Ask the responsible steward to correct the address in the GIS. "
                        "Nothing is written to the source from here."
                    ),
                    fields=(
                        _field("target_type", "Target type", value="application", field_type="hidden"),
                        _field("target_id", "Target", value=record_id or "", field_type="hidden"),
                        _field("change_kind", "Change kind", value="factual", field_type="hidden"),
                        _field(
                            "title",
                            "Summary",
                            value="Address correction for GIS",
                            required=True,
                        ),
                        _field("reason", "Reason", field_type="textarea", required=True),
                        _field(
                            "old_value",
                            "Current value (JSON)",
                            value=json.dumps({"address": match_view.get("matched_address") or match_view.get("submitted_text")}),
                            field_type="textarea",
                        ),
                        _field("proposed_value", "Proposed value (JSON)", field_type="textarea"),
                    ),
                )
            )
            for item in actions[-4:]:
                item["group"] = "property"
            actions[-1]["dom_id"] = "address-correction"
        actions.append(
            action(
                session,
                actor,
                action_id="permit.evaluate",
                label="Run application checks",
                path="/ui/actions/permit.evaluate",
                permission="application.evaluate",
                domain_id="permits",
                record_ids=(record_id or "",),
                destination="Permitting validation",
                description="Evaluate the current revision against the selected rule versions.",
                expected_version=application_version,
                fields=(
                    _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="permit.decide",
                label="Record review decision",
                path="/ui/actions/permit.decide",
                permission="permit.decide",
                domain_id="permits",
                record_ids=(record_id or "",),
                destination="Permitting decision record",
                description=(
                    "Record an authorized decision with its reason and the versions "
                    "it was made against."
                ),
                expected_version=application_version,
                fields=(
                    _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                    _field(
                        "expected_application_version",
                        "Expected application version",
                        value=str(application_version),
                        field_type="hidden",
                    ),
                    _field(
                        "expected_evaluation_version",
                        "Expected evaluation version",
                        value=str(evaluation.get("version", "")),
                        field_type="hidden",
                    ),
                    _field(
                        "outcome",
                        "Outcome",
                        field_type="select",
                        options=("approved", "denied", "modified", "information_requested"),
                        required=True,
                    ),
                    _field(
                        "reason_code",
                        "Denial reason code (required for a denial)",
                        field_type="select",
                        options=("",) + denial_codes,
                    ),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="permit.reconfirm",
                label="Reconfirm the decision",
                path="/ui/actions/permit.reconfirm",
                permission="permit.decide",
                domain_id="permits",
                record_ids=(record_id or "",),
                destination="Permitting decision record",
                description=(
                    "Confirm the decision again against the current versions after a "
                    "dependency changed."
                ),
                expected_version=application_version,
                state_allowed=bool(decision),
                state_reason="there is no decision to reconfirm yet",
                fields=(
                    _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                    _field(
                        "expected_application_version",
                        "Expected application version",
                        value=str(application_version),
                        field_type="hidden",
                    ),
                    _field(
                        "expected_evaluation_version",
                        "Expected evaluation version",
                        value=str(evaluation.get("version", "")),
                        field_type="hidden",
                    ),
                    _field(
                        "outcome",
                        "Outcome",
                        field_type="select",
                        options=("approved", "denied", "modified", "information_requested"),
                        required=True,
                    ),
                    _field(
                        "reason_code",
                        "Denial reason code (required for a denial)",
                        field_type="select",
                        options=("",) + denial_codes,
                    ),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="permit.issue",
                label="Issue permit",
                path="/ui/actions/permit.issue",
                permission="permit.issue",
                domain_id="permits",
                record_ids=(record_id or "",),
                destination="Permitting issued permit",
                description=(
                    "Issue the simulated permit from the current approved decision. The "
                    "command key makes the action idempotent."
                ),
                expected_version=application_version,
                state_allowed=bool(decision),
                state_reason="a current approved decision is required before issuance",
                fields=(
                    _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                    _field(
                        "decision_id",
                        "Decision",
                        value=decision.get("decision_id", ""),
                        field_type="hidden",
                    ),
                    _field(
                        "expected_application_version",
                        "Expected application version",
                        value=str(application_version),
                        field_type="hidden",
                    ),
                    _field(
                        "expected_decision_version",
                        "Expected decision version",
                        value=str(decision.get("version", "")),
                        field_type="hidden",
                    ),
                    _field(
                        "command_key",
                        "Issuance command key",
                        value=f"issue-{record_id or 'application'}",
                        required=True,
                    ),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="permit.revise",
                label="Correct the application record",
                path="/ui/actions/permit.revise",
                permission="application.revision.submit",
                domain_id="permits",
                record_ids=tuple(
                    item
                    for item in (
                        record_id,
                        str((payload.get("application") or {}).get("source_application_number", "")),
                    )
                    if item
                ),
                destination="Permitting application revision",
                description=(
                    "Create a new submitted revision. The earlier revision keeps its "
                    "content."
                ),
                expected_version=application_version,
                fields=(
                    _field("application_id", "Application", value=record_id or "", field_type="hidden"),
                    _field(
                        "expected_version",
                        "Expected application version",
                        value=str(application_version),
                        field_type="hidden",
                    ),
                    _field("facts", "Changed facts (JSON)", field_type="textarea", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="change.request",
                label="Request source correction",
                path="/ui/actions/change.request",
                permission="correction.request.submit",
                destination="Configured steward queue",
                description=(
                    "Ask the responsible steward to correct a source fact of this case."
                ),
                fields=(
                    _field("target_type", "Target type", value="application", field_type="hidden"),
                    _field("target_id", "Target", value=record_id or "", field_type="hidden"),
                    _field("change_kind", "Change kind", value="factual", field_type="hidden"),
                    _field("title", "Summary", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                    _field("old_value", "Current value (JSON)", field_type="textarea"),
                    _field("proposed_value", "Proposed value (JSON)", field_type="textarea"),
                ),
            )
        )

    if screen == "steward":
        for proposal in payload.get("parcel_proposals") or []:
            for label, decision_value in (
                ("Approve parcel link", "approve"),
                ("Reject parcel link", "reject"),
            ):
                actions.append(
                    action(
                        session,
                        actor,
                        action_id="parcel.link.decide",
                        label=f"{label} for {proposal['number']}",
                        path="/ui/actions/parcel.link.decide",
                        permission="registry.crosswalk.decide",
                        domain_id="parcels",
                        destination="Parcel link (identity)",
                        description=(
                            "The Data Steward approves the identity link between the "
                            "application and the parcel, with the locator evidence shown."
                        ),
                        expected_version=proposal["version"],
                        state_allowed=decision_value == "reject" or proposal["can_approve"],
                        state_reason="this proposal names no parcel; reject it or choose another candidate",
                        fields=(
                            _field("application_id", "Application", value=proposal["application_id"], field_type="hidden"),
                            _field("decision", "Decision", value=decision_value, field_type="hidden"),
                            _field("expected_version", "Expected version", value=str(proposal["version"]), field_type="hidden"),
                            _field("reason", "Reason", field_type="textarea", required=True),
                        ),
                    )
                )
                actions[-1]["application_id"] = proposal["application_id"]
        actions.append(
            action(
                session,
                actor,
                action_id="registry.propose",
                label="Propose candidate links",
                path="/ui/actions/registry.propose",
                permission="registry.crosswalk.propose",
                domain_id="applicants",
                destination="Registry candidate comparison",
                description=(
                    "Compare a source record with the canonical parties. The proposal "
                    "is evidence, never a decision."
                ),
                fields=(
                    _field("source_system_id", "Source system", value="permitting", required=True),
                    _field("dataset_key", "Dataset", value="applicant_profiles", required=True),
                    _field("source_record_id", "Source record", required=True),
                    _field("notes", "Note", field_type="textarea"),
                ),
            )
        )
        for label, decision_value in (
            ("Confirm link", "approve"),
            ("Reject link", "reject"),
            ("Record no match", "no_match"),
        ):
            actions.append(
                action(
                    session,
                    actor,
                    action_id="registry.decide",
                    label=label,
                    path="/ui/actions/registry.decide",
                    permission="registry.crosswalk.decide",
                    domain_id="applicants",
                    destination="Registry crosswalk",
                    description=(
                        "Record the steward decision with its reason and the expected "
                        "version of the link."
                    ),
                    fields=(
                        _field(
                            "source_system_id",
                            "Source system",
                            value="permitting",
                            required=True,
                        ),
                        _field(
                            "dataset_key",
                            "Dataset",
                            value="applicant_profiles",
                            required=True,
                        ),
                        _field("source_record_id", "Source record", required=True),
                        _field("decision", "Decision", value=decision_value, field_type="hidden"),
                        _field(
                            "entity_id",
                            "Canonical entity (leave it empty to record no match)",
                        ),
                        _field("expected_version", "Expected link version", field_type="number"),
                        _field("reason", "Reason", field_type="textarea", required=True),
                    ),
                )
            )
        actions.append(
            action(
                session,
                actor,
                action_id="change.transition",
                label="Move change case",
                path="/ui/actions/change.transition",
                permission="change.case.transition",
                destination="Configured steward queue",
                description=(
                    "Move a change case to the next permitted state. The server decides "
                    "which transitions are allowed."
                ),
                fields=(
                    _field("change_case_id", "Change case", required=True),
                    _field(
                        "to_status",
                        "New state",
                        field_type="select",
                        options=(
                            "in_review",
                            "awaiting_approval",
                            "approved",
                            "sent_to_source",
                            "rejected",
                            "closed",
                        ),
                        required=True,
                    ),
                    _field("expected_version", "Expected case version", field_type="number"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="change.request",
                label="Request source correction",
                path="/ui/actions/change.request",
                permission="correction.request.submit",
                destination="Configured steward queue",
                description="Ask the responsible steward to correct a source fact.",
                fields=(
                    _field("target_type", "Target type", value="source_record", field_type="hidden"),
                    _field("target_id", "Target", required=True),
                    _field("change_kind", "Change kind", value="factual", field_type="hidden"),
                    _field("title", "Summary", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                    _field("old_value", "Current value (JSON)", field_type="textarea"),
                    _field("proposed_value", "Proposed value (JSON)", field_type="textarea"),
                ),
            )
        )

    if screen == "rules":
        actions.append(
            action(
                session,
                actor,
                action_id="rule.draft",
                label="Draft rule version",
                path="/ui/actions/rule.draft",
                permission="rule.version.draft",
                domain_id="building_rules",
                destination="Approved rules register",
                description="Create a new draft version of a rule.",
                fields=(
                    _field("rule_id", "Rule", required=True),
                    _field("permit_type_key", "Permit type", value="com_ti", required=True),
                    _field("title", "Title", required=True),
                    _field("citation", "Citation", required=True),
                    _field("field_path", "Field path"),
                    _field("operator", "Operator", field_type="select", options=("", "min", "max", "equals")),
                    _field("limit_value", "Limit"),
                    _field("on_violate", "On violation"),
                    _field("message", "Message"),
                    _field("effective_from", "Effective from", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        for label, action_id, permission in (
            ("Submit rule version for review", "rule.submit", "rule.version.draft"),
            ("Approve rule version", "rule.approve", "rule.version.approve"),
            ("Publish rule version", "rule.publish", "rule.version.publish"),
            ("Retire rule version", "rule.retire", "rule.version.publish"),
        ):
            actions.append(
                action(
                    session,
                    actor,
                    action_id=action_id,
                    label=label,
                    path=f"/ui/actions/{action_id}",
                    permission=permission,
                    domain_id="building_rules",
                    destination="Approved rules register",
                    description=f"{label}. The author may never approve their own version.",
                    fields=(
                        _field("rule_version_id", "Rule version", required=True),
                        _field("expected_version", "Expected version", field_type="number", required=True),
                        _field("reason", "Reason", field_type="textarea", required=True),
                        _field("precedence", "Precedence"),
                    ),
                )
            )
        actions.append(
            action(
                session,
                actor,
                action_id="fee.draft",
                label="Draft fee schedule version",
                path="/ui/actions/fee.draft",
                permission="rule.version.draft",
                domain_id="finance",
                destination="Approved fee register",
                description="Create a new draft version of a fee schedule.",
                fields=(
                    _field("fee_schedule_id", "Fee schedule", required=True),
                    _field("version_label", "Version label", required=True),
                    _field("effective_from", "Effective from", required=True),
                    _field("currency", "Currency", value="USD", required=True),
                    _field("definition", "Definition (JSON)", field_type="textarea", required=True),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        for label, action_id, permission in (
            ("Submit fee schedule for review", "fee.submit", "rule.version.draft"),
            ("Approve fee schedule", "fee.approve", "rule.version.approve"),
            ("Publish fee schedule", "fee.publish", "rule.version.publish"),
            ("Retire fee schedule", "fee.retire", "rule.version.publish"),
        ):
            actions.append(
                action(
                    session,
                    actor,
                    action_id=action_id,
                    label=label,
                    path=f"/ui/actions/{action_id}",
                    permission=permission,
                    domain_id="finance",
                    destination="Approved fee register",
                    description=f"{label}.",
                    fields=(
                        _field("fee_schedule_version_id", "Fee schedule version", required=True),
                        _field("expected_version", "Expected version", field_type="number", required=True),
                        _field("reason", "Reason", field_type="textarea", required=True),
                        _field("precedence", "Precedence"),
                    ),
                )
            )

    if screen == "reconciliation":
        actions.append(
            action(
                session,
                actor,
                action_id="finance.assess",
                label="Assess application",
                path="/ui/actions/finance.assess",
                permission="finance.assessment.create",
                domain_id="finance",
                destination="Finance assessment",
                description="Assess the declared valuation of an application.",
                fields=(
                    _field("application_id", "Application", required=True),
                    _field("valuation", "Declared valuation"),
                    _field("expected_application_version", "Expected application version", field_type="number"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="finance.reassess",
                label="Reassess application",
                path="/ui/actions/finance.reassess",
                permission="finance.assessment.create",
                domain_id="finance",
                destination="Finance assessment",
                description=(
                    "Assess again at a new valuation. The paid funds are carried "
                    "forward once, in the same transaction."
                ),
                fields=(
                    _field("application_id", "Application", required=True),
                    _field("valuation", "Declared valuation"),
                    _field("expected_application_version", "Expected application version", field_type="number"),
                    _field("carry_forward", "Carry the paid funds forward", value="true", field_type="hidden"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="finance.import",
                label="Import ERP payment",
                path="/ui/actions/finance.import",
                permission="finance.payment.import",
                domain_id="finance",
                destination="Simulated ERP/Finance ledger",
                description="Import one simulated receipt event.",
                fields=(
                    _field("source_transaction_id", "Transaction", required=True),
                    _field("source_event_id", "Event", required=True),
                    _field("source_event_version", "Event version"),
                    _field("event_type", "Event type", value="received", field_type="select", options=("received", "settled", "reversed")),
                    _field("amount", "Amount", required=True),
                    _field("currency", "Currency", value="USD", required=True),
                    _field("payer_account_id", "Payer account"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="finance.allocate",
                label="Confirm allocation",
                path="/ui/actions/finance.allocate",
                permission="finance.allocation.confirm",
                domain_id="finance",
                destination="Finance allocation",
                description=(
                    "Confirm an allocation of settled funds to an assessment version. "
                    "The idempotency key keeps a repeated command harmless."
                ),
                fields=(
                    _field("payment_id", "Receipt", required=True),
                    _field("assessment_id", "Assessment version", required=True),
                    _field("amount", "Amount", required=True),
                    _field("currency", "Currency", value="USD", required=True),
                    _field("idempotency_key", "Idempotency key", required=True),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="finance.reconcile",
                label="Reconcile assessment",
                path="/ui/actions/finance.reconcile",
                permission="finance.allocation.confirm",
                domain_id="finance",
                destination="Finance reconciliation",
                description="Reconcile an assessment version against its receipts.",
                fields=(
                    _field("assessment_id", "Assessment version", required=True),
                    _field("payment_ids", "Receipts (comma separated)"),
                ),
            )
        )

    if screen == "governance":
        actions.append(
            action(
                session,
                actor,
                action_id="intake.simulate",
                label="Simulate incoming permits",
                path="/ui/actions/intake.simulate",
                permission="governance.dataset.register",
                destination="ACME ePermit Portal (simulated) intake",
                description=(
                    "Post a deterministic batch of fictional incoming permits "
                    "from the outside portal and run the agent triage pipeline "
                    "for each one."
                ),
                fields=(
                    _field(
                        "scenario",
                        "Scenario",
                        field_type="select",
                        options=(
                            "fence-conforming-rear",
                            "fence-front-too-tall",
                            "fence-missing-site-plan",
                            "deck-high",
                            "mixed",
                        ),
                        required=True,
                    ),
                    _field("count", "Count (optional)", field_type="number"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.register",
                label="Register source dataset",
                path="/ui/actions/governance.register",
                permission="governance.dataset.register",
                destination="Governance registration",
                description=(
                    "Register a dataset with its owner, steward queue, custodian, "
                    "authority policy and correction route."
                ),
                fields=(
                    _field("source_system_id", "Source system", required=True),
                    _field("dataset_key", "Dataset", required=True),
                    _field("label", "Label", required=True),
                    _field("domain_id", "Domain"),
                    _field("accountable_owner_actor_id", "Accountable owner"),
                    _field("steward_queue_id", "Steward queue"),
                    _field("system_custodian_actor_id", "System custodian"),
                    _field("authority_policy_id", "Authority policy"),
                    _field("correction_route", "Correction route"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.publish_dataset",
                label="Publish source dataset",
                path="/ui/actions/governance.publish_dataset",
                permission="governance.dataset.register",
                destination="Governance registration",
                description=(
                    "Publish a registered dataset once its registration is complete."
                ),
                fields=(_field("dataset_key", "Dataset", required=True),),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.reassign",
                label="Reassign steward",
                path="/ui/actions/governance.reassign",
                permission="governance.assignment.manage",
                destination="Effective-dated assignment",
                description=(
                    "Move a responsibility to another actor. The earlier assignment "
                    "keeps its history."
                ),
                fields=(
                    _field("domain_id", "Domain", required=True),
                    _field(
                        "responsibility",
                        "Responsibility",
                        value="steward",
                        field_type="select",
                        options=("owner", "steward", "delegate", "custodian", "escalation"),
                    ),
                    _field("new_actor_id", "New actor", required=True),
                    _field("expected_version", "Expected version", field_type="number"),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.authority_preview",
                label="Preview authority change",
                path="/ui/actions/governance.authority_preview",
                permission="governance.authority_policy.manage",
                destination="Authority policy preview",
                description="Show the datasets and cases an authority change would affect.",
                fields=(
                    _field("policy_id", "Policy", required=True),
                    _field("field_group", "Field group", required=True),
                    _field("domain_id", "Domain"),
                    _field("authoritative_source_system_id", "Authoritative source"),
                    _field("authoritative_dataset_key", "Authoritative dataset"),
                    _field("change_destination", "Change destination", required=True),
                    _field("user_action", "User action", required=True),
                    _field("decision_relevant", "Decision relevant", value="false", field_type="hidden"),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.authority_publish",
                label="Publish authority change",
                path="/ui/actions/governance.authority_publish",
                permission="governance.authority_policy.publish",
                destination="Authority policy",
                description="Publish the authority policy version after its impact preview.",
                fields=(
                    _field("policy_id", "Policy", required=True),
                    _field("approver_actor_id", "Approver", required=True),
                    _field("expected_version", "Expected version", field_type="number", required=True),
                    _field("field_group", "Field group"),
                    _field("domain_id", "Domain"),
                    _field("change_destination", "Change destination"),
                    _field("user_action", "User action"),
                    _field("decision_relevant", "Decision relevant", value="false", field_type="hidden"),
                    _field("reason", "Reason", field_type="textarea", required=True),
                ),
            )
        )
        actions.append(
            action(
                session,
                actor,
                action_id="governance.escalate",
                label="Escalate dispute",
                path="/ui/actions/governance.escalate",
                permission="correction.request.submit",
                destination="Governance issue queue",
                description="Route a disputed decision to the accountable owner of its domain.",
                fields=(
                    _field("domain_id", "Domain", required=True),
                    _field("subject_type", "Subject type", required=True),
                    _field("subject_id", "Subject", required=True),
                    _field("issue_type", "Issue type", required=True),
                    _field("description", "Description", field_type="textarea", required=True),
                    _field("reason", "Reason", field_type="textarea"),
                ),
            )
        )
    return actions


#: The source dataset that owns each credential type.
CREDENTIAL_DATASET: dict[str, tuple[str, str]] = {
    "business_license": ("erp_finance", "business_licensing_register"),
    "contractor_registration": ("permitting", "contractor_register"),
}


def _credential_source_record(
    session: Session, credentials: list[registry.Credential]
) -> dict[str, Any] | None:
    """Return the source record behind the credentials of one party."""
    for credential in credentials:
        dataset = CREDENTIAL_DATASET.get(credential.credential_type)
        if dataset is None:
            continue
        source_system_id, dataset_key = dataset
        snapshot = session.execute(
            select(source.SourceSnapshot)
            .where(
                source.SourceSnapshot.source_system_id == source_system_id,
                source.SourceSnapshot.source_dataset_id == dataset_key,
                source.SourceSnapshot.source_record_id == credential.source_record_id,
                source.SourceSnapshot.record_status == "accepted",
            )
            .order_by(source.SourceSnapshot.ingested_at.desc())
        ).scalars().first()
        return {
            "source_system_id": source_system_id,
            "dataset_key": dataset_key,
            "record_id": credential.source_record_id or "",
            "version": (snapshot.source_record_version if snapshot else None) or "",
            "destination": (
                "ERP business licensing register"
                if credential.credential_type == "business_license"
                else "Permitting contractor register"
            ),
        }
    return None


def _applicant_source_record(
    session: Session, party_id: str | None
) -> dict[str, Any] | None:
    """Return the Permitting source record of one applicant profile."""
    if not party_id:
        return None
    row = session.execute(
        select(source.SourceSnapshot)
        .where(
            source.SourceSnapshot.source_system_id == "permitting",
            source.SourceSnapshot.source_dataset_id == "applicant_profiles",
            source.SourceSnapshot.record_status == "accepted",
        )
        .order_by(source.SourceSnapshot.ingested_at.desc())
    ).scalars().all()
    for snapshot in row:
        payload = dict(snapshot.raw_payload or {})
        if payload.get("party_ref") == party_id:
            return {
                "record_id": snapshot.source_record_id,
                "version": snapshot.source_record_version or "",
                "source_system_id": snapshot.source_system_id,
                "dataset_key": snapshot.source_dataset_id,
            }
    return None



# -------------------------------------------------------------- permit icons


def permit_type_icons(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return every permit type with their current and candidate icons.

    Seed icons are loaded by the fixture reset, so rendering writes nothing.
    Generation is never
    automatic: candidates appear only after an administrator's governed
    generate action, and stay pending until a save.
    """
    from acme_city.permits import icons as icon_service

    per_type_counts, total_today = icon_service.icon_attempt_counts(session)
    can_generate = allows(session, actor, icon_service.ICON_PERMISSION)
    types: list[dict[str, Any]] = []
    rows = session.execute(
        select(permit.PermitType).order_by(permit.PermitType.label)
    ).scalars().all()
    for row in rows:
        icons = session.execute(
            select(permit.PermitTypeIcon)
            .where(permit.PermitTypeIcon.permit_type_id == row.id)
            .order_by(permit.PermitTypeIcon.created_at, permit.PermitTypeIcon.id)
        ).scalars().all()
        icon_entries = [
            {
                "icon_id": icon.id,
                "media_type": icon.media_type,
                "prompt": icon.prompt,
                "source": icon.source,
                "is_current": bool(icon.is_current),
                "created_by": icon.created_by,
                "created_at": _iso(icon.created_at),
                "url": f"/permit-type-icons/{icon.id}",
            }
            for icon in icons
        ]
        current = next((entry for entry in icon_entries if entry["is_current"]), None)
        if current is None and row.icon_id:
            current = next(
                (entry for entry in icon_entries if entry["icon_id"] == row.icon_id), None
            )
        types.append(
            {
                "permit_type_id": row.id,
                "permit_type_key": row.key,
                "key": row.key,
                "label": row.label,
                "version": row.version,
                "current_icon": current,
                "icons": icon_entries,
            }
        )
    return {
        "types": types,
        "can_generate": can_generate,
        "attempts_today": total_today,
        "per_type_counts": per_type_counts,
        "per_type_cap": icon_service.PER_TYPE_DAILY_CAP,
        "global_cap": None,
    }


def icon_for_permit_type(
    session: Session, permit_type_row: permit.PermitType | None
) -> dict[str, Any] | None:
    """Return the current icon of one permit type row, or ``None``."""
    if permit_type_row is None:
        return None
    icon = None
    if permit_type_row.icon_id:
        icon = session.execute(
            select(permit.PermitTypeIcon).where(
                permit.PermitTypeIcon.id == permit_type_row.icon_id
            )
        ).scalar_one_or_none()
    if icon is None:
        icon = session.execute(
            select(permit.PermitTypeIcon).where(
                permit.PermitTypeIcon.permit_type_id == permit_type_row.id,
                permit.PermitTypeIcon.is_current.is_(True),
            )
        ).scalar_one_or_none()
    if icon is None:
        return None
    return {
        "icon_id": icon.id,
        "media_type": icon.media_type,
        "source": icon.source,
        "url": f"/permit-type-icons/{icon.id}",
    }


# ------------------------------------------------------------------ work queue


def _application_blockers(
    service: PermitService, application: permit.Application
) -> list[dict[str, str]]:
    """Return the conditions that hold a dependent action of an application."""
    blockers: list[dict[str, str]] = []
    evaluation = service.current_evaluation(application.id)
    if evaluation is not None:
        for blocker in service.evaluation_view(evaluation).blockers:
            blockers.append({"code": blocker.code, "detail": blocker.detail})
    for blocker in service.site_blockers(application):
        blockers.append({"code": blocker.code, "detail": blocker.detail})
    inputs = dict(evaluation.source_versions or {}).get("inputs", {}) if evaluation else {}
    for blocker in service.credential_blockers(application, inputs, utc_now()):
        blockers.append({"code": blocker.code, "detail": blocker.detail})
    for blocker in service.identity_link_blockers(application):
        blockers.append({"code": blocker.code, "detail": blocker.detail})
    for blocker in service.finance_link_blockers(application):
        blockers.append({"code": blocker.code, "detail": blocker.detail})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker["code"], blocker["detail"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)
    return unique


def _application_step(
    application: permit.Application, has_assessment: bool
) -> tuple[int, str]:
    """Return the 0..5 mini-progress position of an application and its tone.

    Derived only from the recorded application status (and whether a fee
    was assessed): 0 submitted, 1 validated, 2 decision, 3 fee assessed,
    4 paid (not derivable per row, so assessed stays 3), 5 issued.
    """
    status = application.status
    if status == "issued":
        return 5, "done"
    if status in ("approved", "denied"):
        return (3, "done") if has_assessment else (2, "done")
    if status in ("under_review", "ready_for_review"):
        return 2, "current"
    if status == "needs_information":
        return 1, "blocked"
    return 0, "current"


def _next_action(
    session: Session,
    actor: ActorContext,
    service: PermitService,
    application: permit.Application,
    blockers: list[dict[str, str]],
) -> str:
    """Return the plain next action of one application."""
    evaluation = service.current_evaluation(application.id)
    decision = service.current_decision(application.id)
    permit_row = session.execute(
        select(permit.Permit).where(permit.Permit.application_id == application.id)
    ).scalars().first()
    if permit_row is not None:
        return "Issued - read the permit artifact"
    if application.status == "returned":
        return "Returned to the applicant - the applicant starts a new application"
    if application.status == "revisions_requested":
        return "Waiting for the applicant's answer"
    if application.status == "needs_information":
        if blockers:
            return f"Resolve {blockers[0]['code'].replace('_', ' ')}"
        if allows(session, actor, "permit.case.advance", "permits"):
            return "Advance the case to review"
        return "Waiting for the Data Steward"
    if blockers:
        return f"Resolve {blockers[0]['code'].replace('_', ' ')}"
    if evaluation is None:
        if application.status == "submitted" and application.scenario_id is None:
            return "Waiting for the intake agent"
        if allows(session, actor, "application.evaluate", "permits"):
            return "Run application checks"
        return "Waiting for validation"
    if decision is None:
        if allows(session, actor, "permit.decide", "permits"):
            return "Record the review decision"
        return "Waiting for the reviewer decision"
    if decision.outcome == "approved":
        if allows(session, actor, "permit.issue", "permits"):
            return "Confirm the finance position and issue the permit"
        return "Waiting for issuance"
    return "Read the recorded decision"


def work_queue(
    session: Session,
    actor: ActorContext,
    *,
    view: str = "my",
    department: str | None = None,
    object_type: str | None = None,
    state: str | None = None,
    focus: str = "all",
) -> dict[str, Any]:
    """Return the work queue of the acting persona.

    The queue shows the applications, the change cases, the review tasks and
    the open issues the persona may act on, with the blocker, the age, the
    configured response target and the plain next action of each item.
    """
    service = PermitService(session)
    now = utc_now()
    items: list[dict[str, Any]] = []
    visible = visible_applications(session, actor)
    owner_labels = {
        row.actor_id: row.label
        for row in session.execute(
            select(governance.Actor).where(
                governance.Actor.actor_id.in_(
                    sorted({a.owner_actor_id for a in visible if a.owner_actor_id})
                )
            )
        ).scalars().all()
    }

    for application in visible:
        # An archived case is closed: it is not an active queue entry.
        if application.status == "archived":
            continue
        blockers = _application_blockers(service, application)
        assessment = session.execute(
            select(finance.Assessment)
            .where(
                finance.Assessment.application_id == application.id,
                finance.Assessment.status == "current",
            )
            .order_by(finance.Assessment.version.desc())
        ).scalars().first()
        age = _age_days(application.initial_submitted_at, now)
        type_row = service.permit_type(application)
        step, step_state = _application_step(application, assessment is not None)
        items.append(
            {
                "kind": "application",
                "object_type": "Application",
                "id": application.id,
                "title": application.source_application_number,
                "subtitle": type_row.label,
                "permit_type_id": type_row.id,
                "permit_type_key": type_row.key,
                "icon": icon_for_permit_type(session, type_row),
                "step": step,
                "step_state": step_state,
                "state": application.status,
                "state_label": (
                    "Awaiting intake agent"
                    if application.status == "submitted" and application.scenario_id is None
                    else application.status
                ),
                "department": "permits",
                "assignee": application.applicant_party_id,
                "blocker": blockers[0]["detail"] if blockers else "",
                "blocker_code": blockers[0]["code"] if blockers else "",
                "blockers": blockers,
                "age_days": age,
                "target": "first review within 1 business day",
                "target_note": "configured demonstration target, not a service promise",
                "next_action": _next_action(session, actor, service, application, blockers),
                "href": f"/permits/{application.id}",
                "version": application.version,
                "scenario_id": application.scenario_id,
                "financial_state": (
                    f"assessed {assessment.assessed_total_cents / 100:.2f} "
                    f"{assessment.currency}"
                    if assessment is not None
                    else "not assessed"
                ),
            }
        )
        reviewer_views.decorate_application_item(
            session,
            items[-1],
            application,
            owner_labels.get(application.owner_actor_id or "", ""),
            int(type_row.service_target_days or 0),
            now,
        )

    change_service = ChangeService(session)
    for case in session.execute(
        select(change.ChangeCase).order_by(change.ChangeCase.created_at)
    ).scalars().all():
        if not allows(
            session,
            actor,
            "change.case.transition",
            None,
            (case.target_id,),
        ) and case.assignee_actor_id != actor.actor_id:
            continue
        view_model = change_service.case_view(case)
        items.append(
            {
                "kind": "change_case",
                "object_type": "Change case",
                "id": case.id,
                "title": case.title,
                "subtitle": case.target_id,
                "state": case.status,
                "department": "stewardship",
                "assignee": case.assignee_actor_id,
                "blocker": case.destination or "",
                "blocker_code": "",
                "blockers": [],
                "age_days": _age_days(case.created_at, now),
                "target": "first review within 1 business day",
                "target_note": "configured demonstration target, not a service promise",
                "next_action": (
                    "Move the case to "
                    + (", ".join(permitted_targets(case.status, case.change_kind)) or "close")
                ),
                "href": "/steward",
                "version": case.version,
                "scenario_id": case.scenario_id,
                "allowed_transitions": list(view_model.allowed_transitions),
                "financial_state": "",
            }
        )

    for task in session.execute(
        select(change.ReviewTask).where(change.ReviewTask.status == "open")
    ).scalars().all():
        if task.assignee_actor_id != actor.actor_id and not allows(
            session, actor, "change.case.transition"
        ):
            continue
        items.append(
            {
                "kind": "review_task",
                "object_type": "Review task",
                "id": task.id,
                "title": task.task_type.replace("_", " ").capitalize(),
                "subtitle": task.target_id or "",
                "state": task.status,
                "department": "stewardship",
                "assignee": task.assignee_actor_id,
                "blocker": "",
                "blocker_code": "",
                "blockers": [],
                "age_days": _age_days(task.created_at, now),
                "target": "first review within 1 business day",
                "target_note": "configured demonstration target, not a service promise",
                "next_action": "Review the affected record",
                "href": "/steward",
                "version": 1,
                "scenario_id": task.scenario_id,
                "financial_state": "",
            }
        )

    for issue in session.execute(
        select(change.GovernanceIssue).where(change.GovernanceIssue.status == "open")
    ).scalars().all():
        if issue.assigned_actor_id != actor.actor_id and not allows(
            session, actor, "governance.assignment.manage"
        ):
            continue
        items.append(
            {
                "kind": "issue",
                "object_type": "Governance issue",
                "id": issue.id,
                "title": issue.issue_type.replace("_", " ").capitalize(),
                "subtitle": issue.subject_id,
                "state": issue.status,
                "department": "governance",
                "assignee": issue.assigned_actor_id,
                "blocker": issue.description,
                "blocker_code": issue.issue_type,
                "blockers": [],
                "age_days": _age_days(issue.created_at, now),
                "target": "first review within 1 business day",
                "target_note": "configured demonstration target, not a service promise",
                "next_action": "Route the issue to the accountable owner",
                "href": "/governance",
                "version": issue.version,
                "scenario_id": issue.scenario_id,
                "financial_state": "",
            }
        )

    for item in items:
        if "bucket" not in item:
            reviewer_views.decorate_other_item(item)

    if view == "mine":
        items = [item for item in items if item.get("owner_actor_id") == actor.actor_id]
    elif view == "my":
        items = [
            item
            for item in items
            if item["assignee"] == actor.actor_id
            or item["kind"] == "application"
            and allows(
                session,
                actor,
                {
                    "application": "application.evaluate",
                    "change_case": "change.case.transition",
                    "review_task": "change.case.transition",
                    "issue": "governance.assignment.manage",
                }[item["kind"]],
                item["department"],
                (item["id"],),
            )
        ]
    if department:
        items = [item for item in items if item["department"] == department]
    if object_type:
        items = [item for item in items if item["object_type"].lower() == object_type.lower()]
    if state:
        items = [item for item in items if item["state"] == state]

    focus = focus if focus in reviewer_views.QUEUE_VIEW_KEYS else "all"
    views = reviewer_views.queue_views(items, focus)
    if focus != "all":
        items = [item for item in items if item["bucket"] == focus]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["object_type"]] = counts.get(item["object_type"], 0) + 1
    return {
        "entries": items,
        "counts": counts,
        "views": views,
        "has_owner": any(item.get("owner_label") for item in items),
        "age_note": reviewer_views.scenario_clock_note(now),
        "filters": {
            "focus": focus,
            "view": view,
            "department": department or "",
            "object_type": object_type or "",
            "state": state or "",
        },
        "states": sorted({item["state"] for item in items}),
        "departments": sorted({item["department"] for item in items}),
        "object_types": sorted({item["object_type"] for item in items}),
    }


# ------------------------------------------------------------------ applicants


def _party_aliases(session: Session, party_id: str) -> list[dict[str, Any]]:
    """Return the recorded aliases of one party."""
    rows = session.execute(
        select(registry.PartyAlias).where(registry.PartyAlias.party_id == party_id)
    ).scalars().all()
    return [
        {
            "alias_id": row.id,
            "value": row.alias_value,
            "alias_type": row.alias_type,
            "source_snapshot_id": row.source_snapshot_id,
            "recorded_at": _iso(row.recorded_at),
        }
        for row in rows
    ]


def _party_contacts(session: Session, party_id: str) -> list[dict[str, Any]]:
    """Return the current contact register of one party."""
    rows = session.execute(
        select(registry.PartyContact).where(registry.PartyContact.party_id == party_id)
    ).scalars().all()
    return [
        {
            "contact_id": row.id,
            "contact_type": row.contact_type,
            "value": row.value,
            "verification_state": row.verification_state,
            "source_snapshot_id": row.source_snapshot_id,
            "valid_from": _iso(row.valid_from),
            "valid_to": _iso(row.valid_to),
            "version": row.version,
        }
        for row in rows
    ]


def _party_applications(session: Session, party_id: str) -> list[permit.Application]:
    """Return the applications one party appears on."""
    party_ids = session.execute(
        select(permit.ApplicationParty.party_id).where(
            permit.ApplicationParty.party_id == party_id
        )
    ).scalars().all()
    if not party_ids:
        return []
    return list(
        session.execute(
            select(permit.Application)
            .where(permit.Application.applicant_party_id.in_(party_ids))
            .order_by(permit.Application.source_application_number)
        ).scalars().all()
    )


def _applicant_party_ids(session: Session) -> set[str]:
    """Return the parties that appear in the applicant role."""
    return set(
        session.execute(
            select(permit.ApplicationParty.party_id).where(
                permit.ApplicationParty.party_role == "applicant"
            )
        ).scalars().all()
    )


def applicants(session: Session, actor: ActorContext, *, query: str = "") -> dict[str, Any]:
    """Return the shared applicant view of the canonical parties."""
    applicant_ids = _applicant_party_ids(session)
    rows: list[dict[str, Any]] = []
    needle = query.strip().lower()
    for party in visible_parties(session, actor):
        aliases = _party_aliases(session, party.id)
        if needle:
            haystack = " ".join(
                [party.display_name, party.legal_name or ""]
                + [alias["value"] for alias in aliases]
            ).lower()
            if needle not in haystack:
                continue
        applications = _party_applications(session, party.id)
        rows.append(
            {
                "party_id": party.id,
                "display_name": party.display_name,
                "legal_name": party.legal_name,
                "party_type": party.party_type,
                "status": party.status,
                "version": party.version,
                "aliases": aliases,
                "contacts": _party_contacts(session, party.id),
                "applications": [
                    {
                        "application_id": item.id,
                        "source_application_number": item.source_application_number,
                        "status": item.status,
                        "href": f"/permits/{item.id}",
                    }
                    for item in applications
                ],
                "is_applicant": party.id in applicant_ids,
                "href": f"/applicants/{party.id}",
            }
        )
    return {"parties": rows, "query": query, "count": len(rows)}


def party_detail(
    session: Session, actor: ActorContext, party_id: str
) -> dict[str, Any]:
    """Return the shared party view of one canonical identity.

    The current profile, the submitted declarations, the proposed
    corrections and the issued values are shown separately, and the sources,
    evidence and history of the record follow them.
    """
    party = session.execute(
        select(registry.Party).where(registry.Party.id == party_id)
    ).scalar_one_or_none()
    if party is None:
        return {}
    if party.id not in {row.id for row in visible_parties(session, actor)}:
        return {}
    registry_service = RegistryService(session)
    trusted = registry_service.trusted_view(party.id)
    applications = _party_applications(session, party.id)

    submitted: list[dict[str, Any]] = []
    issued: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for application in applications:
        revisions = session.execute(
            select(permit.ApplicationRevision)
            .where(permit.ApplicationRevision.application_id == application.id)
            .order_by(permit.ApplicationRevision.revision_number)
        ).scalars().all()
        for revision in revisions:
            submitted.append(
                {
                    "application_id": application.id,
                    "source_application_number": application.source_application_number,
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "submitted_at": _iso(revision.submitted_at),
                    "submitted_by_actor_id": revision.submitted_by_actor_id,
                    "facts": dict(revision.snapshot or {}),
                }
            )
        permits = session.execute(
            select(permit.Permit).where(permit.Permit.application_id == application.id)
        ).scalars().all()
        for issued_permit in permits:
            issued.append(
                {
                    "permit_id": issued_permit.id,
                    "permit_number": issued_permit.permit_number,
                    "issued_at": _iso(issued_permit.issued_at),
                    "status": issued_permit.status,
                    "artifact_hash": issued_permit.artifact_hash,
                    "application_id": application.id,
                }
            )
        documents = session.execute(
            select(permit.Document).where(permit.Document.application_id == application.id)
        ).scalars().all()
        for document in documents:
            evidence.append(
                {
                    "evidence_id": document.id,
                    "kind": "document",
                    "label": f"{document.document_type} v{document.version}",
                    "detail": document.content_hash,
                    "content_hash": document.content_hash,
                    "received_at": _iso(document.received_at),
                    "application_id": application.id,
                }
            )

    proposed = [
        {
            "change_case_id": case.id,
            "title": case.title,
            "status": case.status,
            "reason": case.reason,
            "old_value": dict(case.old_value or {}),
            "proposed_value": dict(case.proposed_value or {}),
            "destination": case.destination,
            "assignee_actor_id": case.assignee_actor_id,
            "requester_actor_id": case.requester_actor_id,
            "version": case.version,
        }
        for case in session.execute(
            select(change.ChangeCase)
            .where(
                change.ChangeCase.target_id == party.id,
                change.ChangeCase.status.notin_(("closed", "rejected")),
            )
            .order_by(change.ChangeCase.created_at)
        ).scalars().all()
    ]

    crosswalks = [
        crosswalk_view(row).model_dump(mode="json")
        for row in session.execute(
            select(registry.Crosswalk)
            .where(registry.Crosswalk.entity_id == party.id)
            .order_by(registry.Crosswalk.created_at)
        ).scalars().all()
    ]

    credentials = session.execute(
        select(registry.Credential).where(registry.Credential.holder_party_id == party.id)
    ).scalars().all()

    contacts = _party_contacts(session, party.id)
    aliases = _party_aliases(session, party.id)
    current = {
        "display_name": party.display_name,
        "legal_name": party.legal_name,
        "status": party.status,
        "version": party.version,
        "contacts": contacts,
        "aliases": aliases,
    }
    trusted_fields = trusted.fields if trusted is not None else []
    return {
        "party": {
            "party_id": party.id,
            "display_name": party.display_name,
            "legal_name": party.legal_name,
            "party_type": party.party_type,
            "status": party.status,
            "version": party.version,
        },
        "current": current,
        "submitted": submitted,
        "proposed": proposed,
        "issued": issued,
        "sources": crosswalks,
        "trusted_fields": [field.model_dump(mode="json") for field in trusted_fields],
        "trusted_disagreements": (
            [field.model_dump(mode="json") for field in trusted.disagreements]
            if trusted is not None
            else []
        ),
        "credentials": [
            {
                "credential_id": row.credential_id,
                "credential_type": row.credential_type,
                "issuing_authority_id": row.issuing_authority_id,
                "number": row.number,
                "status": row.status,
                "valid_from": _iso(row.valid_from),
                "valid_to": _iso(row.valid_to),
                "version": row.version,
            }
            for row in credentials
        ],
        "evidence": evidence,
        "history": history(session, actor, party.id),
        "responsibility": responsibility(
            session,
            domain_id="applicants",
            version=party.version,
            source_system_id="permitting",
            dataset_key="applicant_profiles",
            subject_ids=(party.id,),
        ),
    }


# --------------------------------------------------------------------- masters


def masters(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the properties, businesses and contractors of one master view."""
    parcels = session.execute(
        select(registry.Parcel).order_by(registry.Parcel.source_parcel_number)
    ).scalars().all()
    if actor.record_scope:
        # A record-scoped actor only sees the properties of the cases it may see.
        allowed_parcels = {
            site.parcel_id
            for application in visible_applications(session, actor)
            for site in [session.execute(
                select(permit.ApplicationSite).where(
                    permit.ApplicationSite.application_id == application.id
                )
            ).scalar_one_or_none()]
            if site is not None and site.parcel_id
        }
        parcels = [parcel for parcel in parcels if parcel.parcel_id in allowed_parcels]
    addresses = session.execute(
        select(registry.Address).order_by(registry.Address.address_id)
    ).scalars().all()
    parcel_addresses = session.execute(select(registry.ParcelAddress)).scalars().all()
    by_parcel: dict[str, list[registry.Address]] = {}
    for link in parcel_addresses:
        by_parcel.setdefault(link.parcel_id, []).append(
            next(
                (
                    address
                    for address in addresses
                    if address.address_id == link.address_id
                ),
                None,
            )
        )

    credential_rows = session.execute(select(registry.Credential)).scalars().all()
    parties = {row.id: row for row in visible_parties(session, actor)}
    businesses: list[dict[str, Any]] = []
    contractors: list[dict[str, Any]] = []
    for credential in credential_rows:
        party = parties.get(credential.holder_party_id)
        if party is None:
            continue
        entry = {
            "party_id": party.id,
            "display_name": party.display_name,
            "credential_id": credential.credential_id,
            "credential_type": credential.credential_type,
            "number": credential.number,
            "status": credential.status,
            "issuing_authority_id": credential.issuing_authority_id,
            "valid_from": _iso(credential.valid_from),
            "valid_to": _iso(credential.valid_to),
            "version": credential.version,
            "href": f"/masters/{party.id}",
        }
        if credential.credential_type == "business_license":
            businesses.append(entry)
        elif credential.credential_type == "contractor_registration":
            contractors.append(entry)

    property_rows = [
        {
            "parcel_id": parcel.parcel_id,
            "source_parcel_number": parcel.source_parcel_number,
            "jurisdiction_id": parcel.jurisdiction_id,
            "status": parcel.status,
            "valid_from": _iso(parcel.valid_from),
            "version": parcel.version,
            "addresses": [
                {
                    "address_id": address.address_id,
                    "source_string": address.source_string,
                    "unit_number": address.unit_number,
                    "version": address.version,
                }
                for address in by_parcel.get(parcel.parcel_id, [])
                if address is not None
            ],
        }
        for parcel in parcels
    ]
    return {
        "properties": property_rows,
        "businesses": businesses,
        "contractors": contractors,
        "responsibilities": {
            "parcels": responsibility(
                session,
                domain_id="parcels",
                source_system_id="gis",
                dataset_key="parcel_register",
            ),
            "businesses": responsibility(
                session,
                domain_id="businesses",
                source_system_id="erp_finance",
                dataset_key="business_licensing_register",
            ),
            "contractors": responsibility(
                session,
                domain_id="contractors",
                source_system_id="permitting",
                dataset_key="contractor_register",
            ),
        },
    }


def master_detail(session: Session, actor: ActorContext, party_id: str) -> dict[str, Any]:
    """Return the master record view of one business or contractor."""
    party = session.execute(
        select(registry.Party).where(registry.Party.id == party_id)
    ).scalar_one_or_none()
    if party is None:
        return {}
    if party.id not in {row.id for row in visible_parties(session, actor)}:
        return {}
    credentials = session.execute(
        select(registry.Credential).where(registry.Credential.holder_party_id == party.id)
    ).scalars().all()
    domain_id = "businesses"
    for credential in credentials:
        if credential.credential_type == "contractor_registration":
            domain_id = "contractors"
    accounts = session.execute(
        select(registry.FinanceAccount).where(registry.FinanceAccount.party_id == party.id)
    ).scalars().all()
    crosswalks = [
        crosswalk_view(row).model_dump(mode="json")
        for row in session.execute(
            select(registry.Crosswalk)
            .where(registry.Crosswalk.entity_id == party.id)
            .order_by(registry.Crosswalk.created_at)
        ).scalars().all()
    ]
    source_record = _credential_source_record(session, credentials)
    return {
        "party": {
            "party_id": party.id,
            "display_name": party.display_name,
            "legal_name": party.legal_name,
            "party_type": party.party_type,
            "status": party.status,
            "version": party.version,
        },
        "domain_id": domain_id,
        "source_record": source_record,
        "credentials": [
            {
                "credential_id": row.credential_id,
                "credential_type": row.credential_type,
                "number": row.number,
                "status": row.status,
                "issuing_authority_id": row.issuing_authority_id,
                "valid_from": _iso(row.valid_from),
                "valid_to": _iso(row.valid_to),
                "version": row.version,
            }
            for row in credentials
        ],
        "accounts": [
            {
                "account_id": row.account_id,
                "source_account_id": row.source_account_id,
                "account_role": row.account_role,
                "link_status": row.link_status,
                "version": row.version,
            }
            for row in accounts
        ],
        "sources": crosswalks,
        "history": history(session, actor, party.id),
        "responsibility": responsibility(
            session,
            domain_id=domain_id,
            version=party.version,
            subject_ids=(party.id,),
        ),
    }


# ------------------------------------------------------------ permit workspace


def _agent_trace(session: Session, application_id: str) -> list[dict[str, Any]]:
    """Return the recorded runs of the agents on one application.

    The trace is the per-node record of each run: which node ran, at which
    dependency level, with which status and what it found.
    """
    runs = list(
        session.execute(
            select(agent.AgentRun)
            .where(agent.AgentRun.application_id == application_id)
            .order_by(agent.AgentRun.started_at, agent.AgentRun.id)
        ).scalars().all()
    )
    trace: list[dict[str, Any]] = []
    for run in runs:
        nodes = list(
            session.execute(
                select(agent.AgentRunNode)
                .where(agent.AgentRunNode.agent_run_id == run.id)
                .order_by(agent.AgentRunNode.position)
            ).scalars().all()
        )
        for node in nodes:
            trace.append(
                {
                    "step_id": node.id,
                    "step_name": node.node_id,
                    "label": node.label,
                    "dependency_level": node.dependency_level,
                    "service_identity_id": run.service_identity_id,
                    "service_identity_label": actor_label(session, run.service_identity_id),
                    "started_at": _iso(run.started_at),
                    "ended_at": _iso(run.finished_at),
                    "inputs": {},
                    "outcome": node.status,
                    "outcome_detail": node.note or "",
                    "model_run_id": None,
                    "evaluation_id": None,
                    "recommendation_id": None,
                    "triggered_by": run.triggered_by,
                }
            )
    return trace


def permit_workspace(
    session: Session, actor: ActorContext, application_id: str
) -> dict[str, Any]:
    """Return the permit workspace of one application.

    The workspace keeps the submission, the documents, the identity state, the
    validation, the decision, the finance position and the history of one
    case together, and it shows the current, submitted, proposed and issued
    values separately.
    """
    service = PermitService(session)
    application = session.execute(
        select(permit.Application).where(permit.Application.id == application_id)
    ).scalar_one_or_none()
    if application is None or not _application_in_scope(actor, application):
        return {}
    application_view = service.application_view(application).model_dump(mode="json")
    evaluation = service.current_evaluation(application.id)
    evaluation_view = (
        service.evaluation_view(evaluation).model_dump(mode="json")
        if evaluation is not None
        else None
    )
    evaluations = [
        service.evaluation_view(row).model_dump(mode="json")
        for row in session.execute(
            select(permit.Evaluation)
            .where(permit.Evaluation.application_id == application.id)
            .order_by(permit.Evaluation.version)
        ).scalars().all()
    ]
    decisions = [
        {
            "decision_id": row.id,
            "decision_type": row.decision_type,
            "outcome": row.outcome,
            "outcome_label": decision_outcome_label(row),
            "conditions": list(row.conditions or []),
            "decided_by_actor_id": row.decided_by_actor_id,
            "decided_at": _iso(row.decided_at),
            "reason": row.reason,
            "status": row.status,
            "stale": row.stale,
            "version": row.version,
        }
        for row in session.execute(
            select(permit.Decision)
            .where(permit.Decision.application_id == application.id)
            .order_by(permit.Decision.decided_at)
        ).scalars().all()
    ]
    current_decision = service.current_decision(application.id)
    recommendations = [
        {
            "recommendation_id": row.id,
            "proposed_outcome": row.proposed_outcome,
            "evidence_refs": list(row.evidence_refs or []),
            "run_ref": row.run_ref,
            "status": row.status,
            "rationale": row.rationale,
            "muse_summary": row.muse_summary,
            "muse_run_id": row.muse_run_id,
            "conditions": list(row.conditions or []),
            "confirmed_by": row.confirmed_by or "",
            "confirmed_at": _iso(row.confirmed_at),
            "reverted_by": row.reverted_by or "",
            "reverted_at": _iso(row.reverted_at),
            "revert_reason": row.revert_reason or "",
            "decision_id": row.decision_id or "",
        }
        for row in session.execute(
            select(permit.Recommendation).where(
                permit.Recommendation.application_id == application.id
            )
        ).scalars().all()
    ]
    agent_steps = _agent_trace(session, application.id)
    documents = [
        {
            "document_id": row.id,
            "document_type": row.document_type,
            "version": row.version,
            "content_hash": row.content_hash,
            "received_at": _iso(row.received_at),
            "uploaded_by_actor_id": row.uploaded_by_actor_id,
        }
        for row in session.execute(
            select(permit.Document)
            .where(permit.Document.application_id == application.id)
            .order_by(permit.Document.document_type, permit.Document.version)
        ).scalars().all()
    ]
    from acme_city.applicant_portal.service import declared_separately

    stored_types = {item["document_type"] for item in documents}
    # The applicant's statement only; none of these has a stored file.
    documents_declared_separately = [
        item for item in declared_separately(application) if item not in stored_types
    ]
    parties = [
        {
            "party_id": row.party_id,
            "party_role": row.party_role,
            "is_primary": row.is_primary,
            "authority_evidence_ref": row.authority_evidence_ref,
        }
        for row in service.parties(application.id)
    ]
    crosswalks = [
        crosswalk_view(row).model_dump(mode="json")
        for row in session.execute(
            select(registry.Crosswalk)
            .where(
                registry.Crosswalk.entity_id.in_([party["party_id"] for party in parties])
            )
            .order_by(registry.Crosswalk.created_at)
        ).scalars().all()
    ]
    assessment = session.execute(
        select(finance.Assessment)
        .where(
            finance.Assessment.application_id == application.id,
            finance.Assessment.status == "current",
        )
        .order_by(finance.Assessment.version.desc())
    ).scalars().first()
    finance_view: dict[str, Any] = {"assessment": None, "payments": [], "allocations": []}
    if assessment is not None:
        finance_service = FinanceService(session)
        finance_view["assessment"] = finance_service.assessment_view(
            assessment
        ).model_dump(mode="json")
        allocations = session.execute(
            select(finance.Allocation).where(
                finance.Allocation.assessment_id == assessment.id
            )
        ).scalars().all()
        finance_view["allocations"] = [
            finance_service.allocation_view(row).model_dump(mode="json")
            for row in allocations
        ]
        reconciliation = finance_service.compute_reconciliation(
            assessment, [], actor, persist=False
        )
        finance_view["reconciliation"] = reconciliation.model_dump(mode="json")
    issued = [
        {
            "permit_id": row.id,
            "permit_number": row.permit_number,
            "issued_at": _iso(row.issued_at),
            "status": row.status,
            "artifact_hash": row.artifact_hash,
            "decision_id": row.decision_id,
        }
        for row in session.execute(
            select(permit.Permit).where(permit.Permit.application_id == application.id)
        ).scalars().all()
    ]
    proposed = [
        {
            "change_case_id": row.id,
            "title": row.title,
            "status": row.status,
            "reason": row.reason,
            "old_value": dict(row.old_value or {}),
            "proposed_value": dict(row.proposed_value or {}),
            "destination": row.destination,
            "assignee_actor_id": row.assignee_actor_id,
            "version": row.version,
        }
        for row in session.execute(
            select(change.ChangeCase)
            .where(
                change.ChangeCase.target_id == application.id,
                change.ChangeCase.status.notin_(("closed", "rejected")),
            )
            .order_by(change.ChangeCase.created_at)
        ).scalars().all()
    ]
    blockers = _application_blockers(service, application)
    runs = model_runs(session, actor, application_id=application.id)
    # Workspace derivations use only fields already returned above: the
    # pipeline position, the extracted fields of the latest run, the fee
    # preview lines and the applicant-facing tracker/what-next box.
    app_status = application.status
    evaluation_row = evaluation
    decision_row = current_decision
    finance_view_local = finance_view
    issued_rows = issued
    if app_status == "issued" or issued_rows:
        pipe_index = 5
    elif app_status in ("approved", "denied") or decision_row is not None:
        pipe_index = (
            3 if (finance_view_local.get("assessment") if finance_view_local else None) else 2
        )
        if finance_view_local and finance_view_local.get("reconciliation"):
            pipe_index = 3
    elif evaluation_row is not None or app_status in ("under_review", "ready_for_review"):
        pipe_index = 2
    elif app_status == "needs_information":
        pipe_index = 1
    elif app_status in ("submitted", "draft"):
        pipe_index = 1 if evaluation_row is not None else 0
    else:
        pipe_index = 0
    steps_meta = [
        ("Submitted", "send"),
        ("Validated", "shield"),
        ("Decision", "stamp"),
        ("Fee and payment", "coins"),
        ("Issued", "file"),
    ]
    pipeline: list[dict[str, Any]] = []
    for index, (label, icon_name) in enumerate(steps_meta):
        if index < pipe_index:
            state_name = "done"
        elif index == pipe_index:
            state_name = "blocked" if blockers and index in (1, 2) else "current"
        else:
            state_name = ""
        pipeline.append(
            {"label": label, "icon": icon_name, "state": state_name, "index": index}
        )
    latest_run = runs[0] if runs else None
    extracted_fields: list[dict[str, Any]] = []
    if latest_run is not None:
        observations = session.execute(
            select(permit.ExtractionObservation)
            .where(permit.ExtractionObservation.model_run_id == latest_run["run_id"])
            .order_by(permit.ExtractionObservation.field_path)
        ).scalars().all()
        extracted_fields = [
            {
                "observation_id": row.id,
                "field": row.field_path,
                "value": row.proposed_value or "",
                "cite": row.page_region or "",
                "state": row.validation_state,
            }
            for row in observations
        ]
        # Triage may record its run after an earlier manual run; fall back to
        # the newest run that actually produced observations.
        if not extracted_fields:
            for candidate in runs:
                observations = session.execute(
                    select(permit.ExtractionObservation)
                    .where(
                        permit.ExtractionObservation.model_run_id == candidate["run_id"]
                    )
                    .order_by(permit.ExtractionObservation.field_path)
                ).scalars().all()
                if observations:
                    extracted_fields = [
                        {
                            "observation_id": row.id,
                            "field": row.field_path,
                            "value": row.proposed_value or "",
                            "cite": row.page_region or "",
                            "state": row.validation_state,
                        }
                        for row in observations
                    ]
                    break
    fee_lines: list[dict[str, Any]] = []
    fee_total: Any = None
    if finance_view_local and finance_view_local.get("assessment"):
        assessment_vm = finance_view_local["assessment"]
        fee_lines = list(assessment_vm.get("lines") or [])
        fee_total = assessment_vm.get("assessed_total")
    tracker_steps = [
        "Submitted", "Checked", "In review", "Fee", "Paid", "Permit issued",
    ]
    if app_status == "issued" or issued_rows:
        tracker_index = 5
    elif finance_view_local and finance_view_local.get("reconciliation"):
        tracker_index = 4
    elif finance_view_local and finance_view_local.get("assessment"):
        tracker_index = 3
    elif app_status in ("under_review", "ready_for_review", "approved"):
        tracker_index = 2
    elif app_status == "needs_information":
        tracker_index = 1
    else:
        tracker_index = 0
    type_row = service.permit_type(application)
    workspace: dict[str, Any] = {
        "application": application_view,
        "permit_type": {
            "permit_type_id": type_row.id,
            "key": type_row.key,
            "label": type_row.label,
            "icon": icon_for_permit_type(session, type_row),
        },
        "pipeline": pipeline,
        "pipeline_index": pipe_index,
        "extracted_fields": extracted_fields,
        "fee_lines": fee_lines,
        "fee_total": fee_total,
        "tracker": [
            {
                "label": label,
                "state": (
                    "done" if i < tracker_index
                    else "current" if i == tracker_index
                    else ""
                ),
            }
            for i, label in enumerate(tracker_steps)
        ],
        "next_step_text": _next_action(session, actor, service, application, blockers),
        "current": {
            "status": application.status,
            "version": application.version,
            "priority": application.priority,
            "owner_actor_id": application.owner_actor_id or "",
            "site": application_view.get("site"),
            "parties": parties,
        },
        "submitted": {
            "revision_id": application_view.get("revision_id"),
            "revision_number": application_view.get("revision_number"),
            "initial_submitted_at": _iso(application.initial_submitted_at),
            "revision_submitted_at": _iso(application.revision_submitted_at),
            "date_basis": application_view.get("date_basis"),
            "facts": application_view.get("snapshot") or {},
        },
        "proposed": proposed,
        "issued": issued,
        "documents": documents,
        "documents_declared_separately": documents_declared_separately,
        "evaluations": evaluations,
        "evaluation": evaluation_view,
        "decisions": decisions,
        "current_decision": (
            {
                "decision_id": current_decision.id,
                "outcome": current_decision.outcome,
                "outcome_label": decision_outcome_label(current_decision),
                "conditions": list(current_decision.conditions or []),
                "decided_by_actor_id": current_decision.decided_by_actor_id,
                "decided_at": _iso(current_decision.decided_at),
                "reason": current_decision.reason,
                "stale": current_decision.stale,
                "version": current_decision.version,
            }
            if current_decision is not None
            else None
        ),
        "recommendations": recommendations,
        "current_recommendation": next(
            (row for row in recommendations if row["status"] == "pending"), None
        ),
        "findings": [
            {
                "finding_id": row.id,
                "finding_type": row.finding_type,
                "message": row.message,
                "rule": row.rule or "",
                "applicant_must": row.applicant_must or "",
                "severity": row.severity,
                "source_node": row.source_node or "",
                "related_application_id": row.related_application_id or "",
                "state": row.state,
                "revision_number": row.revision_number,
                "waived": row.waived_at is not None,
                "waived_at": _iso(row.waived_at),
                "waived_by_actor_id": row.waived_by_actor_id or "",
                "waiver_reason_code": row.waiver_reason_code or "",
                "waiver_reason_code_label": row.waiver_reason_code_label or "",
                "waiver_reason": row.waiver_reason or "",
                "waivable": row.finding_type in WAIVABLE_TYPES and row.state == "current",
            }
            for row in session.execute(
                select(permit.ApplicationFinding)
                .where(permit.ApplicationFinding.application_id == application.id)
                .order_by(
                    permit.ApplicationFinding.created_at,
                    permit.ApplicationFinding.id,
                )
            ).scalars().all()
        ],
        "comments": [
            comment_view(row)
            for row in comments_for(session, application.id, actor)
        ],
        "lifecycle": _lifecycle_panel(session, actor, application),
        "agent_states": {
            key: agent_views.agent_state(session, key)
            for key in ("intake", "adjudication")
        },
        "can_run_intake": allows(session, actor, "agent.run.intake", "permits"),
        "can_run_adjudication": allows(
            session, actor, "agent.run.adjudication", "permits"
        ),
        "can_decide": allows(session, actor, "permit.decide", "permits"),
        "property": property_views.application_property(session, actor, application),
        "agent_steps": agent_steps,
        "finance": finance_view,
        "blockers": blockers,
        "crosswalks": crosswalks,
        "model_runs": runs,
        "history": history(session, actor, application.id),
        "synthetic": bool(application.synthetic),
        "synthetic_history": _synthetic_history(session, application),
        "evidence": [
            {
                "evidence_id": document["document_id"],
                "kind": "document",
                "label": f"{document['document_type']} v{document['version']}",
                "detail": document["content_hash"],
                "received_at": document["received_at"],
                "content_hash": document["content_hash"],
            }
            for document in documents
        ],
        "responsibility": responsibility(
            session,
            domain_id="permits",
            version=application.version,
            source_system_id="permitting",
            dataset_key="applications_and_permits",
            subject_ids=(application.id,),
        ),
    }
    workspace["reviewer"] = reviewer_views.workspace_extras(
        session, actor, application, workspace
    )
    return workspace


# ------------------------------------------------------------- steward review


def steward_review(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the steward review screen.

    The screen compares the proposed links with their supporting and
    conflicting evidence, shows the impact of the open change cases, and
    reports the acknowledgement status of every source command.
    """
    decided_records = {
        (row.source_system_id, row.source_dataset_key, row.source_record_id)
        for row in session.execute(
            select(registry.Crosswalk).where(
                registry.Crosswalk.link_status != "proposed"
            )
        ).scalars().all()
    }
    snapshots = {
        row.source_snapshot_id: row
        for row in session.execute(select(source.SourceSnapshot)).scalars().all()
    }
    proposals = [
        {
            "proposal_id": row.id,
            "source_snapshot_id": row.source_snapshot_id,
            "source_system_id": (
                snapshots[row.source_snapshot_id].source_system_id
                if row.source_snapshot_id in snapshots
                else ""
            ),
            "source_dataset_key": (
                snapshots[row.source_snapshot_id].source_dataset_id
                if row.source_snapshot_id in snapshots
                else ""
            ),
            "source_record_id": (
                snapshots[row.source_snapshot_id].source_record_id
                if row.source_snapshot_id in snapshots
                else ""
            ),
            "entity_id": row.entity_id,
            "entity_type": "party",
            "disposition": row.disposition,
            "method": row.method,
            "proposal_score": row.proposal_score,
            "score_is_calibrated": bool(row.score_is_calibrated),
            "score_label": "uncalibrated_heuristic",
            "candidate_ids": list(row.candidate_ids or []),
            "compared_fields": list(row.compared_fields or []),
            "supporting": list(row.supporting_evidence or []),
            "conflicting": list(row.conflicting_evidence or []),
            "created_by_actor_id": row.created_by_actor_id,
            "created_at": _iso(row.created_at),
            "scenario_id": row.scenario_id,
            "awaiting_decision": (
                snapshots[row.source_snapshot_id].source_system_id
                if row.source_snapshot_id in snapshots
                else "",
                snapshots[row.source_snapshot_id].source_dataset_id
                if row.source_snapshot_id in snapshots
                else "",
                snapshots[row.source_snapshot_id].source_record_id
                if row.source_snapshot_id in snapshots
                else "",
            )
            not in decided_records,
        }
        for row in session.execute(
            select(registry.MatchProposal).order_by(registry.MatchProposal.created_at)
        ).scalars().all()
    ]
    crosswalks = [
        crosswalk_view(row).model_dump(mode="json")
        for row in session.execute(
            select(registry.Crosswalk).order_by(registry.Crosswalk.created_at)
        ).scalars().all()
    ]
    change_service = ChangeService(session)
    cases = []
    for case in session.execute(
        select(change.ChangeCase).order_by(change.ChangeCase.created_at)
    ).scalars().all():
        view_model = change_service.case_view(case)
        cases.append(view_model.model_dump(mode="json"))
    commands = [
        {
            "source_command_id": row.id,
            "change_case_id": row.change_case_id,
            "source_system_id": row.source_system_id,
            "operation": row.operation,
            "expected_source_version": row.expected_source_version,
            "accepted_source_version": row.accepted_source_version,
            "status": row.status,
            "response": dict(row.response or {}),
            "actor_id": row.actor_id,
        }
        for row in session.execute(
            select(change.SourceCommand).order_by(change.SourceCommand.id)
        ).scalars().all()
    ]
    deliveries = [
        {
            "delivery_id": row.id,
            "change_case_id": row.change_case_id,
            "destination": row.destination,
            "status": row.status,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "acknowledged_at": _iso(row.acknowledged_at),
        }
        for row in session.execute(
            select(change.OutboxDelivery).order_by(change.OutboxDelivery.id)
        ).scalars().all()
    ]
    source_records = []
    for row in session.execute(
        select(source.SourceSnapshot)
        .where(source.SourceSnapshot.record_status == "accepted")
        .order_by(
            source.SourceSnapshot.source_system_id,
            source.SourceSnapshot.source_dataset_id,
            source.SourceSnapshot.source_record_id,
        )
    ).scalars().all():
        source_records.append(
            {
                "source_system_id": row.source_system_id,
                "source_dataset_id": row.source_dataset_id,
                "source_record_id": row.source_record_id,
                "source_record_version": row.source_record_version,
                "source_updated_at": _iso(row.source_updated_at),
                "ingested_at": _iso(row.ingested_at),
                "scenario_id": row.scenario_id,
            }
        )
    return {
        "parcel_proposals": property_views.steward_parcel_proposals(session, actor),
        "proposals": proposals,
        "crosswalks": crosswalks,
        "cases": cases,
        "commands": commands,
        "deliveries": deliveries,
        "source_records": source_records,
        "responsibility": responsibility(
            session,
            domain_id="applicants",
            source_system_id="permitting",
            dataset_key="applicant_profiles",
        ),
        "model_runs": model_runs(session, actor),
        "history": stewardship_history(session),
    }


# -------------------------------------------------------------- rules and fees


def rules_fees(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the rule and fee catalogue screen."""
    catalog = RuleCatalogService(session)
    versions = [view.model_dump(mode="json") for view in catalog.list_versions()]
    fee_schedules = [
        {
            "row_id": row.id,
            "fee_schedule_id": row.fee_schedule_id,
            "version_label": row.version_label,
            "version": row.version,
            "effective_from": _iso(row.effective_from),
            "effective_to": _iso(row.effective_to),
            "currency": row.currency,
            "definition": dict(row.definition or {}),
            "status": row.status,
            "author_actor_id": row.author_actor_id,
            "approver_actor_id": row.approver_actor_id,
        }
        for row in session.execute(
            select(finance.FeeScheduleVersion).order_by(
                finance.FeeScheduleVersion.fee_schedule_id,
                finance.FeeScheduleVersion.effective_from,
            )
        ).scalars().all()
    ]
    return {
        "versions": versions,
        "fee_schedules": fee_schedules,
        "permit_type_icons": permit_type_icons(session, actor),
        "responsibility": responsibility(
            session,
            domain_id="building_rules",
            source_system_id="permitting",
            dataset_key="approved_rules_register",
        ),
    }


# -------------------------------------------------------------- reconciliation


def reconciliation(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the reconciliation screen.

    The screen shows every assessment version, the receipts, the confirmed
    allocations, the balance and the exception of each position.
    """
    service = FinanceService(session)
    assessments = []
    for assessment in session.execute(
        select(finance.Assessment).order_by(
            finance.Assessment.application_id, finance.Assessment.version
        )
    ).scalars().all():
        view_model = service.assessment_view(assessment).model_dump(mode="json")
        position = service.compute_reconciliation(
            assessment, [], actor, persist=False
        ).model_dump(mode="json")
        assessed_cents = view_model.get("assessed_total_cents")
        if assessed_cents is None:
            raw_total = view_model.get("assessed_total")
            try:
                assessed_cents = int(round(float(str(raw_total)) * 100))
            except (TypeError, ValueError):
                assessed_cents = 0
        position["assessed_total_cents"] = assessed_cents
        position["settled_allocated_cents"] = int(
            position.get("settled_allocated_cents") or 0
        )
        position["alloc_pct"] = (
            min(100, round(100 * position["settled_allocated_cents"] / assessed_cents))
            if assessed_cents
            else 0
        )
        assessments.append({**view_model, "position": position})
    payments = [
        service.payment_view(row).model_dump(mode="json")
        for row in session.execute(
            select(finance.Payment).order_by(finance.Payment.source_transaction_id)
        ).scalars().all()
    ]
    allocations = [
        service.allocation_view(row).model_dump(mode="json")
        for row in session.execute(
            select(finance.Allocation).order_by(finance.Allocation.id)
        ).scalars().all()
    ]
    accounts = [
        {
            "account_id": row.account_id,
            "source_account_id": row.source_account_id,
            "account_role": row.account_role,
            "link_status": row.link_status,
            "party_id": row.party_id,
            "version": row.version,
        }
        for row in session.execute(
            select(registry.FinanceAccount).order_by(registry.FinanceAccount.account_id)
        ).scalars().all()
    ]
    return {
        "assessments": assessments,
        "payments": payments,
        "allocations": allocations,
        "accounts": accounts,
        "responsibility": responsibility(
            session,
            domain_id="finance",
            source_system_id="erp_finance",
            dataset_key="finance_accounts",
        ),
    }


# --------------------------------------------------------- governance and sources


def governance_sources(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the governance and sources screen."""
    service = GovernanceService(session)
    registrations = [
        view.model_dump(mode="json") for view in service.list_registrations()
    ]
    domains = [
        {
            "domain_id": row.domain_id,
            "label": row.label,
            "accountable_owner_actor_id": row.accountable_owner_actor_id,
            "steward_queue_id": row.steward_queue_id,
            "system_custodian_actor_id": row.system_custodian_actor_id,
            "default_source_system_id": row.default_source_system_id,
            "default_dataset_key": row.default_dataset_key,
            "version": row.version,
        }
        for row in session.execute(
            select(governance.Domain).order_by(governance.Domain.domain_id)
        ).scalars().all()
    ]
    queues = [
        {
            "queue_id": row.queue_id,
            "domain_id": row.domain_id,
            "label": row.label,
            "primary_actor_id": row.primary_actor_id,
            "delegate_actor_id": row.delegate_actor_id,
            "escalation_actor_id": row.escalation_actor_id,
            "cross_domain_escalation_actor_id": row.cross_domain_escalation_actor_id,
            "first_review_target_quantity": row.first_review_target_quantity,
            "first_review_target_unit": row.first_review_target_unit,
            "service_promise": row.service_promise,
            "version": row.version,
        }
        for row in session.execute(
            select(governance.StewardQueue).order_by(governance.StewardQueue.queue_id)
        ).scalars().all()
    ]
    assignments = [
        view.model_dump(mode="json") for view in service.current_assignments()
    ]
    policies = [
        {
            "policy_id": row.policy_id,
            "field_group": row.field_group,
            "domain_id": row.domain_id,
            "authoritative_source_system_id": row.authoritative_source_system_id,
            "authoritative_dataset_key": row.authoritative_dataset_key,
            "change_destination": row.change_destination,
            "user_action": row.user_action,
            "requires_source_ack": row.requires_source_ack,
            "decision_relevant": row.decision_relevant,
            "status": row.status,
            "approver_actor_id": row.approver_actor_id,
            "version": row.version,
        }
        for row in session.execute(
            select(governance.AuthorityPolicy).order_by(governance.AuthorityPolicy.policy_id)
        ).scalars().all()
    ]
    staged = [
        {
            "source_snapshot_id": row.source_snapshot_id,
            "source_system_id": row.source_system_id,
            "source_dataset_id": row.source_dataset_id,
            "source_record_id": row.source_record_id,
            "source_record_version": row.source_record_version,
            "record_status": row.record_status,
            "ingested_at": _iso(row.ingested_at),
            "scenario_id": row.scenario_id,
        }
        for row in session.execute(
            select(source.SourceSnapshot)
            .where(source.SourceSnapshot.record_status == "staged")
            .order_by(source.SourceSnapshot.source_record_id)
        ).scalars().all()
    ]
    quarantined = [
        {
            "error_id": row.id,
            "source_snapshot_id": row.source_snapshot_id,
            "field_path": row.field_path,
            "error_code": row.error_code,
            "message": row.message,
            "responsible_queue_id": row.responsible_queue_id,
            "status": row.status,
        }
        for row in session.execute(
            select(source.QuarantineError).order_by(source.QuarantineError.id)
        ).scalars().all()
    ]
    commands = [
        {
            "source_command_id": row.id,
            "change_case_id": row.change_case_id,
            "source_system_id": row.source_system_id,
            "operation": row.operation,
            "status": row.status,
            "accepted_source_version": row.accepted_source_version,
        }
        for row in session.execute(
            select(change.SourceCommand).order_by(change.SourceCommand.id)
        ).scalars().all()
    ]
    subscriber_rows = property_views.subscribers_for(session, None)
    return {
        "published_datasets": [
            {
                "dataset_key": "property_master",
                "label": "Property master (parcel, address, owner, zoning)",
                "owner": "Planning and Development Services (simulated GIS parcel register)",
                "subscribers": subscriber_rows,
                "notice": property_views.DEPARTMENT_NOTICE,
            }
        ],
        "registrations": registrations,
        "domains": domains,
        "queues": queues,
        "assignments": assignments,
        "policies": policies,
        "staged": staged,
        "quarantined": quarantined,
        "commands": commands,
        "responsibility": responsibility(
            session,
            domain_id="records",
            source_system_id="permitting",
            dataset_key="applications_and_permits",
        ),
    }


# ------------------------------------------------------------------- evidence


def model_runs(
    session: Session, actor: ActorContext, *, application_id: str | None = None
) -> list[dict[str, Any]]:
    """Return the recorded model runs with their explicit mode badge.

    A run of the applicant help assistant is the record of a private
    conversation.  It is never listed on a staff screen: staff read an
    un-escalated chat never, and the administrator sees an escalated
    conversation through the support screen instead.
    """
    statement = select(model_run.ModelRun).order_by(model_run.ModelRun.started_at.desc())
    if application_id:
        statement = statement.where(
            model_run.ModelRun.input_refs.is_not(None),
        )
    rows = session.execute(statement).scalars().all()
    runs: list[dict[str, Any]] = []
    for row in rows:
        # input_refs is stored as an object ({"application_id": ..., "documents": [...]});
        # older rows may be a plain list of references.
        raw_refs = row.input_refs or {}
        refs = list(raw_refs) if not isinstance(raw_refs, dict) else [raw_refs]
        run_application = raw_refs.get("application_id") if isinstance(raw_refs, dict) else None
        if isinstance(raw_refs, dict) and str(raw_refs.get("task") or "") in PRIVATE_TASKS:
            # A chat run is private to its applicant; a what-if run is shown
            # only through the policy screens, to the holders of its grants.
            continue
        if application_id and application_id != run_application and application_id not in refs:
            continue
        validation = dict(row.validation_result or {})
        runs.append(
            {
                "run_id": row.id,
                "task": "extraction" if "document" in str(refs) else "model task",
                "mode": row.mode,
                "mode_label": row.mode.capitalize(),
                "source_label": muse_source_label(row.model, row.mode),
                "status": row.status,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "response_id": row.provider_response_id,
                "latency_ms": row.latency_ms,
                "error": row.error,
                "started_at": _iso(row.started_at),
                "completed_at": _iso(row.completed_at),
                "actor_id": row.actor_id,
                "replay_of_run_id": row.replay_of_run_id,
                "input_refs": refs,
                "validation_errors": list(validation.get("errors") or []),
                "validation_result": validation,
                "output": dict(row.output or {}),
                "usage": dict(row.usage or {}),
            }
        )
    return runs


def _synthetic_history(session: Session, application: permit.Application) -> list[dict[str, str]]:
    """Return the dated history of a synthetic case, or an empty list.

    A synthetic case has no audit events: nobody acted.  Its dates are stored
    facts of a generated historical record, and the screen says so.
    """
    if not application.synthetic:
        return []
    entries: list[dict[str, str]] = []
    if application.initial_submitted_at is not None:
        entries.append({"when": application.initial_submitted_at.isoformat(), "what": "Submitted"})
    for decision in session.execute(
        select(permit.Decision).where(permit.Decision.application_id == application.id)
    ).scalars():
        entries.append({"when": decision.decided_at.isoformat(), "what": f"Decision recorded: {decision.outcome}"})
    for issued in session.execute(
        select(permit.Permit).where(permit.Permit.application_id == application.id)
    ).scalars():
        entries.append({"when": issued.issued_at.isoformat(), "what": f"Permit {issued.permit_number} issued"})
    return sorted(entries, key=lambda item: item["when"])


def muse_source_label(model: str | None, mode: str) -> str:
    """Return the source label of a model run, for example ``Muse Spark (live)``.

    A Muse model is named by its family and the run mode in brackets, so a
    live run reads ``Muse Spark (live)`` and a replay reads ``Muse Spark
    (replay)``.  A run of another model keeps its own model name.
    """
    name = (model or "").strip()
    if name.lower().startswith("muse-spark"):
        family = "Muse Spark"
    elif name.lower().startswith("muse-wonder"):
        family = "Muse Wonder"
    elif name.lower().startswith("muse-image"):
        family = "Muse Image"
    else:
        family = name or "no model recorded"
    return f"{family} ({mode})"


def history(session: Session, actor: ActorContext, target_id: str) -> list[dict[str, Any]]:
    """Return the recorded history of one record.

    The history is the append-only audit trail.  It is read, never written,
    by the interface.  An event that records an internal comment is not
    shown to an applicant at all: the applicant never learns that an
    internal note exists.
    """
    from acme_city.permits.comments import is_staff

    rows = session.execute(
        select(audit.AuditEvent)
        .where(audit.AuditEvent.target_id == target_id)
        .order_by(audit.AuditEvent.occurred_at.desc())
    ).scalars().all()
    staff = is_staff(session, actor)
    entries: list[dict[str, Any]] = []
    for row in rows:
        entry = _history_entry(session, row)
        comment_id = str((row.metadata_json or {}).get("comment_id") or "")
        if not comment_id:
            entries.append(entry)
            continue
        comment = session.get(permit.ApplicationComment, comment_id)
        if comment is None:
            continue
        if comment.visibility == "internal" and not staff:
            continue
        entry["comment_id"] = comment.id
        entry["comment_visibility"] = comment.visibility
        entry["comment_body"] = comment.body
        entries.append(entry)
    return entries


def stewardship_history(session: Session, limit: int = 25) -> list[dict[str, Any]]:
    """Return the recorded stewardship history of the demonstration."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.action.like("registry.%")
            | audit.AuditEvent.action.like("change.%")
            | audit.AuditEvent.action.like("source.%")
            | audit.AuditEvent.action.like("ui.%")
        )
        .order_by(audit.AuditEvent.occurred_at.desc())
        .limit(limit)
    ).scalars().all()
    return [_history_entry(session, row) for row in rows]


def decision_outcome_label(row: permit.Decision) -> str:
    """Return the outcome a person reads: an approval with conditions says so."""
    if row.outcome == "approved" and row.conditions:
        return "Approved with conditions"
    if row.outcome == "modified":
        # A modified decision keeps its own meaning: it is not issuable.
        return "Modified (not issuable)"
    return row.outcome.replace("_", " ").capitalize()


def _history_entry(session: Session, row: audit.AuditEvent) -> dict[str, Any]:
    """Return the readable form of one audit event."""
    return {
        "event_id": row.id,
        "occurred_at": _iso(row.occurred_at),
        "actor_id": row.actor_id,
        "actor_label": actor_label(session, row.actor_id),
        "action": row.action,
        "outcome": row.outcome,
        "before_version": row.before_version,
        "after_version": row.after_version,
        "reason": row.reason,
        "references": list(row.references or []),
        "denial_reason": row.denial_reason,
    }


def feedback(session: Session, actor: ActorContext) -> dict[str, Any] | None:
    """Return the last action the acting persona performed.

    The feedback is read from the append-only audit trail, so it survives a
    refresh, a navigation and a restart of the application.
    """
    row = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.actor_id == actor.actor_id,
            audit.AuditEvent.action.like("ui.%"),
        )
        .order_by(audit.AuditEvent.occurred_at.desc())
    ).scalars().first()
    if row is None:
        return None
    metadata = dict(row.metadata_json or {})
    return {
        "event_id": row.id,
        "occurred_at": _iso(row.occurred_at),
        "action": row.action,
        "outcome": row.outcome,
        "reason": row.reason,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before_version": row.before_version,
        "after_version": row.after_version,
        "destination": metadata.get("destination", ""),
        "state": metadata.get("state", ""),
        "pending": bool(metadata.get("pending", False)),
        "affected": list(metadata.get("affected") or []),
        "detail": metadata.get("detail", ""),
    }


__all__ = [
    "PERSONA_ORDER",
    "SCREEN_DOMAIN",
    "SCREEN_PERMISSIONS",
    "SCREENS",
    "actor_department",
    "home_for",
    "may_open_screen",
    "screen_for_path",
    "screen_label",
    "action",
    "allowed_actions_for",
    "allows",
    "applicants",
    "correction_destination",
    "denied_action_explanations",
    "feedback",
    "governance_sources",
    "history",
    "master_detail",
    "masters",
    "model_runs",
    "navigation",
    "open_issues",
    "party_detail",
    "permit_type_icons",
    "permit_workspace",
    "persona_options",
    "reconciliation",
    "responsibility",
    "rules_fees",
    "source_times",
    "steward_review",
    "stewardship_history",
    "visible_applications",
    "visible_parties",
    "work_queue",
]

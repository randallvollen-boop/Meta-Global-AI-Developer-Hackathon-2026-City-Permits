"""The City Administrator screens: the planning overview, the rules and fee
register, the governance and sources screen and the reconciliation screen.

Every figure is a server query over the stored rows and is labelled with the
definition it counts.  Nothing in this module decides anything: it reports
what the services recorded, diffs two stored version records against each
other, and names the next action the acting persona is allowed to take.  The
rule and fee lifecycle itself is owned by ``rules/service.py``; this module
never transitions a version.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-03, GOV-04, REF-01, REF-02, PER-02, PER-06, FIN-01, FIN-05, SEC-01
# The Administrator screens show the recorded facts of the rule catalogue, the
# source registrations and the finance positions, with the applicable rule
# versions, the recorded history and the next authorized action.

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.finance.service import FinanceService
from acme_city.governance.service import GovernanceService
from acme_city.permits.schemas import DEFAULT_DATE_BASIS
from acme_city.persistence.models import (
    audit,
    change,
    finance,
    governance,
    permit,
    registry,
    source,
)
from acme_city.rules import approval_policy, catalog
from acme_city.ui import ops_views, property_views, view_models
from acme_city.ui.view_models import action as build_action
from acme_city.ui.view_models import _field

#: The months of a readable date, in order.
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

#: The labels of the rule and fee version states.  ``in_review`` is the only
#: state in which a version is actually waiting for an approval.
VERSION_STATUS_LABELS: dict[str, str] = {
    "draft": "Draft",
    "in_review": "In review, awaiting approval",
    "approved": "Approved",
    "published": "Published",
    "retired": "Retired",
}

#: The two registers of the rules and fees screen.
RULE_TABS: tuple[tuple[str, str], ...] = (("rules", "Rules"), ("fees", "Fee schedules"))

#: The three views every register has.
REGISTER_VIEWS: tuple[tuple[str, str], ...] = (
    ("published", "Published"),
    ("drafts", "Drafts"),
    ("history", "History"),
)

#: The fields of a rule version that a diff compares.
_RULE_DIFF_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Title"),
    ("citation", "Citation"),
    ("project_type", "Project type"),
    ("field_path", "Checked field"),
    ("operator", "Operator"),
    ("limit_value", "Limit"),
    ("on_violate", "On violation"),
    ("condition", "Condition"),
    ("message", "Message"),
    ("condition_note", "Condition note"),
    ("effective_from", "Effective from"),
    ("effective_to", "Effective to"),
)

#: The fields of a fee schedule version that a diff compares.
_FEE_DIFF_FIELDS: tuple[tuple[str, str], ...] = (
    ("currency", "Currency"),
    ("effective_from", "Effective from"),
    ("effective_to", "Effective to"),
)

#: The fee components a diff compares inside the stored definition.
_FEE_COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("fixed_review_charge_cents", "Fixed review charge (cents)"),
    ("valuation_multiplier", "Valuation multiplier"),
    ("rounding", "Rounding"),
    ("rounding_scope", "Rounding scope"),
    ("version_basis", "Version basis"),
    ("formula", "Formula"),
)

#: The three simulated source systems the overview names.
_OVERVIEW_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("gis", "GIS", "property, parcel and address"),
    ("permitting", "Permitting", "applications, applicants and review events"),
    ("erp_finance", "ERP/Finance", "assessments and receipts"),
)

#: The recorded basis a version is selected on, in plain words.  The service
#: selects it from ``permits/service.py``; the screen names it.
DATE_BASIS_TEXT = f"the initial submission time ({DEFAULT_DATE_BASIS})"


# ------------------------------------------------------------------- helpers


def _readable_date(value: datetime | None) -> str:
    """Return a date a person can read, without a time."""
    if value is None:
        return ""
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _readable_window(
    effective_from: datetime | None, effective_to: datetime | None
) -> str:
    """Return the readable effective period of a version."""
    start = _readable_date(effective_from) or "not recorded"
    if effective_to is None:
        return f"From {start}, open ended"
    return f"{start} to {_readable_date(effective_to)}"


def _permit_type_labels(session: Session) -> dict[str, str]:
    """Return the readable label of every permit type, keyed by its id."""
    rows = session.execute(select(permit.PermitType)).scalars().all()
    return {row.id: row.label for row in rows}


def _actor_label(session: Session, actor_id: str | None) -> str:
    """Return the readable label of one actor, or the id when there is none."""
    if not actor_id:
        return "not recorded"
    return view_models.actor_label(session, actor_id)


def _assigned_approver(session: Session, domain_id: str) -> str:
    """Return the accountable owner of a domain: who is responsible for approving.

    The owner is a stored assignment of the domain, not a person who happens
    to hold the approval grant today.
    """
    domain = session.execute(
        select(governance.Domain).where(governance.Domain.domain_id == domain_id)
    ).scalar_one_or_none()
    if domain is None or not domain.accountable_owner_actor_id:
        return "not assigned"
    return _actor_label(session, domain.accountable_owner_actor_id)


def _approval_record(
    session: Session, target_type: str, target_id: str
) -> audit.AuditEvent | None:
    """Return the audit event that recorded the approval of a version."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type == target_type,
            audit.AuditEvent.target_id == target_id,
            audit.AuditEvent.action.in_(("rule.version.approve", "fee.schedule.approved")),
        )
        .order_by(audit.AuditEvent.occurred_at.desc())
    ).scalars().all()
    return rows[0] if rows else None


def _basis_label(event: audit.AuditEvent | None) -> str:
    """Return the recorded approval basis of an event, such as the single-administrator policy."""
    if event is None:
        return ""
    return str((event.metadata_json or {}).get(approval_policy.BASIS_KEY, ""))


def _approval_text(session: Session, event: audit.AuditEvent) -> str:
    """Return the plain sentence that says who approved a version, and on what basis."""
    who = _actor_label(session, event.actor_id)
    when = _readable_date(event.occurred_at)
    basis = _basis_label(event)
    if basis:
        return f"{basis}. {who} approved it on {when}."
    return f"Approved by {who} on {when}."


def _version_history(
    session: Session, target_type: str, target_id: str
) -> list[dict[str, Any]]:
    """Return the recorded review, approval and publication events of a version."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type == target_type,
            audit.AuditEvent.target_id == target_id,
        )
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id)
    ).scalars().all()
    return [
        {
            "action": row.action,
            "occurred_at": view_models._iso(row.occurred_at),
            "occurred_date": _readable_date(row.occurred_at),
            "actor": _actor_label(session, row.actor_id),
            "outcome": row.outcome,
            "reason": row.reason or "",
            "references": list(row.references or []),
            "before_version": row.before_version,
            "after_version": row.after_version,
            "basis": _basis_label(row),
        }
        for row in rows
    ]


def _application_reference(session: Session, application_id: str) -> str:
    """Return the readable reference of an application.

    The readable reference is the source application number.  The internal
    identifier is a different name of the same row, never a second record.
    """
    row = session.get(permit.Application, application_id)
    if row is None:
        return "not recorded"
    return row.source_application_number


def _applications_in_window(
    session: Session,
    permit_type_id: str | None,
    effective_from: datetime | None,
    effective_to: datetime | None,
) -> list[dict[str, Any]]:
    """Return the applications a version would apply to.

    The applicability rule is the configured one: the permit type of the
    version and the effective window, read against the initial submission
    time of each application.
    """
    rows = session.execute(
        select(permit.Application).order_by(permit.Application.source_application_number)
    ).scalars().all()
    selected: list[dict[str, Any]] = []
    for row in rows:
        if (row.permit_type_id or None) != (permit_type_id or None):
            continue
        basis = row.initial_submitted_at
        if basis is None:
            continue
        if effective_from is not None and effective_to is not None:
            if not catalog.effective_at(effective_from, effective_to, basis):
                continue
        elif effective_from is not None and basis < effective_from:
            continue
        elif effective_to is not None and basis >= effective_to:
            continue
        selected.append(
            {
                "reference": row.source_application_number,
                "application_id": row.id,
                "basis_date": _readable_date(basis),
                "basis_iso": view_models._iso(basis),
                "href": f"/permits/{row.id}",
            }
        )
    return selected


# ------------------------------------------------------------------- overview


def planning_overview(session: Session, actor: ActorContext) -> dict[str, Any]:
    """Return the planning overview of the City Administrator.

    The overview is a hub: every card counts stored rows and opens the
    records behind the count.  It never repeats a screen it links to.
    """
    applications = view_models.visible_applications(session, actor)
    live = [row for row in applications if row.status != "archived"]
    type_labels = _permit_type_labels(session)

    # Applications needing attention: an open finding, a site that is not
    # resolved, or an open recorded issue.  Each reason is counted once.
    attention: list[dict[str, Any]] = []
    for row in live:
        reasons: list[str] = []
        findings = session.execute(
            select(permit.ApplicationFinding).where(
                permit.ApplicationFinding.application_id == row.id,
                permit.ApplicationFinding.state == "current",
            )
        ).scalars().all()
        if findings:
            reasons.append(
                f"{len(findings)} open finding(s): {findings[0].message}"
            )
        site = session.execute(
            select(permit.ApplicationSite).where(
                permit.ApplicationSite.application_id == row.id,
                permit.ApplicationSite.is_primary.is_(True),
            )
        ).scalar_one_or_none()
        if site is not None and site.resolution_status != "resolved":
            reasons.append(f"the site is {site.resolution_status}")
        issues = view_models.open_issues(session, (row.id,))
        if issues:
            reasons.append(f"{len(issues)} open recorded issue(s)")
        if reasons:
            attention.append(
                {
                    "reference": row.source_application_number,
                    "application_id": row.id,
                    "project_type": type_labels.get(row.permit_type_id, "not recorded"),
                    "reason": reasons[0],
                    "reason_count": len(reasons),
                    "more_note": (
                        "More reasons on the case." if len(reasons) > 1 else ""
                    ),
                    "href": f"/permits/{row.id}",
                }
            )

    # Property context: the applications with a stored site record.
    sites = session.execute(
        select(permit.ApplicationSite).where(permit.ApplicationSite.is_primary.is_(True))
    ).scalars().all()
    site_by_application = {row.application_id: row for row in sites}
    property_items: list[dict[str, Any]] = []
    for row in live:
        site = site_by_application.get(row.id)
        if site is None:
            continue
        property_items.append(
            {
                "reference": row.source_application_number,
                "application_id": row.id,
                "project_type": type_labels.get(row.permit_type_id, "not recorded"),
                "parcel": _parcel_number(session, site.parcel_id),
                "address": _address_text(session, site.address_id),
                "resolution": site.resolution_status,
                "detail_href": f"/overview?detail=property-context:{row.id}",
            }
        )

    # Proposed changes: the versions that are not published or retired yet.
    proposed = _proposed_versions(session)
    policy = approval_policy_view()

    # Source information: the three simulated source systems.
    source_items: list[dict[str, Any]] = []
    for source_system_id, label, records in _OVERVIEW_SOURCES:
        last_change, last_received = view_models.source_times(session, source_system_id)
        source_items.append(
            {
                "source_system_id": source_system_id,
                "label": label,
                "records": records,
                "last_changed": _readable_date(last_change),
                "last_changed_iso": view_models._iso(last_change),
                "last_received": _readable_date(last_received),
                "last_received_iso": view_models._iso(last_received),
                "freshness_known": last_change is not None or last_received is not None,
                "href": f"/governance?tab=sources&source={source_system_id}",
            }
        )

    related = [
        {
            "label": "City view",
            "href": "/insight/city",
            "note": "Permit activity, business categories and the simulated departments.",
        },
        {
            "label": "What-if",
            "href": "/policy/scenarios",
            "note": "Test a proposed rule change on a set of cases before anything changes.",
        },
    ]
    if view_models.may_open_screen(session, actor, "ops_dashboard"):
        related.append(
            {
                "label": "Operations dashboard",
                "href": "/ops/dashboard",
                "note": "How permit work is going, counted from the stored cases.",
            }
        )

    return {
        "scope_label": "Sample applications · synthetic",
        "attention": {
            "label": "Applications needing attention",
            "definition": (
                "Sample applications with an open agent finding, a site that is not "
                "resolved, or an open recorded issue."
            ),
            "count": len(attention),
            "href": "/queue?view=needs-checks",
            "entries": attention[:8],
            "more": max(0, len(attention) - 8),
        },
        "property": {
            "label": "Applications with property details",
            "definition": (
                "Sample applications with a stored primary site: the parcel, the "
                "official address and the documents that apply."
            ),
            "count": len(property_items),
            "href": "/property",
            "entries": property_items[:8],
            "more": max(0, len(property_items) - 8),
        },
        "changes": {
            "label": "Unpublished rule and fee versions",
            "definition": (
                "Rule and fee schedule versions that are drafted, in review or "
                "approved and are not published or retired. They are not waiting "
                "for an approval."
            ),
            "count": len(proposed),
            "href": "/rules?tab=rules&view=drafts",
            "entries": proposed[:8],
            "more": max(0, len(proposed) - 8),
            "approval_policy": policy,
        },
        "sources": {
            "label": "Simulated source systems",
            "definition": (
                "The simulated source systems the demonstration reads from. The "
                "count is the number of configured systems."
            ),
            "count": len(source_items),
            "href": "/governance?tab=sources",
            "entries": source_items,
        },
        "related": related,
        "unresolved_count": len(attention),
    }


def _parcel_number(session: Session, parcel_id: str | None) -> str:
    """Return the readable parcel number of a parcel id."""
    if not parcel_id:
        return "not resolved"
    row = session.get(registry.Parcel, parcel_id)
    return row.source_parcel_number if row is not None else "not recorded"


def _address_text(session: Session, address_id: str | None) -> str:
    """Return the readable official address, including its unit."""
    if not address_id:
        return "not resolved"
    row = session.get(registry.Address, address_id)
    if row is None:
        return "not recorded"
    if row.source_string:
        return row.source_string
    parts = [row.street_number, row.street_name, row.street_type]
    text = " ".join(part for part in parts if part)
    if row.unit_number:
        text = f"{text} {row.unit_type or 'unit'} {row.unit_number}".strip()
    return text or "not recorded"


def _next_step_text(status: str) -> str:
    """Return the next step of a proposed version under the active approval policy."""
    if status == "draft":
        return "Submit for review"
    if status == "in_review":
        if approval_policy.is_single():
            return "Ready for approval by a City Administrator, who may be the author"
        return "Needs approval by an administrator other than the author"
    if status == "approved":
        return "Ready to publish"
    return ""


def _proposed_versions(session: Session) -> list[dict[str, Any]]:
    """Return the rule and fee versions that are not published or retired."""
    items: list[dict[str, Any]] = []
    for row in session.execute(
        select(finance.RuleVersion).order_by(
            finance.RuleVersion.rule_id, finance.RuleVersion.effective_from
        )
    ).scalars().all():
        if row.status in ("published", "retired"):
            continue
        items.append(
            {
                "kind": "Rule version",
                "version_label": catalog.version_label(row),
                "title": row.title,
                "status": row.status,
                "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
                "date_label": "Proposed effective date",
                "date": _readable_date(row.effective_from),
                "next_step": _next_step_text(row.status),
                "href": f"/rules?tab=rules&view=drafts&version={row.id}",
            }
        )
    for row in session.execute(
        select(finance.FeeScheduleVersion).order_by(
            finance.FeeScheduleVersion.fee_schedule_id,
            finance.FeeScheduleVersion.effective_from,
        )
    ).scalars().all():
        if row.status in ("published", "retired"):
            continue
        items.append(
            {
                "kind": "Fee schedule version",
                "version_label": f"{row.fee_schedule_id} {row.version_label}",
                "title": "Fee schedule",
                "status": row.status,
                "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
                "date_label": "Proposed effective date",
                "date": _readable_date(row.effective_from),
                "next_step": _next_step_text(row.status),
                "href": f"/rules?tab=fees&view=drafts&version={row.id}",
            }
        )
    return items


# ------------------------------------------------------------ rules and fees


def _approval_events(
    session: Session, target_type: str
) -> dict[str, audit.AuditEvent]:
    """Return the recorded approval event of every version of one kind.

    The events are read once, so the register does not ask the database the
    same question for every row.
    """
    rows = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type == target_type,
            audit.AuditEvent.action.in_(("rule.version.approve", "fee.schedule.approved")),
        )
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id)
    ).scalars().all()
    events: dict[str, audit.AuditEvent] = {}
    for row in rows:
        if row.target_id and row.target_id not in events:
            events[row.target_id] = row
    return events


def _rule_row_view(
    session: Session,
    row: finance.RuleVersion,
    type_labels: dict[str, str],
    *,
    view: str,
    assignment: str,
    approvals: dict[str, audit.AuditEvent],
) -> dict[str, Any]:
    """Return the readable register row of one stored rule version."""
    project_type = type_labels.get(row.permit_type_id or "", "") or "all project types"
    approved_by = "not approved yet"
    approved_on = "not approved yet"
    if row.status in ("approved", "published", "retired"):
        approved_by = _actor_label(session, row.approver_actor_id)
        event = approvals.get(row.id)
        approved_on = (
            _readable_date(event.occurred_at) if event is not None else "not recorded"
        )
        if event is not None and _basis_label(event):
            approved_by += " (the author, single-administrator policy)"
    return {
        "row_id": row.id,
        "kind": "Rule version",
        "version_label": catalog.version_label(row),
        "title": row.title,
        "project_type": project_type,
        "status": row.status,
        "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
        "effective_from": _readable_date(row.effective_from),
        "effective_to": _readable_date(row.effective_to) or "open",
        "effective_period": _readable_window(row.effective_from, row.effective_to),
        "assigned_approver": assignment,
        "approved_by": approved_by,
        "approved_on": approved_on,
        "author": _actor_label(session, row.author_actor_id),
        "citation": row.citation,
        "internal_key": row.id,
        "view": view,
    }


def _fee_row_view(
    session: Session,
    row: finance.FeeScheduleVersion,
    *,
    view: str,
    assignment: str,
    approvals: dict[str, audit.AuditEvent],
) -> dict[str, Any]:
    """Return the readable register row of one stored fee schedule version."""
    approved_by = "not approved yet"
    approved_on = "not approved yet"
    if row.status in ("approved", "published", "retired"):
        approved_by = _actor_label(session, row.approver_actor_id)
        event = approvals.get(row.id)
        approved_on = (
            _readable_date(event.occurred_at) if event is not None else "not recorded"
        )
        if event is not None and _basis_label(event):
            approved_by += " (the author, single-administrator policy)"
    return {
        "row_id": row.id,
        "kind": "Fee schedule version",
        "version_label": f"{row.fee_schedule_id} {row.version_label}",
        "title": "Fee schedule",
        "project_type": "all project types",
        "status": row.status,
        "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
        "effective_from": _readable_date(row.effective_from),
        "effective_to": _readable_date(row.effective_to) or "open",
        "effective_period": _readable_window(row.effective_from, row.effective_to),
        "assigned_approver": assignment,
        "approved_by": approved_by,
        "approved_on": approved_on,
        "author": _actor_label(session, row.author_actor_id),
        "citation": row.currency,
        "internal_key": row.id,
        "view": view,
    }


def _lifecycle_next(
    session: Session,
    actor: ActorContext,
    kind: str,
    row: Any,
) -> dict[str, Any]:
    """Return the next action of one version and why it may not be available.

    The order is the lifecycle order of the service: submit, approve, publish,
    retire.  An author never approves or publishes their own version, and the
    reason says so in plain words.
    """
    is_rule = kind == "rule"
    domain_id = "building_rules" if is_rule else "finance"
    author_id = row.author_actor_id
    is_author = bool(author_id) and author_id == actor.actor_id
    independent = not approval_policy.is_single()
    if is_rule:
        pairs = (
            ("draft", "Submit for review", "rule.submit", "rule.version.draft"),
            ("in_review", "Approve version", "rule.approve", "rule.version.approve"),
            ("approved", "Publish version", "rule.publish", "rule.version.publish"),
            ("published", "Retire version", "rule.retire", "rule.version.publish"),
        )
    else:
        pairs = (
            ("draft", "Submit for review", "fee.submit", "rule.version.draft"),
            ("in_review", "Approve version", "fee.approve", "rule.version.approve"),
            ("approved", "Publish version", "fee.publish", "rule.version.publish"),
            ("published", "Retire version", "fee.retire", "rule.version.publish"),
        )
    for state, label, action_id, permission in pairs:
        if row.status != state:
            continue
        holds = view_models.allows(
            session, actor, permission, domain_id, (row.id,)
        )
        reason = ""
        if not holds:
            reason = (
                f"your persona does not hold the {permission!r} grant for this version; "
                "the responsible steward or the named queue may perform it"
            )
        elif is_author and independent and action_id in ("rule.approve", "fee.approve"):
            reason = "You authored this version; another administrator must approve it."
        elif is_author and independent and action_id in ("rule.publish", "fee.publish"):
            reason = "You authored this version; another administrator must publish it."
        return {
            "label": label,
            "action_id": action_id,
            "available": not reason,
            "reason": reason,
        }
    if row.status == "retired":
        return {
            "label": "No further action",
            "action_id": "",
            "available": False,
            "reason": "The version is retired; its effective period is closed.",
        }
    return {
        "label": "No further action",
        "action_id": "",
        "available": False,
        "reason": "The version is in a state that has no next step.",
    }


def _rule_diff(
    session: Session,
    previous: finance.RuleVersion,
    current: finance.RuleVersion,
    type_labels: dict[str, str],
) -> list[dict[str, str]]:
    """Return the changed fields between two stored rule version records."""
    def snapshot(row: finance.RuleVersion) -> dict[str, str]:
        return {
            "title": row.title or "",
            "citation": row.citation or "",
            "project_type": type_labels.get(row.permit_type_id or "", "") or "all project types",
            "field_path": row.field_path or "",
            "operator": row.operator or "",
            "limit_value": row.limit_value or "",
            "on_violate": row.on_violate or "",
            "condition": _plain(row.condition),
            "message": row.message or "",
            "condition_note": row.condition_note or "",
            "effective_from": _readable_date(row.effective_from),
            "effective_to": _readable_date(row.effective_to) or "open",
        }

    before = snapshot(previous)
    after = snapshot(current)
    return [
        {"field": key, "label": label, "before": before[key], "after": after[key]}
        for key, label in _RULE_DIFF_FIELDS
        if before[key] != after[key]
    ]


def _fee_diff(
    previous: finance.FeeScheduleVersion,
    current: finance.FeeScheduleVersion,
) -> list[dict[str, str]]:
    """Return the changed fields between two stored fee schedule records."""
    def snapshot(row: finance.FeeScheduleVersion) -> dict[str, str]:
        values = {
            "currency": row.currency or "",
            "effective_from": _readable_date(row.effective_from),
            "effective_to": _readable_date(row.effective_to) or "open",
        }
        definition = dict(row.definition or {})
        for key, _label in _FEE_COMPONENT_FIELDS:
            values[key] = _plain(definition.get(key))
        return values

    before = snapshot(previous)
    after = snapshot(current)
    changes = [
        {"field": key, "label": label, "before": before[key], "after": after[key]}
        for key, label in _FEE_DIFF_FIELDS
        if before[key] != after[key]
    ]
    changes += [
        {"field": key, "label": label, "before": before[key], "after": after[key]}
        for key, label in _FEE_COMPONENT_FIELDS
        if before[key] != after[key]
    ]
    return changes


def _plain(value: Any) -> str:
    """Return a stored value as plain text, never as a Python object."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _rule_counterpart(
    session: Session, row: finance.RuleVersion
) -> finance.RuleVersion | None:
    """Return the published version of the same rule, if one is published."""
    rows = session.execute(
        select(finance.RuleVersion).where(
            finance.RuleVersion.rule_id == row.rule_id,
            finance.RuleVersion.status == "published",
            finance.RuleVersion.id != row.id,
        )
    ).scalars().all()
    if not rows:
        return None
    return max(rows, key=lambda item: item.effective_from)


def _rule_predecessor(
    session: Session, row: finance.RuleVersion
) -> finance.RuleVersion | None:
    """Return the stored version before this one of the same rule."""
    rows = session.execute(
        select(finance.RuleVersion).where(
            finance.RuleVersion.rule_id == row.rule_id,
            finance.RuleVersion.id != row.id,
        )
    ).scalars().all()
    current = catalog.business_version(row)
    earlier = [
        item
        for item in rows
        if catalog.business_version(item) < current
    ]
    if not earlier:
        return None
    return max(earlier, key=catalog.business_version)


def _fee_predecessor(
    session: Session, row: finance.FeeScheduleVersion
) -> finance.FeeScheduleVersion | None:
    """Return the stored version before this one of the same fee schedule."""
    rows = session.execute(
        select(finance.FeeScheduleVersion).where(
            finance.FeeScheduleVersion.fee_schedule_id == row.fee_schedule_id,
            finance.FeeScheduleVersion.id != row.id,
        )
    ).scalars().all()
    earlier = [item for item in rows if (item.effective_from or item.created_at) < (
        row.effective_from or row.created_at
    )]
    if not earlier:
        return None
    return max(earlier, key=lambda item: item.effective_from)


def _overlap_warning(
    session: Session, kind: str, row: Any
) -> str:
    """Return the warning for a version whose effective period overlaps another.

    The check reuses the catalogue's own window rule; the service refuses the
    overlapping publication, so the screen says so before the click.
    """
    if kind == "rule":
        conflict = catalog.conflicting_published_version(session, row)
        if conflict is None:
            return ""
        return (
            "Publishing this version would overlap the published version "
            f"{catalog.version_label(conflict)} whose effective period is "
            f"{_readable_window(conflict.effective_from, conflict.effective_to)}. "
            "The service refuses an overlapping publication unless an explicit "
            "precedence is given."
        )
    others = session.execute(
        select(finance.FeeScheduleVersion).where(
            finance.FeeScheduleVersion.fee_schedule_id == row.fee_schedule_id,
            finance.FeeScheduleVersion.status == "published",
            finance.FeeScheduleVersion.id != row.id,
        )
    ).scalars().all()
    for other in others:
        if catalog.windows_overlap(
            row.effective_from,
            row.effective_to,
            other.effective_from,
            other.effective_to,
        ):
            return (
                "Publishing this version would overlap the published version "
                f"{other.fee_schedule_id} {other.version_label} whose effective "
                f"period is {_readable_window(other.effective_from, other.effective_to)}. "
                "The service refuses an overlapping publication unless an explicit "
                "precedence is given."
            )
    return ""


def _lifecycle_history(
    session: Session, target_type: str
) -> list[dict[str, Any]]:
    """Return the recorded lifecycle events of one kind of version.

    The history view is the recorded review, approval and publication trail
    of the catalogue, read from the append-only audit record.
    """
    rows = session.execute(
        select(audit.AuditEvent)
        .where(audit.AuditEvent.target_type == target_type)
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id)
    ).scalars().all()
    entries: list[dict[str, Any]] = []
    for row in rows:
        label = ""
        if target_type == "rule_version":
            stored = session.get(finance.RuleVersion, row.target_id or "")
            label = catalog.version_label(stored) if stored is not None else ""
        else:
            stored = session.get(finance.FeeScheduleVersion, row.target_id or "")
            label = (
                f"{stored.fee_schedule_id} {stored.version_label}"
                if stored is not None
                else ""
            )
        entries.append(
            {
                "occurred_date": _readable_date(row.occurred_at),
                "occurred_at": view_models._iso(row.occurred_at),
                "action": row.action,
                "action_label": ops_views.action_label(row.action),
                "version_id": row.target_id or "",
                "version_label": label or (row.target_id or ""),
                "actor": _actor_label(session, row.actor_id),
                "outcome": row.outcome,
                "reason": row.reason or "",
                "basis": _basis_label(row),
            }
        )
    return entries


def approval_policy_view() -> dict[str, str]:
    """Return the active approval policy for display."""
    key = approval_policy.active_policy()
    return {
        "key": key,
        "label": approval_policy.policy_label(),
        "line": approval_policy.policy_line(),
    }


def rules_register(
    session: Session,
    actor: ActorContext,
    *,
    tab: str = "rules",
    view: str = "published",
    version_id: str | None = None,
) -> dict[str, Any]:
    """Return the rules and fees screen.

    The register has two tabs — rules and fee schedules — and three views of
    each: published, drafts and history.  The selected version shows the
    diffed records, the applicability, the recorded history and the next
    authorized action.
    """
    tab = tab if tab in dict(RULE_TABS) else "rules"
    view = view if view in dict(REGISTER_VIEWS) else "published"
    type_labels = _permit_type_labels(session)
    rule_assignment = _assigned_approver(session, "building_rules")
    fee_assignment = _assigned_approver(session, "finance")
    rule_approvals = _approval_events(session, "rule_version")
    fee_approvals = _approval_events(session, "fee_schedule_version")

    rule_rows = [
        _rule_row_view(
            session,
            row,
            type_labels,
            view=view,
            assignment=rule_assignment,
            approvals=rule_approvals,
        )
        for row in session.execute(
            select(finance.RuleVersion).order_by(
                finance.RuleVersion.rule_id, finance.RuleVersion.effective_from
            )
        ).scalars().all()
    ]
    fee_rows = [
        _fee_row_view(
            session,
            row,
            view=view,
            assignment=fee_assignment,
            approvals=fee_approvals,
        )
        for row in session.execute(
            select(finance.FeeScheduleVersion).order_by(
                finance.FeeScheduleVersion.fee_schedule_id,
                finance.FeeScheduleVersion.effective_from,
            )
        ).scalars().all()
    ]

    if view == "published":
        rules = [row for row in rule_rows if row["status"] == "published"]
        fees = [row for row in fee_rows if row["status"] == "published"]
    elif view == "drafts":
        rules = [
            row for row in rule_rows if row["status"] in ("draft", "in_review", "approved")
        ]
        fees = [
            row for row in fee_rows if row["status"] in ("draft", "in_review", "approved")
        ]
    else:
        rules = [row for row in rule_rows if row["status"] == "retired"]
        fees = [row for row in fee_rows if row["status"] == "retired"]

    history = (
        _lifecycle_history(
            session, "rule_version" if tab == "rules" else "fee_schedule_version"
        )
        if view == "history"
        else []
    )

    rows = rules if tab == "rules" else fees
    for row in rows:
        source_row = _version_row(session, tab, row["row_id"])
        next_action = _lifecycle_next(session, actor, tab, source_row) if source_row else {
            "label": "No further action",
            "action_id": "",
            "available": False,
            "reason": "The version is not stored.",
        }
        row["next_action"] = next_action
        row["href"] = (
            f"/rules?tab={tab}&view={view}&version={row['row_id']}"
        )

    # Drafts made from a what-if run (policy conversion) link back to the run.
    # They are listed on every view so the origin of a draft stays one click
    # away, whichever register is open.
    from acme_city.policy.drafts import PolicyDraftService  # noqa: PLC0415

    run_links = PolicyDraftService(session).links(actor)
    policy_drafts: list[dict[str, Any]] = []
    for kind, all_rows in (("rule", rule_rows), ("fee", fee_rows)):
        for row in all_rows:
            run_id = run_links.get(row["row_id"])
            if run_id:
                policy_drafts.append(
                    {
                        "kind": kind,
                        "title": row["title"],
                        "version": row["version_label"],
                        "status": row["status"],
                        "href": f"/policy/runs/{run_id}#draft",
                        "register_href": f"/rules?tab={'rules' if kind == 'rule' else 'fees'}&view=drafts&version={row['row_id']}",
                    }
                )

    selected = _selected_version(session, actor, tab, version_id, type_labels)
    actions: list[dict[str, Any]] = []
    if selected is not None:
        selected["view"] = view
        actions = _version_actions(session, actor, tab, selected)

    return {
        "tab": tab,
        "view": view,
        "tabs": [
            {"key": key, "label": label, "href": f"/rules?tab={key}&view={view}"}
            for key, label in RULE_TABS
        ],
        "views": [
            {"key": key, "label": label, "href": f"/rules?tab={tab}&view={key}"}
            for key, label in REGISTER_VIEWS
        ],
        "rows": rows,
        "history": history,
        "row_count_label": (
            f"{len(history)} recorded lifecycle event(s) · synthetic ACME values"
            if view == "history"
            else f"{len(rows)} stored version(s) in this view · synthetic ACME values"
        ),
        "date_column_label": (
            "Proposed effective date" if view == "drafts" else "Effective period"
        ),
        "policy_drafts": policy_drafts,
        "approval_policy": approval_policy_view(),
        "selected": selected,
        "actions": actions,
        "denied_action_explanations": view_models.denied_action_explanations(actions),
        "responsibility": view_models.responsibility(
            session,
            domain_id="building_rules" if tab == "rules" else "finance",
            source_system_id="permitting" if tab == "rules" else "erp_finance",
            dataset_key="approved_rules_register" if tab == "rules" else "finance_accounts",
        ),
        "draft_action": _draft_action(session, actor, tab),
    }


def _version_row(session: Session, tab: str, row_id: str) -> Any:
    """Return the stored row of one version, or ``None``."""
    if tab == "rules":
        return session.get(finance.RuleVersion, row_id)
    return session.get(finance.FeeScheduleVersion, row_id)


def _selected_version(
    session: Session,
    actor: ActorContext,
    tab: str,
    version_id: str | None,
    type_labels: dict[str, str],
) -> dict[str, Any] | None:
    """Return the selected version with its diff, applicability and history."""
    if not version_id:
        return None
    if tab == "rules":
        row = session.get(finance.RuleVersion, version_id)
        if row is None:
            return None
        return _selected_rule(session, actor, row, type_labels)
    row = session.get(finance.FeeScheduleVersion, version_id)
    if row is None:
        return None
    return _selected_fee(session, actor, row)


def _selected_rule(
    session: Session,
    actor: ActorContext,
    row: finance.RuleVersion,
    type_labels: dict[str, str],
) -> dict[str, Any]:
    """Return the selected rule version with everything the brief asks for."""
    previous = _rule_predecessor(session, row)
    published = _rule_counterpart(session, row)
    diff = _rule_diff(session, previous, row, type_labels) if previous else []
    if not previous:
        diff = []
    project_type = type_labels.get(row.permit_type_id or "", "") or "all project types"
    applicable = _applications_in_window(
        session, row.permit_type_id, row.effective_from, row.effective_to
    )
    history = _version_history(session, "rule_version", row.id)
    approval_event = _approval_record(session, "rule_version", row.id)
    next_action = _lifecycle_next(session, actor, "rule", row)
    published_side = None
    proposed_side = None
    if published is not None:
        published_side = {
            "label": catalog.version_label(published),
            "status_label": VERSION_STATUS_LABELS.get(published.status, published.status),
            "effective_period": _readable_window(
                published.effective_from, published.effective_to
            ),
            "limit": published.limit_value or "",
        }
    if row.status != "published":
        proposed_side = {
            "label": catalog.version_label(row),
            "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
            "effective_period": _readable_window(row.effective_from, row.effective_to),
            "limit": row.limit_value or "",
        }
    return {
        "kind": "rule",
        "row_id": row.id,
        "version_label": catalog.version_label(row),
        "title": row.title,
        "project_type": project_type,
        "status": row.status,
        "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
        "citation": row.citation,
        "internal_key": row.id,
        "assigned_approver": _assigned_approver(session, "building_rules"),
        "approved_by": (
            _actor_label(session, row.approver_actor_id)
            + (
                " (the author, single-administrator policy)"
                if _basis_label(approval_event)
                else ""
            )
            if row.status in ("approved", "published", "retired")
            else "not approved yet"
        ),
        "approved_on": (
            _readable_date(approval_event.occurred_at)
            if approval_event is not None
            else ("not recorded" if row.status in ("approved", "published", "retired") else "not approved yet")
        ),
        "author": _actor_label(session, row.author_actor_id),
        "states": {
            "draft": (
                "The version is a draft. It has not entered the approval workflow."
                if row.status == "draft"
                else f"The version was a draft and is now {VERSION_STATUS_LABELS.get(row.status, row.status)}."
            ),
            "approval": (
                "No approval is recorded for this version."
                if approval_event is None
                else _approval_text(session, approval_event)
            ),
            "publication": (
                "The version is not published."
                if row.status != "published"
                else "The version is published and in force for its effective period."
            ),
            "effective_period": _readable_window(row.effective_from, row.effective_to),
            "applicability": (
                f"Applies to {project_type}. The version is selected on "
                f"{DATE_BASIS_TEXT}; a later revision does not switch the schedule."
            ),
        },
        "published_side": published_side,
        "proposed_side": proposed_side,
        "diff": diff,
        "diff_note": (
            ""
            if diff
            else "The stored version records hold no differing content to compare."
        ),
        "compared_with": (
            f"{catalog.version_label(previous)}" if previous is not None else ""
        ),
        "comparison": {
            "diff_baseline": catalog.version_label(previous) if previous is not None else "No predecessor",
            "published_baseline": published_side["label"] if published_side else "No published counterpart",
        },
        "reason": (
            (approval_event.reason or "")
            if approval_event is not None and approval_event.reason
            else (
                history[0]["reason"]
                if history and history[0]["reason"]
                else "No reason is recorded with the seeded version record."
            )
        ),
        "supporting": [
            {"label": "Citation", "value": row.citation or "not recorded"},
            {"label": "Rule text on record", "value": row.title or "not recorded"},
        ],
        "history": history,
        "applicability": {
            "basis_label": DEFAULT_DATE_BASIS,
            "basis_text": (
                "The version is chosen on the initial submission time of the "
                "application. A later revision does not switch the schedule, and "
                "publishing a new version never changes a past decision or "
                "assessment."
            ),
            "applications": applicable,
            "note": (
                f"{len(applicable)} sample application(s) fall inside the effective "
                "period of this version."
                if applicable
                else "No sample application has an initial submission time inside "
                "this effective period. An application first submitted from the "
                "start of the period would use this version."
            ),
        },
        "overlap_warning": _overlap_warning(session, "rule", row),
        "next_action": next_action,
    }


def _selected_fee(
    session: Session,
    actor: ActorContext,
    row: finance.FeeScheduleVersion,
) -> dict[str, Any]:
    """Return the selected fee schedule version with everything the brief asks for."""
    previous = _fee_predecessor(session, row)
    diff = _fee_diff(previous, row) if previous else []
    published = [
        item
        for item in session.execute(
            select(finance.FeeScheduleVersion).where(
                finance.FeeScheduleVersion.fee_schedule_id == row.fee_schedule_id,
                finance.FeeScheduleVersion.status == "published",
                finance.FeeScheduleVersion.id != row.id,
            )
        ).scalars().all()
    ]
    published_row = max(published, key=lambda item: item.effective_from) if published else None
    applicable = _applications_in_window(
        session, None, row.effective_from, row.effective_to
    )
    history = _version_history(session, "fee_schedule_version", row.id)
    approval_event = _approval_record(session, "fee_schedule_version", row.id)
    next_action = _lifecycle_next(session, actor, "fee", row)
    published_side = None
    proposed_side = None
    if published_row is not None:
        published_side = {
            "label": f"{published_row.fee_schedule_id} {published_row.version_label}",
            "status_label": VERSION_STATUS_LABELS.get(
                published_row.status, published_row.status
            ),
            "effective_period": _readable_window(
                published_row.effective_from, published_row.effective_to
            ),
            "limit": str((published_row.definition or {}).get("formula", "")),
        }
    if row.status != "published":
        proposed_side = {
            "label": f"{row.fee_schedule_id} {row.version_label}",
            "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
            "effective_period": _readable_window(row.effective_from, row.effective_to),
            "limit": str((row.definition or {}).get("formula", "")),
        }
    return {
        "kind": "fee",
        "row_id": row.id,
        "version_label": f"{row.fee_schedule_id} {row.version_label}",
        "title": "Fee schedule",
        "project_type": "all project types",
        "status": row.status,
        "status_label": VERSION_STATUS_LABELS.get(row.status, row.status),
        "citation": row.currency,
        "internal_key": row.id,
        "assigned_approver": _assigned_approver(session, "finance"),
        "approved_by": (
            _actor_label(session, row.approver_actor_id)
            + (
                " (the author, single-administrator policy)"
                if _basis_label(approval_event)
                else ""
            )
            if row.status in ("approved", "published", "retired")
            else "not approved yet"
        ),
        "approved_on": (
            _readable_date(approval_event.occurred_at)
            if approval_event is not None
            else ("not recorded" if row.status in ("approved", "published", "retired") else "not approved yet")
        ),
        "author": _actor_label(session, row.author_actor_id),
        "states": {
            "draft": (
                "The version is a draft. It has not entered the approval workflow."
                if row.status == "draft"
                else f"The version was a draft and is now {VERSION_STATUS_LABELS.get(row.status, row.status)}."
            ),
            "approval": (
                "No approval is recorded for this version."
                if approval_event is None
                else _approval_text(session, approval_event)
            ),
            "publication": (
                "The version is not published."
                if row.status != "published"
                else "The version is published and in force for its effective period."
            ),
            "effective_period": _readable_window(row.effective_from, row.effective_to),
            "applicability": (
                "Applies to every project type the schedule prices. The version is "
                f"selected on {DATE_BASIS_TEXT}; a later revision does not switch "
                "the schedule."
            ),
        },
        "published_side": published_side,
        "proposed_side": proposed_side,
        "diff": diff,
        "diff_note": (
            ""
            if diff
            else "The stored version records hold no differing content to compare."
        ),
        "compared_with": (
            f"{previous.fee_schedule_id} {previous.version_label}"
            if previous is not None
            else ""
        ),
        "comparison": {
            "diff_baseline": (f"{previous.fee_schedule_id} {previous.version_label}" if previous is not None else "No predecessor"),
            "published_baseline": published_side["label"] if published_side else "No published counterpart",
        },
        "reason": (
            (approval_event.reason or "")
            if approval_event is not None and approval_event.reason
            else (
                history[0]["reason"]
                if history and history[0]["reason"]
                else "No reason is recorded with the seeded version record."
            )
        ),
        "supporting": [
            {"label": "Currency", "value": row.currency or "not recorded"},
            {
                "label": "Classification on record",
                "value": str((row.definition or {}).get("classification", "not recorded")),
            },
        ],
        "history": history,
        "applicability": {
            "basis_label": DEFAULT_DATE_BASIS,
            "basis_text": (
                "The schedule is chosen on the initial submission time of the "
                "application. A later revision does not switch the schedule, and "
                "publishing a new schedule never changes a past decision or "
                "assessment."
            ),
            "applications": applicable,
            "note": (
                f"{len(applicable)} sample application(s) fall inside the effective "
                "period of this version."
                if applicable
                else "No sample application has an initial submission time inside "
                "this effective period. An application first submitted from the "
                "start of the period would use this version."
            ),
        },
        "overlap_warning": _overlap_warning(session, "fee", row),
        "next_action": next_action,
    }


def _version_actions(
    session: Session, actor: ActorContext, tab: str, selected: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the actions of the selected version, in the order of the lifecycle."""
    kind = selected["kind"]
    row_id = selected["row_id"]
    domain_id = "building_rules" if kind == "rule" else "finance"
    is_rule = kind == "rule"
    version_field = "rule_version_id" if is_rule else "fee_schedule_version_id"
    actions: list[dict[str, Any]] = []

    if is_rule:
        row = session.get(finance.RuleVersion, row_id)
        edit = build_action(
            session,
            actor,
            action_id="rule.draft",
            label="Edit draft",
            path="/ui/actions/rule.draft",
            permission="rule.version.draft",
            domain_id=domain_id,
            record_ids=(row_id,),
            destination="Approved rules register",
            description=(
                "Draft a new version from this one. A drafted version is never "
                "changed in place, so a change is recorded as a new version."
            ),
            state_allowed=(row is not None and row.status == "draft"),
            state_reason=(
                "Only a draft may be edited, and a change is recorded as a new version."
                if row is not None
                else "The version is not stored."
            ),
            fields=(
                _field("rule_id", "Rule", value=row.rule_id if row else "", required=True),
                _field(
                    "permit_type_key",
                    "Permit type",
                    value="com_ti",
                    required=True,
                ),
                _field("title", "Title", value=row.title if row else "", required=True),
                _field(
                    "citation", "Citation", value=row.citation if row else "", required=True
                ),
                _field("field_path", "Field path", value=row.field_path if row else ""),
                _field(
                    "operator",
                    "Operator",
                    field_type="select",
                    options=("", "min", "max", "equals"),
                    value=(row.operator if row and row.operator else ""),
                ),
                _field("limit_value", "Limit", value=row.limit_value if row else ""),
                _field("on_violate", "On violation", value=row.on_violate if row else ""),
                _field("message", "Message", value=row.message if row else ""),
                _field(
                    "effective_from",
                    "Effective from",
                    value=(
                        view_models._iso(row.effective_from)
                        if row and row.effective_from
                        else ""
                    ),
                    required=True,
                ),
                _field("reason", "Reason", field_type="textarea", required=True),
            ),
        )
        edit["dom_id"] = f"rule-draft-{row_id}"
        actions.append(edit)
    else:
        row = session.get(finance.FeeScheduleVersion, row_id)
        edit = build_action(
            session,
            actor,
            action_id="fee.draft",
            label="Edit draft",
            path="/ui/actions/fee.draft",
            permission="rule.version.draft",
            domain_id=domain_id,
            record_ids=(row_id,),
            destination="Approved fee register",
            description=(
                "Draft a new schedule version from this one. A drafted version is "
                "never changed in place, so a change is recorded as a new version."
            ),
            state_allowed=(row is not None and row.status == "draft"),
            state_reason=(
                "Only a draft may be edited, and a change is recorded as a new version."
                if row is not None
                else "The version is not stored."
            ),
            fields=(
                _field(
                    "fee_schedule_id",
                    "Fee schedule",
                    value=row.fee_schedule_id if row else "",
                    required=True,
                ),
                _field(
                    "version_label",
                    "Version label",
                    value=row.version_label if row else "",
                    required=True,
                ),
                _field(
                    "effective_from",
                    "Effective from",
                    value=(
                        view_models._iso(row.effective_from)
                        if row and row.effective_from
                        else ""
                    ),
                    required=True,
                ),
                _field("currency", "Currency", value=row.currency if row else "USD", required=True),
                _field(
                    "definition",
                    "Definition (JSON)",
                    field_type="textarea",
                    value=_plain(row.definition) if row else "",
                    required=True,
                ),
                _field("reason", "Reason", field_type="textarea", required=True),
            ),
        )
        edit["dom_id"] = f"fee-draft-{row_id}"
        actions.append(edit)

    compare = build_action(
        session,
        actor,
        action_id="rule.compare",
        label="Compare versions",
        path=f"/rules?tab={tab}",
        permission="rule.version.draft",
        domain_id=domain_id,
        record_ids=(row_id,),
        destination="no external destination",
        description=(
            "Compare the selected version with the version before it. The "
            "comparison reads the two stored version records; it writes nothing."
        ),
        fields=(),
        method="get",
    )
    compare["dom_id"] = f"compare-{row_id}"
    compare["href"] = (
        f"/rules?tab={tab}&view={selected.get('view', 'published')}"
        f"&version={row_id}#version-diff"
    )
    compare["is_link"] = True

    if is_rule:
        lifecycle = (
            ("rule.submit", "Submit for review", "rule.version.draft", "draft"),
            ("rule.approve", "Approve version", "rule.version.approve", "in_review"),
            ("rule.publish", "Publish version", "rule.version.publish", "approved"),
            ("rule.retire", "Retire version", "rule.version.publish", "published"),
        )
    else:
        lifecycle = (
            ("fee.submit", "Submit for review", "rule.version.draft", "draft"),
            ("fee.approve", "Approve version", "rule.version.approve", "in_review"),
            ("fee.publish", "Publish version", "rule.version.publish", "approved"),
            ("fee.retire", "Retire version", "rule.version.publish", "published"),
        )
    row = _version_row(session, tab, row_id)
    author_id = getattr(row, "author_actor_id", None) if row is not None else None
    is_author = bool(author_id) and author_id == actor.actor_id
    independent = not approval_policy.is_single()
    prepared: list[dict[str, Any]] = []
    for action_id, label, permission, state in lifecycle:
        state_allowed = row is not None and row.status == state
        state_reason = ""
        if not state_allowed:
            state_reason = (
                f"This step applies to a version in status {state.replace('_', ' ')}; "
                f"this version is {row.status.replace('_', ' ')}."
                if row is not None
                else "The version is not stored."
            )
        elif is_author and independent and action_id in ("rule.approve", "fee.approve"):
            state_reason = (
                "You authored this version; another administrator must approve it."
            )
            state_allowed = False
        elif is_author and independent and action_id in ("rule.publish", "fee.publish"):
            state_reason = (
                "You authored this version; another administrator must publish it."
            )
            state_allowed = False
        item = build_action(
            session,
            actor,
            action_id=action_id,
            label=label,
            path=f"/ui/actions/{action_id}",
            permission=permission,
            domain_id=domain_id,
            record_ids=(row_id,),
            destination=(
                "Approved rules register" if is_rule else "Approved fee register"
            ),
            description=(
                f"{label}. An author may never approve or publish their own version."
                if independent
                else (
                    f"{label}. Under the single-administrator policy the author may approve "
                    "and publish their own version. Approving it needs a confirmation "
                    "and a reason, which are recorded."
                    if is_author and action_id in ("rule.approve", "fee.approve")
                    else f"{label}."
                )
            ),
            expected_version=row.version if row is not None else None,
            state_allowed=state_allowed,
            state_reason=state_reason,
            fields=(
                _field(version_field, "Version", value=row_id, field_type="hidden"),
                _field(
                    "expected_version",
                    "Expected version",
                    field_type="number",
                    value=str(row.version) if row is not None else "",
                    required=True,
                ),
                _field("reason", "Reason", field_type="textarea", required=True),
                *(
                    (
                        _field(
                            "confirm_author_approval",
                            "I wrote this version and I am approving it under the "
                            "single-administrator policy",
                            field_type="checkbox",
                            required=True,
                        ),
                    )
                    if is_author and not independent and action_id in ("rule.approve", "fee.approve")
                    else ()
                ),
                _field("precedence", "Precedence"),
            ),
        )
        item["dom_id"] = f"{action_id}-{row_id}"
        prepared.append(item)
    # The actions sit with the selected version in the order of the lifecycle:
    # edit the draft, submit it for review, compare it with the version before
    # it, approve it, publish it, retire it.
    ordered: list[dict[str, Any]] = list(actions)
    for item in prepared:
        ordered.append(item)
        if item["action_id"] in ("rule.submit", "fee.submit"):
            ordered.append(compare)
    return ordered


def _draft_action(
    session: Session, actor: ActorContext, tab: str
) -> dict[str, Any] | None:
    """Return the action that drafts a new version of the selected register."""
    if tab == "rules":
        return build_action(
            session,
            actor,
            action_id="rule.draft",
            label="Draft a new rule version",
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
                _field(
                    "operator",
                    "Operator",
                    field_type="select",
                    options=("", "min", "max", "equals"),
                ),
                _field("limit_value", "Limit"),
                _field("on_violate", "On violation"),
                _field("message", "Message"),
                _field("effective_from", "Effective from", required=True),
                _field("reason", "Reason", field_type="textarea", required=True),
            ),
        )
    return build_action(
        session,
        actor,
        action_id="fee.draft",
        label="Draft a new fee schedule version",
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


# -------------------------------------------------------- governance screen


def _policy_status_label(status: str | None) -> str:
    """Return the readable state of one authority policy.

    The stored state carries a note after a semicolon, so the note is kept
    and the state itself is read as a word.
    """
    head, _, note = str(status or "").partition(";")
    label = ops_views.display_word("values", head.strip(), "Proposed")
    if note.strip():
        return f"{label}. {note.strip()[:1].upper()}{note.strip()[1:]}."
    return label


def governance_screen(
    session: Session, actor: ActorContext, *, tab: str = "sources"
) -> dict[str, Any]:
    """Return the governance and sources screen.

    The screen opens with the sources; the tabs below it hold the
    responsibilities, the authority rules, the access map and the history.
    """
    from acme_city.ui import admin_b_labels  # lane-owned labels

    tab = tab if tab in dict(_GOVERNANCE_TABS) else "sources"
    service = GovernanceService(session)
    sources = _source_overview(session)
    source_labels = {item["source_system_id"]: item["label"] for item in sources}
    registrations = []
    for view in service.list_registrations():
        item = view.model_dump(mode="json")
        item["dataset_label"] = admin_b_labels.identifier_label(item["dataset_key"])
        item["source_label"] = source_labels.get(
            item["source_system_id"], admin_b_labels.identifier_label(item["source_system_id"])
        )
        item["domain_label"] = admin_b_labels.identifier_label(item.get("domain_id"), missing="No domain assigned")
        item["owner_label"] = (
            _actor_label(session, item.get("accountable_owner_actor_id"))
            if item.get("accountable_owner_actor_id") else "No owner assigned"
        )
        item["queue_label"] = admin_b_labels.identifier_label(item.get("steward_queue_id"), missing="No queue assigned")
        item["custodian_label"] = (
            _actor_label(session, item.get("system_custodian_actor_id"))
            if item.get("system_custodian_actor_id") else "No custodian assigned"
        )
        registrations.append(item)
    domains = [
        {
            "domain_id": row.domain_id,
            "label": row.label,
            "accountable_owner_actor_id": row.accountable_owner_actor_id,
            "accountable_owner": _actor_label(session, row.accountable_owner_actor_id),
            "steward_queue_id": row.steward_queue_id,
            "system_custodian_actor_id": row.system_custodian_actor_id,
            "system_custodian": _actor_label(session, row.system_custodian_actor_id),
            "default_source_system_id": row.default_source_system_id,
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
            "primary": _actor_label(session, row.primary_actor_id),
            "delegate_actor_id": row.delegate_actor_id,
            "delegate": _actor_label(session, row.delegate_actor_id),
            "escalation_actor_id": row.escalation_actor_id,
            "escalation": _actor_label(session, row.escalation_actor_id),
            "first_review_target_quantity": row.first_review_target_quantity,
            "first_review_target_unit": row.first_review_target_unit,
            "service_promise": row.service_promise,
            "version": row.version,
        }
        for row in session.execute(
            select(governance.StewardQueue).order_by(governance.StewardQueue.queue_id)
        ).scalars().all()
    ]
    queue_labels = {row["queue_id"]: row["label"] for row in queues}
    for domain in domains:
        domain["domain_label"] = domain["label"] or admin_b_labels.identifier_label(
            domain["domain_id"]
        )
        domain["queue_label"] = queue_labels.get(
            domain["steward_queue_id"] or "", "Not assigned"
        )
        domain["source_label"] = source_labels.get(
            domain["default_source_system_id"] or "", "Not declared"
        )
    domain_labels = {row["domain_id"]: row["domain_label"] for row in domains}
    assignments = [
        view.model_dump(mode="json") for view in service.current_assignments()
    ]
    for assignment in assignments:
        assignment["actor_label"] = (
            _actor_label(session, assignment.get("actor_id"))
            if assignment.get("actor_id") else "Not assigned"
        )
        assignment["queue_label"] = (
            queue_labels.get(str(assignment.get("queue_id") or ""), "Not assigned")
        )
        assignment["subject_label"] = domain_labels.get(
            str(assignment.get("subject_id") or ""),
            admin_b_labels.identifier_label(str(assignment.get("subject_id") or "")),
        )
        assignment["responsibility_label"] = ops_views.display_word(
            "values", assignment.get("responsibility")
        )
    policies = [
        {
            "policy_id": row.policy_id,
            "policy_label": admin_b_labels.identifier_label(row.policy_id),
            "field_group": row.field_group,
            "domain_id": row.domain_id,
            "domain_label": admin_b_labels.identifier_label(
                row.domain_id, missing="All domains"
            ),
            "authoritative_source_system_id": row.authoritative_source_system_id,
            "source_label": source_labels.get(
                row.authoritative_source_system_id or "", "Not declared"
            ),
            "authoritative_dataset_key": row.authoritative_dataset_key,
            "change_destination": row.change_destination,
            "user_action": row.user_action,
            "requires_source_ack": row.requires_source_ack,
            "decision_relevant": row.decision_relevant,
            "status": row.status,
            "status_label": _policy_status_label(row.status),
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
            "ingested_at": view_models._iso(row.ingested_at),
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
            "source_label": source_labels.get(row.source_system_id, "Not declared"),
            "operation": row.operation,
            "operation_label": ops_views.display_word(
                "values", row.operation, "Sent to the source"
            ),
            "status": row.status,
            "status_label": ops_views.display_word("values", row.status),
            "accepted_source_version": row.accepted_source_version,
        }
        for row in session.execute(
            select(change.SourceCommand).order_by(change.SourceCommand.id)
        ).scalars().all()
    ]
    subscriber_rows = property_views.subscribers_for(session, None)

    history = _governance_history(session)
    access = _access_map(session)
    for entry in access:
        entry["permission_rows"] = [
            {"id": permission_id, "label": admin_b_labels.permission_label(permission_id)}
            for permission_id in entry["permissions"]
        ]

    return {
        "tab": tab,
        "tabs": [
            {"key": key, "label": label, "href": f"/governance?tab={key}"}
            for key, label in _GOVERNANCE_TABS
        ],
        "sources": sources,
        "attention": {"staged_records": len(staged), "quarantine_errors": len(quarantined)},
        "registrations": registrations,
        "domains": domains,
        "queues": queues,
        "assignments": assignments,
        "policies": policies,
        "staged": staged,
        "quarantined": quarantined,
        "commands": commands,
        "history": history,
        "access": access,
        "published_datasets": [
            {
                "dataset_key": "property_master",
                "label": "Property master (parcel, address, owner, zoning)",
                "owner": "Planning and Development Services (simulated GIS parcel register)",
                "subscribers": subscriber_rows,
                "notice": property_views.DEPARTMENT_NOTICE,
            }
        ],
        "responsibility": view_models.responsibility(
            session,
            domain_id="records",
            source_system_id="permitting",
            dataset_key="applications_and_permits",
        ),
    }


_GOVERNANCE_TABS: tuple[tuple[str, str], ...] = (
    ("sources", "Sources"),
    ("responsibilities", "Responsibilities"),
    ("authority", "Authority rules"),
    ("access", "Access"),
    ("history", "History"),
)


def _source_overview(session: Session) -> list[dict[str, Any]]:
    """Return the three source systems with their records and freshness.

    Freshness is the last time the source reported a change and the last time
    the demonstration received or checked a record.  It is not the number of
    open issues.
    """
    items: list[dict[str, Any]] = []
    for source_system_id, label, records in _OVERVIEW_SOURCES:
        last_change, last_received = view_models.source_times(session, source_system_id)
        open_count = len(view_models.open_issues(session, (source_system_id,)))
        responsible = _responsible_team(session, source_system_id)
        items.append(
            {
                "source_system_id": source_system_id,
                "label": label,
                "records": records,
                "record_count": _source_record_count(session, source_system_id),
                "last_changed": _readable_date(last_change),
                "last_changed_iso": view_models._iso(last_change),
                "last_received": _readable_date(last_received),
                "last_received_iso": view_models._iso(last_received),
                "freshness_known": last_change is not None or last_received is not None,
                "open_issues": open_count,
                "responsible_team": responsible,
                "correction_path": view_models.correction_destination(
                    session, _source_domain(session, source_system_id), source_system_id
                ),
                "detail_href": f"/governance?tab=sources&source={source_system_id}",
            }
        )
    return items


def _source_domain(session: Session, source_system_id: str) -> str:
    """Return the domain a source system feeds."""
    row = session.execute(
        select(governance.Domain).where(
            governance.Domain.default_source_system_id == source_system_id
        )
    ).scalars().first()
    return row.domain_id if row is not None else "records"


def _source_record_count(session: Session, source_system_id: str) -> int:
    """Return the number of stored records that came from one source."""
    return len(
        session.execute(
            select(source.SourceSnapshot).where(
                source.SourceSnapshot.source_system_id == source_system_id
            )
        ).scalars().all()
    )


def _responsible_team(session: Session, source_system_id: str) -> str:
    """Return the team that resolves the problems of one source."""
    domain_id = _source_domain(session, source_system_id)
    domain = session.execute(
        select(governance.Domain).where(governance.Domain.domain_id == domain_id)
    ).scalar_one_or_none()
    if domain is None:
        return "not assigned"
    steward = session.execute(
        select(governance.StewardQueue).where(
            governance.StewardQueue.queue_id == domain.steward_queue_id
        )
    ).scalar_one_or_none()
    if steward is None:
        return "not assigned"
    return f"{steward.label} ({_actor_label(session, steward.primary_actor_id)})"


def _governance_history(session: Session) -> list[dict[str, Any]]:
    """Return the recorded governance history, newest first."""
    rows = session.execute(
        select(audit.AuditEvent)
        .where(audit.AuditEvent.action.like("governance.%"))
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id)
    ).scalars().all()
    return [
        {
            "action": row.action,
            "action_label": ops_views.action_label(row.action),
            "occurred_at": view_models._iso(row.occurred_at),
            "occurred_date": _readable_date(row.occurred_at),
            "actor": _actor_label(session, row.actor_id),
            "outcome": row.outcome,
            "reason": row.reason or "",
            "target_type": row.target_type or "",
            "target_id": row.target_id or "",
        }
        for row in rows
    ]


def _access_map(session: Session) -> list[dict[str, Any]]:
    """Return the persona access map: who holds which permission.

    The map is read from the persisted grants, so it is the same authority
    the server uses to decide.
    """
    from acme_city.auth.permissions import PermissionResolver

    resolver = PermissionResolver(session)
    rows = session.execute(
        select(governance.Actor).where(
            governance.Actor.selectable.is_(True)
        ).order_by(governance.Actor.actor_id)
    ).scalars().all()
    entries: list[dict[str, Any]] = []
    for row in rows:
        permissions = sorted(resolver.permissions_for(row.actor_id))
        entries.append(
            {
                "actor_id": row.actor_id,
                "label": row.label,
                "selectable": bool(row.selectable),
                "permissions": permissions,
                "count": len(permissions),
            }
        )
    return entries


# ------------------------------------------------------- reconciliation screen


def reconciliation_screen(
    session: Session,
    actor: ActorContext,
    *,
    tab: str = "assessments",
    assessment_id: str | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Return the reconciliation screen.

    The screen has three scopes: every assessment, the receipt register and
    the account identity links.  The selected assessment shows its amount,
    the receipts that apply to it, its allocations, its balance and its
    history; the receipt register is a register of its own.
    """
    tab = tab if tab in dict(_RECONCILIATION_TABS) else "assessments"
    service = FinanceService(session)
    assessments: list[dict[str, Any]] = []
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

    reference_by_application = {
        row.id: row.source_application_number
        for row in session.execute(select(permit.Application)).scalars().all()
    }
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
            "link_status_label": ops_views.link_status_label(row.link_status),
            "party_id": row.party_id,
            "party": _actor_label(session, row.party_id),
            "version": row.version,
        }
        for row in session.execute(
            select(registry.FinanceAccount).order_by(registry.FinanceAccount.account_id)
        ).scalars().all()
    ]
    for allocation in allocations:
        allocation["status_label"] = ops_views.display_word(
            "values", allocation.get("status")
        )

    assessment_by_id = {row["assessment_id"]: row for row in assessments}
    allocation_by_payment: dict[str, list[str]] = {}
    for allocation in allocations:
        allocation_by_payment.setdefault(allocation["payment_id"], []).append(
            allocation["assessment_id"]
        )

    rows: list[dict[str, Any]] = []
    for row in assessments:
        reference = reference_by_application.get(row["application_id"], "")
        rows.append(
            {
                "assessment_id": row["assessment_id"],
                "application_id": row["application_id"],
                "reference": reference or "not recorded",
                "version": row["version"],
                "fee_assessed": f"{row['assessed_total']} {row['currency']}",
                "payment_applied": (
                    f"{row['position']['settled_allocated']} {row['currency']}"
                ),
                "balance": f"{row['position']['balance']} {row['currency']}",
                "finance_status": row["position"]["status"],
                "finance_status_label": ops_views.display_word(
                    "values", row["position"]["status"]
                ),
                "exception": row["position"]["exception"] or "",
                "status_detail": _finance_status_detail(row),
                "href": f"/reconciliation?tab=assessments&assessment={row['assessment_id']}",
            }
        )
    if query:
        needle = query.strip().lower()
        rows = [
            row
            for row in rows
            if needle in row["reference"].lower()
            or needle in row["assessment_id"].lower()
        ]

    receipt_rows: list[dict[str, Any]] = []
    for payment in payments:
        linked = allocation_by_payment.get(payment["payment_id"], [])
        receipt_rows.append(
            {
                "payment_id": payment["payment_id"],
                "transaction": payment["source_transaction_id"],
                "amount": payment["amount"],
                "currency": payment["currency"],
                "settlement_status": payment["settlement_status"],
                "settlement_status_label": ops_views.display_word(
                    "values", payment["settlement_status"]
                ),
                "allocation_status": (
                    ", ".join(
                        sorted(
                            {
                                allocation["status"]
                                for allocation in allocations
                                if allocation["payment_id"] == payment["payment_id"]
                            }
                        )
                    )
                    or "not allocated"
                ),
                "linked_assessment": (
                    ", ".join(
                        sorted(
                            {
                                reference_by_application.get(
                                    assessment_by_id.get(item, {}).get("application_id", ""),
                                    "",
                                )
                                or item
                                for item in linked
                            }
                        )
                    )
                    or "no assessment"
                ),
                "payer_account_id": payment["payer_account_id"] or "",
                "account_link_status": _account_link_status(
                    session, payment["payer_account_id"]
                ),
                "account_link_status_label": ops_views.link_status_label(
                    _account_link_status(session, payment["payer_account_id"])
                ),
                "distinct_currency": payment["currency"] != "USD",
            }
        )

    selected = _selected_assessment(
        session, actor, assessment_id, assessments, allocations, payments
    )
    # The finance actions sit with the selected assessment.  They stay
    # reachable when no assessment is selected, because assessing an
    # application is the step that creates the first assessment.
    actions = _finance_actions(session, actor, selected)

    exceptions = [row for row in assessments if row["position"]["exception"]]
    permit_status = _permit_status_for(session, assessments)
    allocation_rows = [
        {
            "allocation_id": allocation["allocation_id"],
            "payment_id": allocation["payment_id"],
            "assessment_id": allocation["assessment_id"],
            "reference": reference_by_application.get(
                assessment_by_id.get(allocation["assessment_id"], {}).get(
                    "application_id", ""
                ),
                "",
            )
            or allocation["assessment_id"],
            "amount": allocation["amount"],
            "currency": allocation["currency"],
            "status": allocation["status"],
            "actor": _actor_label(session, allocation["actor_id"]),
        }
        for allocation in allocations
    ]

    return {
        "tab": tab,
        "tabs": [
            {"key": key, "label": label, "href": f"/reconciliation?tab={key}"}
            for key, label in _RECONCILIATION_TABS
        ],
        "rows": rows,
        "row_count_label": (
            f"{len(rows)} assessment(s) in the demonstration · synthetic ACME values"
        ),
        "query": query,
        "receipts": receipt_rows,
        "receipt_count_label": (
            f"{len(receipt_rows)} receipt(s) recorded · synthetic ERP events"
        ),
        "allocations": allocation_rows,
        "accounts": accounts,
        "account_count_label": f"{len(accounts)} finance account(s) recorded",
        "selected": selected,
        "actions": actions,
        "denied_action_explanations": view_models.denied_action_explanations(actions),
        "exceptions": {
            "count": len(exceptions),
            "definition": (
                "Assessments whose recorded reconciliation carries an exception, such "
                "as a reversed receipt, an unsettled receipt, a currency that is not "
                "the assessment currency, or an unmatched payer account."
            ),
            "attention": bool(exceptions),
        },
        "permit_status": permit_status,
        "responsibility": view_models.responsibility(
            session,
            domain_id="finance",
            source_system_id="erp_finance",
            dataset_key="finance_accounts",
        ),
    }


_RECONCILIATION_TABS: tuple[tuple[str, str], ...] = (
    ("assessments", "Assessments"),
    ("receipts", "Receipts"),
    ("accounts", "Accounts"),
)


def _finance_status_detail(row: dict[str, Any]) -> str:
    """Return the plain reading of one reconciliation status."""
    status = row["position"]["status"]
    exception = row["position"]["exception"]
    if exception:
        return exception.replace("_", " ")
    return {
        "exact": "assessed and paid in full",
        "partial": "partly paid",
        "unpaid": "not paid",
        "overpaid": "paid more than assessed",
    }.get(status, status.replace("_", " "))


def _account_link_status(session: Session, account_id: str | None) -> str:
    """Return the identity link status of the payer account of a receipt."""
    if not account_id:
        return "no payer account recorded"
    row = session.execute(
        select(registry.FinanceAccount).where(
            registry.FinanceAccount.account_id == account_id
        )
    ).scalar_one_or_none()
    if row is None:
        return "payer account not registered"
    return row.link_status


def _permit_status_for(
    session: Session, assessments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the permit status of every application that carries an assessment."""
    statuses: list[dict[str, Any]] = []
    for row in assessments:
        application = session.get(permit.Application, row["application_id"])
        if application is None:
            continue
        issued = session.execute(
            select(permit.Permit).where(
                permit.Permit.application_id == application.id
            )
        ).scalars().first()
        statuses.append(
            {
                "reference": application.source_application_number,
                "application_status": application.status,
                "application_status_label": ops_views.display_word(
                    "values", application.status
                ),
                "permit": "issued" if issued is not None else "not issued",
                "permit_label": "Issued" if issued is not None else "Not issued",
            }
        )
    return statuses


def _selected_assessment(
    session: Session,
    actor: ActorContext,
    assessment_id: str | None,
    assessments: list[dict[str, Any]],
    allocations: list[dict[str, Any]],
    payments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the selected assessment with its receipts, allocations and history."""
    if not assessment_id:
        return None
    row = next(
        (item for item in assessments if item["assessment_id"] == assessment_id), None
    )
    if row is None:
        return None
    own_allocations = [
        item for item in allocations if item["assessment_id"] == assessment_id
    ]
    payment_by_id = {item["payment_id"]: item for item in payments}
    receipts = [
        {
            "payment_id": item["payment_id"],
            "transaction": payment_by_id.get(item["payment_id"], {}).get(
                "source_transaction_id", ""
            ),
            "amount": item["amount"],
            "currency": item["currency"],
            "settlement_status": payment_by_id.get(item["payment_id"], {}).get(
                "settlement_status", ""
            ),
            "settlement_status_label": ops_views.display_word(
                "values",
                payment_by_id.get(item["payment_id"], {}).get("settlement_status", ""),
            ),
            "status": item["status"],
            "status_label": ops_views.display_word("values", item["status"]),
            "distinct_currency": item["currency"] != row["currency"],
        }
        for item in own_allocations
    ]
    history = []
    events = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type.in_(("assessment", "allocation")),
            audit.AuditEvent.target_id.in_(
                [assessment_id] + [item["allocation_id"] for item in own_allocations]
            ),
        )
        .order_by(audit.AuditEvent.occurred_at.desc())
    ).scalars().all()
    history = [
        {
            "action": row.action,
            "action_label": ops_views.action_label(row.action),
            "occurred_at": view_models._iso(row.occurred_at),
            "occurred_date": _readable_date(row.occurred_at),
            "actor": _actor_label(session, row.actor_id),
            "outcome": row.outcome,
            "reason": row.reason or "",
            "references": list(row.references or []),
        }
        for row in events
    ]
    assessed_cents = int(row["position"].get("assessed_total_cents") or 0)
    settled_cents = int(row["position"].get("settled_allocated_cents") or 0)
    return {
        "assessment_id": row["assessment_id"],
        "application_id": row["application_id"],
        "reference": _application_reference(session, row["application_id"]),
        "version": row["version"],
        "assessed_total": row["assessed_total"],
        "currency": row["currency"],
        "settled_allocated": row["position"]["settled_allocated"],
        "alloc_pct": (
            min(100, round(100 * settled_cents / assessed_cents))
            if assessed_cents
            else 0
        ),
        "balance": row["position"]["balance"],
        "status": row["position"]["status"],
        "status_label": ops_views.display_word("values", row["position"]["status"]),
        "status_detail": _finance_status_detail(row),
        "exception": row["position"]["exception"] or "",
        "lines": [
            {
                "fee_code": line["fee_code"],
                "description": line["description"],
                "quantity": line["quantity"],
                "amount": line["amount"],
                "currency": line["currency"],
            }
            for line in row["lines"]
        ],
        "receipts": receipts,
        "allocations": [
            {
                "allocation_id": item["allocation_id"],
                "payment_id": item["payment_id"],
                "amount": item["amount"],
                "currency": item["currency"],
                "status": item["status"],
                "actor": _actor_label(session, item["actor_id"]),
            }
            for item in own_allocations
        ],
        "history": history,
    }


def _finance_actions(
    session: Session, actor: ActorContext, selected: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return the finance actions that act on the selected assessment.

    Without a selected assessment the application-level actions stay
    reachable and the fields are left for the persona to fill in.
    """
    assessment_id = selected["assessment_id"] if selected else ""
    application_id = selected["application_id"] if selected else ""
    currency = selected["currency"] if selected else "USD"
    actions: list[dict[str, Any]] = []
    assess = build_action(
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
            _field("application_id", "Application", value=application_id, required=True),
            _field("valuation", "Declared valuation"),
            _field(
                "expected_application_version",
                "Expected application version",
                field_type="number",
            ),
            _field("reason", "Reason", field_type="textarea"),
        ),
    )
    assess["dom_id"] = "finance-assess"
    actions.append(assess)
    reassess = build_action(
        session,
        actor,
        action_id="finance.reassess",
        label="Reassess application",
        path="/ui/actions/finance.reassess",
        permission="finance.assessment.create",
        domain_id="finance",
        destination="Finance assessment",
        description=(
            "Assess again at a new valuation. The paid funds are carried forward "
            "once, in the same transaction."
        ),
        fields=(
            _field("application_id", "Application", value=application_id, required=True),
            _field("valuation", "Declared valuation"),
            _field(
                "expected_application_version",
                "Expected application version",
                field_type="number",
            ),
            _field(
                "carry_forward",
                "Carry the paid funds forward",
                value="true",
                field_type="hidden",
            ),
            _field("reason", "Reason", field_type="textarea"),
        ),
    )
    reassess["dom_id"] = "finance-reassess"
    actions.append(reassess)
    allocate = build_action(
        session,
        actor,
        action_id="finance.allocate",
        label="Confirm allocation",
        path="/ui/actions/finance.allocate",
        permission="finance.allocation.confirm",
        domain_id="finance",
        destination="Finance allocation",
        description=(
            "Confirm an allocation of settled funds to an assessment version. The "
            "idempotency key keeps a repeated command harmless."
        ),
        fields=(
            _field("payment_id", "Receipt", required=True),
            _field(
                "assessment_id",
                "Assessment version",
                value=assessment_id,
                required=True,
            ),
            _field("amount", "Amount", required=True),
            _field("currency", "Currency", value=currency, required=True),
            _field("idempotency_key", "Idempotency key", required=True),
            _field("reason", "Reason", field_type="textarea"),
        ),
    )
    allocate["dom_id"] = "finance-allocate"
    actions.append(allocate)
    reconcile = build_action(
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
            _field(
                "assessment_id",
                "Assessment version",
                value=assessment_id,
                required=True,
            ),
            _field("payment_ids", "Receipts (comma separated)"),
        ),
    )
    reconcile["dom_id"] = "finance-reconcile"
    actions.append(reconcile)
    import_action = build_action(
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
            _field(
                "event_type",
                "Event type",
                value="received",
                field_type="select",
                options=("received", "settled", "reversed"),
            ),
            _field("amount", "Amount", required=True),
            _field("currency", "Currency", value=currency, required=True),
            _field("payer_account_id", "Payer account"),
            _field("reason", "Reason", field_type="textarea"),
        ),
    )
    import_action["dom_id"] = "finance-import"
    actions.append(import_action)
    return actions


__all__ = [
    "REGISTER_VIEWS",
    "RULE_TABS",
    "VERSION_STATUS_LABELS",
    "governance_screen",
    "planning_overview",
    "reconciliation_screen",
    "rules_register",
]

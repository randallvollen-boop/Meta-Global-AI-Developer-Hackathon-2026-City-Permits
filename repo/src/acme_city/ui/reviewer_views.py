"""Reviewer-facing wording and derived facts for the queue and the workspace.

Everything here is read-only.  It turns recorded state into the plain words a
permit reviewer reads: who the applicant is, where the property is (with its
unit), what stage a case is in, what the issue is, who has to act next and
what the reviewer's own action is called.  The exact codes stay available in
details; nothing here writes a record or decides a permission.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.plain_reason import describe_recommendation
from acme_city.applicant_portal.presubmit import FLAG as SUBMITTED_WITH_KNOWN_ISSUES
from acme_city.core.clock import utc_now
from acme_city.permits.schemas import Blocker
from acme_city.persistence.models import audit, change, finance, permit, registry
from acme_city.ui import display, ops_views

#: The queue views, in display order: key, label, what the view holds.
QUEUE_VIEWS: tuple[tuple[str, str, str], ...] = (
    ("checks", "Needs checks", "Open applications with no data problem in the way: run the checks, then decide."),
    ("data", "Needs data resolution", "Cases held by an identity, property, credential or finance record that is not confirmed yet."),
    ("applicant", "Waiting for applicant", "Cases the City has sent back and is waiting on the applicant to answer."),
    ("issued", "Issued", "Cases with an issued permit."),
    ("all", "All", "Everything in scope."),
)
QUEUE_VIEW_KEYS = tuple(key for key, _, _ in QUEUE_VIEWS)

#: Plain words for the recorded issue codes (the exact code stays in details).
ISSUE_WORDS: dict[str, str] = {
    "identity_link_unapproved": "Identity needs confirmation",
    "finance_account_link_unapproved": "Payer account needs confirmation",
    "finance_account_unknown": "Payer account is not on file",
    "site_unresolved": "Property address needs confirmation",
    "site_missing": "Property address is missing",
    "parcel_unmatched": "Property address needs confirmation",
    "parcel_link_unapproved": "Property address needs confirmation",
    "credential_missing": "License is missing",
    "credential_expired": "License has expired",
    "credential_inactive": "License is not active",
    "credential_not_yet_valid": "License is not valid yet",
    "credential_holder_mismatch": "License belongs to someone else",
    "no_current_evaluation": "Application checks have not been run",
    "evaluation_stale": "Application checks are out of date",
    "decision_stale": "Decision needs reconfirming",
    "open_issue": "An open issue is attached",
}

#: Codes that mean "run or refresh the checks", not a data problem.
CHECK_CODES = frozenset({"no_current_evaluation", "evaluation_stale", "decision_stale", "decision_not_current"})

#: The stage a recorded status reads as.
STAGE_WORDS: dict[str, str] = {
    "draft": "Draft",
    "submitted": "Submitted",
    "needs_information": "Intake review",
    "ready_for_review": "Ready for review",
    "under_review": "Under review",
    "revisions_requested": "Revisions requested",
    "approved": "Decision recorded",
    "denied": "Decision recorded",
    "issued": "Issued",
    "returned": "Returned to applicant",
    "archived": "Archived",
}

APPLICANT_BUCKET_STATUSES = frozenset({"revisions_requested", "returned"})


def issue_label(code: str) -> str:
    """Return the plain words of one issue code."""
    if code in ISSUE_WORDS:
        return ISSUE_WORDS[code]
    return code.replace("_", " ").capitalize() if code else ""


def stage_label(status: str) -> str:
    """Return the stage a status reads as."""
    return STAGE_WORDS.get(status, status.replace("_", " ").capitalize())


def applicant_name(session: Session, application: permit.Application) -> str:
    """Return the applicant's name: as stated, else the party's display name."""
    facts = dict(application.submitted_facts or {})
    stated = str(facts.get("applicant_name") or facts.get("organization_name") or "").strip()
    if application.applicant_party_id:
        party = session.get(registry.Party, application.applicant_party_id)
        if party is not None and party.display_name:
            return party.display_name
    return stated


def _unit_text(address: registry.Address) -> str:
    if not address.unit_number:
        return ""
    kind = (address.unit_type or "unit").strip().capitalize()
    return f"{kind} {address.unit_number}"


def address_with_unit(session: Session, application: permit.Application) -> str:
    """Return the property address with its unit, e.g. ``400 Lantern Row, Unit 2``.

    The resolved official address wins; before the site resolves, the text the
    applicant submitted is shown as submitted.
    """
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id,
            permit.ApplicationSite.is_primary.is_(True),
        )
    ).scalars().first()
    if site is not None and site.address_id:
        address = session.execute(
            select(registry.Address).where(
                (registry.Address.id == site.address_id)
                | (registry.Address.address_id == site.address_id)
            )
        ).scalars().first()
        if address is not None:
            street = " ".join(
                part for part in (address.street_number, address.street_name) if part
            )
            unit = _unit_text(address)
            return ", ".join(part for part in (street, unit) if part) or (
                site.submitted_address_text or ""
            )
    if site is not None and site.submitted_address_text:
        return site.submitted_address_text
    facts = dict(application.submitted_facts or {})
    return str(facts.get("submitted_site_text") or facts.get("site_address") or "")


def submitted_address(session: Session, application: permit.Application) -> str:
    """Return the address text exactly as submitted."""
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id,
            permit.ApplicationSite.is_primary.is_(True),
        )
    ).scalars().first()
    if site is not None and site.submitted_address_text:
        return site.submitted_address_text
    return str(dict(application.submitted_facts or {}).get("submitted_site_text") or "")


def routed_to_steward(session: Session, application: permit.Application) -> bool:
    """Return whether a data issue of the case has really been sent to a steward.

    A data issue counts as routed only when an open change case or an open
    review task names the case.  Without one, nobody else has been asked.
    """
    targets = {application.id, application.source_application_number}
    case = session.execute(
        select(change.ChangeCase.id).where(
            change.ChangeCase.target_id.in_(targets),
            change.ChangeCase.status.notin_(("closed", "rejected")),
        )
    ).first()
    if case is not None:
        return True
    task = session.execute(
        select(change.ReviewTask.id).where(
            change.ReviewTask.target_id.in_(targets),
            change.ReviewTask.status == "open",
        )
    ).first()
    return task is not None


def last_activity(session: Session, application: permit.Application) -> datetime | None:
    """Return the time of the newest audit event of a case, if any."""
    row = session.execute(
        select(audit.AuditEvent.occurred_at)
        .where(audit.AuditEvent.target_id == application.id)
        .order_by(audit.AuditEvent.occurred_at.desc())
    ).first()
    return row[0] if row else None


def bucket_of(application: permit.Application, blockers: list[dict[str, str]]) -> str:
    """Return the queue view an application belongs to."""
    if application.status == "issued":
        return "issued"
    if application.status in APPLICANT_BUCKET_STATUSES:
        return "applicant"
    data_blockers = [b for b in blockers if b["code"] not in CHECK_CODES]
    if data_blockers or application.status == "needs_information":
        return "data"
    return "checks"


def _day(value: datetime | None) -> str:
    return value.date().isoformat() if value else ""


def decorate_application_item(
    session: Session,
    item: dict[str, Any],
    application: permit.Application,
    owner_label: str,
    target_days: int,
    now: datetime,
) -> None:
    """Add the recognisable row fields to one application queue entry."""
    blockers = item.get("blockers") or []
    bucket = bucket_of(application, blockers)
    first = next((b for b in blockers if b["code"] not in CHECK_CODES), None) or (
        blockers[0] if blockers else None
    )
    routed = bucket == "data" and routed_to_steward(session, application)
    if bucket == "issued":
        next_party, action = "None (issued)", "Open application"
    elif bucket == "applicant":
        next_party, action = "Applicant", "Open application"
    elif bucket == "data":
        if routed:
            next_party, action = "Waiting on steward", "View referred issue"
        else:
            next_party, action = "Permit review team (not yet referred to a steward)", "Open application"
    else:
        next_party, action = "Permit review team", "Open application"
    if first is not None:
        issue, code = issue_label(first["code"]), first["code"]
    elif application.status == "needs_information":
        issue, code = "Steward is completing intake", ""
    elif bucket == "applicant":
        issue, code = "Waiting for the applicant's answer", ""
    elif bucket == "issued":
        issue, code = "None", ""
    else:
        issue, code = "None recorded", ""
    submitted = application.initial_submitted_at
    waiting = application.revision_submitted_at or submitted
    activity = last_activity(session, application)
    updated = max([d for d in (activity, waiting) if d is not None], default=None)
    age = item.get("age_days")
    target_state = ""
    if bucket != "issued" and target_days and age is not None:
        target_state = "over" if age > target_days else "within"
    item.update(
        {
            "bucket": bucket,
            "applicant_name": applicant_name(session, application),
            "address": address_with_unit(session, application),
            "project_type": item.get("subtitle", ""),
            # A portal arrival that the intake agent has not run on yet keeps
            # the queue's established wording.
            "stage_label": (
                "Awaiting intake agent"
                if application.status == "submitted" and application.scenario_id is None
                else stage_label(application.status)
            ),
            "issue_label": issue,
            "issue_code": code,
            "next_party": next_party,
            "action_label": action,
            "routed_to_steward": routed,
            "owner_label": owner_label,
            "owner_actor_id": application.owner_actor_id or "",
            "submitted_on": _day(submitted),
            "waiting_since": _day(waiting),
            "last_updated": _day(updated),
            "target_days": target_days if bucket != "issued" else 0,
            "target_state": target_state,
            "technical": {
                "application_id": application.id,
                "applicant_party_id": application.applicant_party_id or "",
                "permit_type_key": item.get("permit_type_key", ""),
            },
        }
    )
    del now


def decorate_other_item(item: dict[str, Any]) -> None:
    """Add the row fields of a change case, review task or governance issue."""
    kind = item.get("kind")
    item.update(
        {
            "bucket": "data",
            "applicant_name": "",
            "address": "",
            "project_type": item.get("object_type", ""),
            "stage_label": item.get("state_label") or str(item.get("state", "")).replace("_", " ").capitalize(),
            "issue_label": item.get("blocker") or item.get("next_action", ""),
            "issue_code": item.get("blocker_code", ""),
            "next_party": "Data steward" if kind != "issue" else "Accountable owner",
            "action_label": "View referred issue",
            "routed_to_steward": True,
            "owner_label": item.get("assignee") or "",
            "submitted_on": "",
            "waiting_since": "",
            "last_updated": "",
            "target_days": 0,
            "target_state": "",
            "technical": {"item_id": item.get("id", ""), "kind": kind or ""},
        }
    )


def queue_views(entries: list[dict[str, Any]], active: str) -> list[dict[str, Any]]:
    """Return the queue views with real counts; a view without cases is omitted."""
    counts = {key: 0 for key in QUEUE_VIEW_KEYS}
    for entry in entries:
        counts[entry.get("bucket", "checks")] += 1
        counts["all"] += 1
    return [
        {"key": key, "label": label, "note": note, "count": counts[key], "active": key == active}
        for key, label, note in QUEUE_VIEWS
        if counts[key] > 0 or key == "all"
    ]


def scenario_clock_note(now: datetime | None = None) -> str:
    """Return the note that explains the ages of seeded cases."""
    return "Ages count whole days from the submission date to " + _day(now or utc_now()) + "."


# ------------------------------------------------------------------ workspace

#: How an observation state reads to a reviewer.
FIELD_STATE_WORDS: dict[str, str] = {
    "proposed": "Suggested: awaiting steward",
    "accepted": "Confirmed by steward",
    "corrected": "Corrected and confirmed by steward",
    "rejected": "Rejected by steward",
}
CONFIRMED_STATES = frozenset({"accepted", "corrected"})


def _revision_rows(session: Session, application: permit.Application) -> list[dict[str, Any]]:
    """Return the revisions with what changed since the previous one."""
    revisions = session.execute(
        select(permit.ApplicationRevision)
        .where(permit.ApplicationRevision.application_id == application.id)
        .order_by(permit.ApplicationRevision.revision_number)
    ).scalars().all()
    documents = session.execute(
        select(permit.Document)
        .where(permit.Document.application_id == application.id)
        .order_by(permit.Document.received_at)
    ).scalars().all()
    evaluations = session.execute(
        select(permit.Evaluation)
        .where(permit.Evaluation.application_id == application.id)
        .order_by(permit.Evaluation.performed_at)
    ).scalars().all()
    current = revisions[-1] if revisions else None
    rows: list[dict[str, Any]] = []
    previous = None
    for revision in revisions:
        snapshot = dict(revision.snapshot or {})
        before = dict(previous.snapshot or {}) if previous is not None else {}
        changed = [
            {"field": key, "before": str(before.get(key, "")), "after": str(snapshot.get(key, ""))}
            for key in sorted(set(before) | set(snapshot))
            if previous is not None and before.get(key) != snapshot.get(key)
        ]
        lower = previous.submitted_at if previous is not None else None
        received = [
            f"{doc.document_type} v{doc.version}"
            for doc in documents
            if (lower is None or doc.received_at > lower) and doc.received_at <= revision.submitted_at
        ]
        checks = [ev for ev in evaluations if ev.revision_id == revision.id]
        is_current = current is not None and revision.id == current.id
        if checks:
            latest = checks[-1]
            checks_state = "Application checks run on this revision" + (
                " (out of date)" if latest.stale else ""
            )
            needs_rereview = bool(latest.stale)
        else:
            checks_state = "Application checks not run on this revision"
            needs_rereview = is_current
        rows.append(
            {
                "revision_id": revision.id,
                "number": revision.revision_number,
                "submitted_at": revision.submitted_at.isoformat() if revision.submitted_at else "",
                "is_current": is_current,
                "label": "Current revision" if is_current else "Earlier revision: superseded",
                "changed": changed,
                "documents": received,
                "checks_state": checks_state,
                "needs_rereview": needs_rereview,
            }
        )
        previous = revision
    return rows


def _ai_summary(detail: dict[str, Any]) -> dict[str, Any]:
    """Return the suggested-versus-confirmed summary of the latest extraction."""
    runs = detail.get("model_runs") or []
    run = runs[0] if runs else None
    fields = []
    for field in detail.get("extracted_fields") or []:
        state = str(field.get("state") or "proposed")
        fields.append(
            {
                **field,
                "state_label": FIELD_STATE_WORDS.get(state, state),
                "confirmed": state in CONFIRMED_STATES,
            }
        )
    confirmed = sum(1 for field in fields if field["confirmed"])
    suggested = len(fields) - confirmed
    if fields and not suggested:
        review_text = "All confirmed by steward"
    elif confirmed:
        review_text = f"{confirmed} confirmed, {suggested} for steward review"
    else:
        review_text = "For steward review"
    return {
        "has_run": run is not None,
        "run_id": run["run_id"] if run else "",
        "source_label": (
            "Recorded replay"
            if run and run.get("mode") == "replay"
            else (ops_views.display_word("values", run["source_label"]) if run else "")
        ),
        "fields": fields,
        "total": len(fields),
        "suggested": suggested,
        "confirmed": confirmed,
        "review_text": review_text,
        "extraction_passed": bool(run and run.get("status") == "succeeded"),
    }


def _issuance_words(detail: dict[str, Any], blockers: list[dict[str, str]]) -> tuple[str, str]:
    """Return the issuance status and the next prerequisite, in plain words."""
    if detail.get("issued"):
        return "Issued", ""
    decision = detail.get("current_decision")
    if decision is None:
        return "Not started", "Record the review decision."
    if decision["outcome"] not in ("approved", "approved_with_conditions"):
        return "Not applicable", f"The decision is {decision['outcome_label'].lower()}, so no permit is issued."
    if decision.get("stale"):
        return "Waiting", "Reconfirm the decision; the case changed after it was recorded."
    finance = detail.get("finance") or {}
    if not finance.get("assessment"):
        return "Waiting", "Assess the fee."
    reconciliation = finance.get("reconciliation") or {}
    if reconciliation and str(reconciliation.get("status", "")) not in ("settled", "reconciled", "paid"):
        return "Waiting", f"Payment is not complete (balance {reconciliation.get('balance')} {reconciliation.get('currency', '')})."
    open_items = [issue_label(b["code"]) for b in blockers]
    if open_items:
        return "Waiting", "Clear: " + "; ".join(open_items) + "."
    return "Ready", "The issuing officer issues the permit."


def _actor_label(session: Session, actor_id: str | None) -> str:
    """Return the name of the person or service that acted."""
    if not actor_id:
        return "Not recorded"
    from acme_city.ui import view_models

    return view_models.actor_label(session, actor_id)


def _party_name(session: Session, party_id: str | None) -> str:
    """Return the name of a person or organization."""
    if not party_id:
        return ""
    row = session.get(registry.Party, party_id)
    return "" if row is None else row.display_name


def _parcel_number(session: Session, parcel_id: str | None) -> str:
    """Return the parcel number of one parcel."""
    if not parcel_id:
        return ""
    row = session.execute(
        select(registry.Parcel).where(registry.Parcel.parcel_id == parcel_id)
    ).scalars().first()
    return "" if row is None else row.source_parcel_number


def _address_text(session: Session, address_id: str | None) -> str:
    """Return the address as the record holds it."""
    if not address_id:
        return ""
    row = session.execute(
        select(registry.Address).where(registry.Address.address_id == address_id)
    ).scalars().first()
    if row is None:
        return ""
    return row.source_string or " ".join(
        part
        for part in (
            row.street_number,
            row.street_name,
            row.street_type,
            row.unit_type,
            row.unit_number,
        )
        if part
    )


def _rule_titles(session: Session, rule_ids: set[str]) -> dict[str, str]:
    """Return the title of each rule, by its rule id."""
    if not rule_ids:
        return {}
    rows = session.execute(
        select(finance.RuleVersion)
        .where(finance.RuleVersion.rule_id.in_(sorted(rule_ids)))
        .order_by(finance.RuleVersion.effective_from)
    ).scalars().all()
    titles: dict[str, str] = {}
    for row in rows:
        titles[row.rule_id] = row.title
    return titles


def label_workspace(session: Session, detail: dict[str, Any]) -> None:
    """Add the readable words to everything the workspace shows.

    The stored keys stay where they are.  Every value a reviewer reads gets
    the word a person says beside it: a name instead of an actor id, the
    title of a rule instead of its key, and the plain state of a thing
    instead of the state the database stores.
    """
    decision = detail.get("current_decision")
    if isinstance(decision, dict):
        decision["decided_by_label"] = _actor_label(
            session, decision.get("decided_by_actor_id")
        )
    for row in detail.get("decisions") or []:
        row["decided_by_label"] = _actor_label(session, row.get("decided_by_actor_id"))

    for row in detail.get("findings") or []:
        row["type_label"] = ops_views.display_word("values", row.get("finding_type"))
        row["severity_label"] = ops_views.display_word("values", row.get("severity"))
        row["state_label"] = ops_views.display_word("values", row.get("state"))
        row["waived_by_label"] = _actor_label(session, row.get("waived_by_actor_id"))

    evaluation = detail.get("evaluation")
    rule_ids: set[str] = set()
    if isinstance(evaluation, dict):
        evaluation["outcome_label"] = ops_views.display_word("values", evaluation.get("outcome"))
        evaluation["status_label"] = ops_views.display_word("values", evaluation.get("status"))
        evaluation["performed_by_label"] = _actor_label(
            session, evaluation.get("performed_by_actor_id")
        )
        for result in evaluation.get("results") or []:
            if result.get("reason") == "parcel_not_confirmed":
                result["status_label"] = "Not checked"
            else:
                result["status_label"] = ops_views.display_word("values", result.get("status"))
            rule_ids.add(str(result.get("rule_id") or ""))
    for row in detail.get("evaluations") or []:
        row["outcome_label"] = ops_views.display_word("values", row.get("outcome"))
        row["status_label"] = ops_views.display_word("values", row.get("status"))
        rule_ids.update(str(item) for item in (row.get("rule_versions") or {}))

    for row in detail.get("recommendations") or []:
        row["proposed_outcome_label"] = ops_views.display_word(
            "values", row.get("proposed_outcome")
        )
        row["status_label"] = ops_views.display_word("values", row.get("status"))
        row["plain"] = describe_recommendation(
            rationale=row.get("rationale") or "",
            evidence_refs=row.get("evidence_refs") or [],
            conditions=row.get("conditions") or [],
            titles=_rule_titles(
                session,
                {
                    str(ref.get("rule_id"))
                    for ref in row.get("evidence_refs") or []
                    if ref.get("rule_id") and not ref.get("title")
                },
            ),
        )

    titles = _rule_titles(session, {item for item in rule_ids if item})
    for result in (evaluation or {}).get("results") or []:
        result["rule_title"] = titles.get(str(result.get("rule_id") or ""), "")

    current = detail.get("current") or {}
    for party in current.get("parties") or []:
        party["name"] = _party_name(session, party.get("party_id"))
        party["role_label"] = ops_views.display_word("values", party.get("party_role"))
    site = current.get("site") or {}
    site["parcel_label"] = _parcel_number(session, site.get("parcel_id"))
    site["address_label"] = _address_text(session, site.get("address_id"))
    site["resolution_label"] = ops_views.display_word(
        "values", site.get("resolution_status"), "Not resolved"
    )

    for link in detail.get("crosswalks") or []:
        link["entity_label"] = _party_name(session, link.get("entity_id")) or str(
            link.get("entity_id") or ""
        )
        link["source_label"] = display.source_name(
            session, link.get("source_system_id"), link.get("source_dataset_key")
        )
        link["link_status_label"] = ops_views.link_status_label(link.get("link_status"))

    for document in detail.get("documents") or []:
        document["document_type_label"] = ops_views.display_word(
            "values", document.get("document_type")
        )

    finance_view = detail.get("finance") or {}
    assessment = finance_view.get("assessment")
    if isinstance(assessment, dict):
        assessment["status_label"] = ops_views.display_word("values", assessment.get("status"))
    reconciliation = finance_view.get("reconciliation")
    if isinstance(reconciliation, dict):
        reconciliation["status_label"] = ops_views.display_word(
            "values", reconciliation.get("status")
        )
    for allocation in finance_view.get("allocations") or []:
        allocation["status_label"] = ops_views.display_word("values", allocation.get("status"))
        allocation["actor_label"] = _actor_label(session, allocation.get("actor_id"))


#: Queues a case may send the reviewer back to. Persona homes are added
#: beside these, because a persona who opened the case from home should
#: land there again.
_QUEUE_RETURNS: dict[str, str] = {
    "/queue": "/queue",
    "/queue/review": "/queue/review",
    "/queue/intake": "/queue/intake",
    "/queue/early-resolution": "/queue/early-resolution",
    "/steward": "/steward",
    "/agents": "/agents",
}

#: A permit workspace address with no query. Only these gain ``?from=``.
_CASE_HREF = re.compile(r"^/permits/[A-Za-z0-9_-]+$")


def _path_key(path: str) -> str:
    """Return the allowlist key of a local path, or ``""`` when it has none."""
    if not path.startswith("/") or path.startswith("//"):
        return ""
    return path.rstrip("/") or "/"


def _return_targets() -> dict[str, str]:
    """Return the allowlisted path and the address the back link uses."""
    from acme_city.ui import view_models

    targets = dict(_QUEUE_RETURNS)
    for profile in view_models.PERSONA_PROFILES.values():
        href = str(profile.get("next") or "")
        key = _path_key(href)
        if key:
            targets.setdefault(key, href)
    for href in view_models.HOME_OVERRIDES.values():
        key = _path_key(str(href))
        if key:
            targets.setdefault(key, str(href))
    return targets


def page_origin(path: str, query: str = "") -> str:
    """Return the local path of the page a case link is leaving."""
    origin = path or "/"
    if query:
        return f"{origin}?{query}"
    return origin


def accepted_return(value: str | None) -> tuple[str, str] | None:
    """Return ``(href, screen path)`` when ``value`` is an allowlisted local return.

    A query on an allowlisted queue is kept, so a filtered queue is the
    same queue on the way back. A foreign, absolute or off-list value
    returns ``None`` and the caller uses the persona's home queue.
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    decoded_path = unquote(parts.path)
    decoded_query = unquote(parts.query)
    if (
        "\\" in decoded_path
        or "\\" in decoded_query
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded_path + decoded_query)
        or not decoded_path.startswith("/")
        or decoded_path.startswith("//")
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        return None
    canonical = _return_targets().get(_path_key(decoded_path))
    if canonical is None:
        return None
    href = f"{canonical}?{parts.query}" if parts.query else canonical
    return href, canonical


def workspace_return(session: Session, actor: Any, value: str | None) -> tuple[str, str]:
    """Return the back link of the permit workspace and its label."""
    from acme_city.ui import view_models

    chosen = accepted_return(value)
    if chosen is None:
        home = view_models.home_for(session, actor)
        return home["href"], f"Back to {home['label']}"
    href, label_path = chosen
    screen = view_models.screen_for_path(label_path)
    if screen:
        name = view_models.screen_label(screen)
    elif _path_key(label_path) == "/city":
        name = "the City website"
    else:
        name = label_path
    return href, f"Back to {name}"


def stamp_case_links(value: Any, origin: str) -> None:
    """Add ``?from=`` to every permit-workspace link under ``value``.

    The origin has to be an allowlisted return. Anything else is left
    alone, and the workspace then uses the persona's home queue.
    """
    if accepted_return(origin) is None:
        return
    _stamp(value, origin, set())


def _stamp(value: Any, origin: str, seen: set[int]) -> None:
    if isinstance(value, dict):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        href = value.get("href")
        if isinstance(href, str) and _CASE_HREF.fullmatch(href):
            value["href"] = f"{href}?{urlencode({'from': origin})}"
        for item in list(value.values()):
            _stamp(item, origin, seen)
    elif isinstance(value, list):
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        for item in value:
            _stamp(item, origin, seen)


def _case_from(application_id: str) -> str:
    """Return the ``from`` value that brings a person back to this case."""
    return quote(f"/permits/{application_id}", safe="/")


def _off_case(path: str, application_id: str) -> str:
    """Return a link to another screen, with a return to this case."""
    return f"{path}?from={_case_from(application_id)}"


def _short_place(text: str) -> str:
    """Return an address without the trailing city name."""
    cleaned = " ".join(str(text or "").split())
    suffix = ", ACME City"
    if cleaned.endswith(suffix):
        cleaned = cleaned[: -len(suffix)].strip()
    return cleaned


def _property_place(session: Session, application: permit.Application) -> str:
    """Return the address the blocker sentence names."""
    from acme_city.persistence.models import gis

    match = session.execute(
        select(gis.ApplicationParcelMatch).where(
            gis.ApplicationParcelMatch.application_id == application.id
        )
    ).scalars().first()
    if match is not None and match.submitted_text:
        place = _short_place(match.submitted_text)
        if place:
            return place
    return _short_place(address_with_unit(session, application)) or "this property"


def _party_label(session: Session, party_id: str) -> str:
    """Return the name a blocker sentence uses for a party."""
    name = _party_name(session, party_id)
    return name or "this party"


def _credential_row(session: Session, credential_id: str | None) -> registry.Credential | None:
    """Return the credential a blocker names."""
    if not credential_id:
        return None
    return session.execute(
        select(registry.Credential).where(registry.Credential.credential_id == credential_id)
    ).scalars().first()


def _credential_words(credential: registry.Credential | None) -> str:
    """Return the plain name of a license or registration."""
    if credential is None:
        return "license"
    kind = {
        "contractor_registration": "contractor registration",
        "business_license": "business licence",
    }.get(credential.credential_type, credential.credential_type.replace("_", " "))
    return f"{kind} {credential.number}".strip()


def _identity_href(session: Session, party_id: str, application_id: str) -> str:
    """Return the steward task that confirms one party, or the steward queue."""
    proposal = None
    if party_id:
        proposal = session.execute(
            select(registry.MatchProposal)
            .where(registry.MatchProposal.entity_id == party_id)
            .order_by(registry.MatchProposal.created_at.desc())
        ).scalars().first()
        if proposal is None:
            for row in session.execute(select(registry.MatchProposal)).scalars():
                candidates = {str(item) for item in (row.candidate_ids or [])}
                if party_id in candidates:
                    proposal = row
                    break
    if proposal is not None:
        return _off_case(f"/steward/issues/link/{proposal.id}", application_id)
    return _off_case("/steward", application_id)


def _payer_party_id(session: Session, blocker: Blocker) -> str:
    """Return the party a finance-link blocker is about."""
    if blocker.subject_type == "party":
        return str(blocker.subject_id or "")
    if blocker.subject_id:
        account = session.execute(
            select(registry.FinanceAccount).where(
                registry.FinanceAccount.account_id == blocker.subject_id
            )
        ).scalars().first()
        if account is not None and account.party_id:
            return account.party_id
    return ""


def blocker_guide(
    session: Session,
    application: permit.Application,
    blocker: Blocker,
) -> dict[str, str]:
    """Return the plain words, the owner and the fix link of one blocker.

    The raw code stays out of the sentence. The link leaves the case only
    with ``?from=`` set to this case, so the person can come back.
    """
    code = blocker.code
    place = _property_place(session, application)
    case_id = application.id
    owner = "Permit Reviewer"
    href = "#application-checks"
    scope = "decision"
    text = issue_label(code) or blocker.detail

    if code == "parcel_link_unapproved":
        owner = "Data Steward"
        scope = "follow_up"
        href = _off_case(f"/steward/issues/parcel/{case_id}", case_id)
        text = (
            f"The property match for {place} has not been approved by the Data Steward."
        )
    elif code in {"parcel_unmatched", "site_unresolved", "site_missing"}:
        owner = "Data Steward"
        href = _off_case(f"/steward/issues/parcel/{case_id}", case_id)
        text = (
            f"The property address for {place} has not been resolved by the Data Steward."
        )
    elif code == "parcel_unconfirmed":
        owner = "Permit Reviewer"
        href = "#property-heading"
        text = (
            f"The property match for {place} has not been confirmed by the Permit Reviewer."
        )
    elif code == "identity_link_unapproved":
        scope = "follow_up"
        party_id = str(blocker.subject_id or "")
        owner = "Data Steward"
        href = _identity_href(session, party_id, case_id)
        text = (
            f"The identity match for {_party_label(session, party_id)} has not been "
            "approved by the Data Steward."
        )
    elif code in {"finance_account_link_unapproved", "finance_account_unknown"}:
        party_id = _payer_party_id(session, blocker)
        owner = "Data Steward"
        href = _identity_href(session, party_id, case_id)
        text = (
            f"The payer account for {_party_label(session, party_id)} has not been "
            "approved by the Data Steward."
        )
    elif code.startswith("credential_"):
        credential = _credential_row(session, blocker.subject_id)
        owner = "City Administrator"
        if credential is not None:
            href = _off_case(f"/detail/credential/{credential.credential_id}", case_id)
        elif blocker.subject_id:
            href = _off_case(f"/detail/credential/{blocker.subject_id}", case_id)
        words = _credential_words(credential)
        if code == "credential_expired":
            text = f"The {words} has expired. The City Administrator updates that record."
        elif code == "credential_missing":
            text = f"The {words} is not on record. The City Administrator records it."
        elif code == "credential_inactive":
            text = f"The {words} is not active. The City Administrator updates that record."
        elif code == "credential_not_yet_valid":
            text = (
                f"The {words} is not valid yet. The City Administrator updates that record."
            )
        else:
            text = (
                f"The {words} does not match the application. "
                "The City Administrator corrects that record."
            )
    elif code in {"rule_fail", "rule_review"}:
        rule_id = str(blocker.subject_id or "")
        title = _rule_titles(session, {rule_id}).get(rule_id) or rule_id or "A check"
        owner = "Permit Reviewer"
        href = "#application-checks"
        if code == "rule_fail":
            text = (
                f"{title} failed. The Permit Reviewer can record an exception "
                "or run the checks again."
            )
        else:
            text = f"{title} needs a person. The Permit Reviewer runs the checks."
    elif code in {"evaluation_stale", "no_current_evaluation"}:
        owner = "Permit Reviewer"
        href = "#application-checks"
        text = (
            "The application checks are out of date. The Permit Reviewer runs them again."
            if code == "evaluation_stale"
            else "The application checks have not been run. The Permit Reviewer runs them."
        )
    elif code in {"decision_stale", "decision_not_current", "decision_not_approved"}:
        owner = "Permit Reviewer"
        href = "#decision-summary"
        text = "The recorded decision needs the Permit Reviewer to confirm it again."
    elif code == "no_current_assessment" or code.startswith("reconciliation_"):
        owner = "City Administrator"
        href = _off_case("/reconciliation", case_id)
        scope = "issuance"
        text = (
            "No fee has been assessed, so the permit cannot be issued. "
            "The City Administrator records the fee."
            if code == "no_current_assessment"
            else (
                "The fee is not settled, so the permit cannot be issued. "
                "The City Administrator reconciles the payment."
            )
        )
    elif code == "open_issue":
        owner = "City Administrator"
        href = _off_case("/governance", case_id)
        text = "An open issue still blocks issuance. The City Administrator closes it."
        scope = "issuance"

    return {
        "code": code,
        "text": text,
        "owner": owner,
        "href": href,
        "detail": blocker.detail,
        "scope": scope,
    }


def workspace_blocker_guides(
    session: Session, application: permit.Application
) -> list[dict[str, str]]:
    """Return every blocker of the case in the words the next-action panel shows.

    Decision blockers come from the same list an approval checks. A stale
    evaluation is named even when that list does not carry it. The fee
    blockers are added only once a decision is approved, because they hold
    issuance rather than the decision.
    """
    from acme_city.core.clock import utc_now
    from acme_city.permits.decisions import PermitDecisionService
    from acme_city.permits.issuance import PermitIssuanceService
    from acme_city.permits.service import PermitService

    service = PermitService(session)
    evaluation = service.current_evaluation(application.id)
    found: list[Blocker] = []
    if evaluation is not None:
        found.extend(PermitDecisionService(session).blockers(application, evaluation))
        if evaluation.stale and not any(item.code == "evaluation_stale" for item in found):
            found.append(
                Blocker(
                    code="evaluation_stale",
                    detail="the current evaluation is stale",
                    subject_type="evaluation",
                    subject_id=evaluation.id,
                )
            )
    else:
        facts = dict(application.submitted_facts or {})
        found.extend(service.site_blockers(application))
        found.extend(service.credential_blockers(application, facts, utc_now()))
        found.extend(service.identity_link_blockers(application))
        found.extend(service.finance_link_blockers(application))
    decision = service.current_decision(application.id)
    if (
        decision is not None
        and decision.outcome == "approved"
        and application.status == "approved"
    ):
        for item in PermitIssuanceService(session).blockers(application, decision):
            if item.code == "no_current_assessment" or item.code.startswith("reconciliation_"):
                found.append(item)
    seen: set[tuple[str, str, str]] = set()
    guides: list[dict[str, str]] = []
    for item in found:
        key = (item.code, item.subject_id or "", item.detail)
        if key in seen:
            continue
        seen.add(key)
        guides.append(blocker_guide(session, application, item))
    return guides


#: Findings the applicant can clear. A city-only judgment is not one of them.
APPLICANT_FIX_TYPES = frozenset(
    {"missing_field", "missing_document", "unreadable", "wrong_type", "duplicate"}
)


def information_request_text(findings: list[dict[str, Any]]) -> str:
    """Return the request a reviewer would send for these open findings."""
    lines = [
        sentence
        for row in findings
        if (sentence := _request_sentence(row))
    ]
    return "\n\n".join(lines)


def information_request_preset(
    status: str, findings: list[dict[str, Any]]
) -> dict[str, str] | None:
    """Return the decision-form defaults for a needs-information case.

    A case already in needs information, or one with an open finding the
    applicant must fix, opens on that outcome.  Anything else keeps Approve.
    """
    text = information_request_text(findings)
    if status != "needs_information" and not text:
        return None
    return {"outcome": "information_requested", "text": text}


def _request_sentence(row: dict[str, Any]) -> str:
    """Return one plain sentence for a finding the applicant must fix."""
    if row.get("state") != "current" or row.get("waived"):
        return ""
    kind = str(row.get("finding_type") or "")
    if kind not in APPLICANT_FIX_TYPES:
        return ""
    message = str(row.get("message") or "").strip()
    citation = _citation(str(row.get("rule") or ""))
    if kind == "duplicate":
        number = _case_number(message) or _case_number(str(row.get("applicant_must") or ""))
        if not number:
            return ""
        return (
            "This looks like a second application for the same project as "
            f"{number}. Please confirm whether it replaces that one."
        )
    if not str(row.get("applicant_must") or "").strip():
        return ""
    label = _subject_label(message)
    if kind == "missing_document" and label and citation:
        return f"Please upload the {label} ({citation})."
    if kind == "missing_field" and label and citation:
        return f"Please state the {label} ({citation})."
    must = str(row.get("applicant_must") or "").strip().rstrip(".")
    if must and citation:
        return f"{must} ({citation})."
    return must


def _citation(rule: str) -> str:
    """Return the code citation without the permit-type note."""
    text = rule.strip()
    if " (" in text:
        return text.split(" (", 1)[0].strip()
    return text


def _subject_label(message: str) -> str:
    """Return the thing a completeness finding says is missing."""
    included = re.search(r"does not include the (.+?)\.", message, re.I)
    if included:
        return included.group(1).strip()
    stated = re.search(r"does not state (.+?)\.", message, re.I)
    if stated:
        return stated.group(1).strip()
    return ""


def _case_number(text: str) -> str:
    """Return the other application's number named in a duplicate finding."""
    named = re.search(r"\bin ([A-Za-z0-9][A-Za-z0-9_-]*)\b", text)
    if named:
        return named.group(1)
    named = re.search(r"\bof ([A-Za-z0-9][A-Za-z0-9_-]*)\b", text)
    return named.group(1) if named else ""


def workspace_extras(
    session: Session,
    actor: Any,
    application: permit.Application,
    detail: dict[str, Any],
    return_from: str | None = None,
) -> dict[str, Any]:
    """Return the reviewer-facing facts the workspace tabs show."""
    from acme_city.ui import view_models

    label_workspace(session, detail)
    type_label = detail["permit_type"]["label"]
    revision_number = detail["submitted"]["revision_number"]
    blockers = list(detail.get("blockers") or [])
    issued = bool(detail.get("issued")) or application.status == "issued"
    issues = [
        {
            "code": b["code"],
            "label": issue_label(b["code"]),
            "detail": b["detail"],
            "kind": "checks" if b["code"] in CHECK_CODES else "data",
        }
        for b in blockers
    ]
    decision = detail.get("current_decision")
    assessment = (detail.get("finance") or {}).get("assessment")
    empty_stages = []
    if not decision:
        empty_stages.append("Decision: Not recorded")
    if not assessment:
        empty_stages.append("Fee: Not assessed")
    if not detail.get("issued"):
        empty_stages.append("Permit: Not issued")
    issuance_status, issuance_next = _issuance_words(detail, blockers)
    review_target = view_models.holds_grant(session, actor, "permit.decide", "permits")
    back_href, back_label = workspace_return(session, actor, return_from)
    return {
        "header": {
            "reference": application.source_application_number,
            "project_type": type_label,
            "applicant_name": applicant_name(session, application),
            "address": address_with_unit(session, application),
            "submitted_address": submitted_address(session, application),
            "revision": revision_number,
            "stage": stage_label(application.status),
            "back_href": back_href,
            "back_label": back_label,
        },
        "issues": issues,
        "issued": issued,
        "follow_up": issues if issued else [],
        "outstanding": [] if issued else issues,
        "empty_stages": empty_stages,
        "stage_decision": bool(decision),
        "stage_fee": bool(assessment),
        "stage_permit": bool(detail.get("issued")),
        "issuance_status": issuance_status,
        "issuance_next": issuance_next,
        "ai": _ai_summary(detail),
        "revisions": _revision_rows(session, application),
        "decision_record": "Recommendation" if not review_target else "Decision",
        "blocker_guides": workspace_blocker_guides(session, application),
        "data_follow_up": _data_follow_up_open(session, application),
        "information_request": information_request_preset(
            application.status, list(detail.get("findings") or [])
        ),
    }


# --- Review queue: where the case is, and what is needed now -----------------
#
# Stage is the life-cycle place of the recorded status. Next action is what
# that status and its blockers need now. Neither writes a record.

#: How many places the main path shows.
STAGE_TOTAL = 6

#: The stage text a case at Checks shows. Help quotes this literal.
STAGE_EXAMPLE = "Checks (3 of 6)"

#: Status to (stage key, label, 1-based position). Off this map, the life
#: cycle's own label is used and the track is omitted.
#: ``revisions_requested`` shares Decision with ``under_review``: the
#: applicant was sent back from review, so the case is still at the decision.
_PATH_STAGES: dict[str, tuple[str, str, int]] = {
    "submitted": ("submitted", "Submitted", 1),
    "needs_information": ("records_matching", "Records matching", 2),
    "ready_for_review": ("checks", "Checks", 3),
    "revisions_requested": ("decision", "Decision", 4),
    "under_review": ("decision", "Decision", 4),
    "approved": ("fee", "Fee", 5),
    "issued": ("issued", "Issued", 6),
}

#: The six statuses whose life-cycle order is the six steps, first to last.
STAGE_PATH: tuple[str, ...] = (
    "submitted",
    "needs_information",
    "ready_for_review",
    "under_review",
    "approved",
    "issued",
)

#: Only these two codes mean the Data Steward still has to approve a link.
#: ``parcel_unconfirmed`` is the reviewer's own confirmation.
STEWARD_CODES = frozenset({"identity_link_unapproved", "parcel_link_unapproved"})

#: A missing or stale evaluation means the checks have to be run again.
_CHECK_AGAIN = frozenset({"no_current_evaluation", "evaluation_stale"})

#: Filter chips, in display order. Ready to decide and Ready to issue are first.
NEXT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("ready_to_decide", "Ready to decide"),
    ("ready_to_issue", "Ready to issue"),
    ("waiting_on_steward", "Waiting on Data Steward"),
    ("needs_checks", "Needs checks"),
    ("fee_not_settled", "Fee not settled"),
    ("early_resolution", "In early resolution"),
    ("submitted_issues", SUBMITTED_WITH_KNOWN_ISSUES),
    ("waiting_for_applicant", "Waiting for the applicant"),
    ("decision_recorded", "Decision recorded"),
    ("issued", "Issued"),
    ("returned", "Returned"),
    ("withdrawn", "Withdrawn"),
    ("archived", "Archived"),
)
NEXT_ACTION_LABELS: dict[str, str] = dict(NEXT_ACTIONS)
NEXT_ACTION_KEYS = frozenset(NEXT_ACTION_LABELS)

_SORT_RANK = {"ready_to_decide": 0, "ready_to_issue": 1}


def _life_cycle_label(status: str) -> str:
    """Return the life-cycle page's own label for a status."""
    from acme_city.permits.lifecycle_map import STATUSES

    for item in STATUSES:
        if item.key == status:
            return item.label
    if not status:
        return "Unknown"
    return status.replace("_", " ").capitalize()


def stage_of(status: str) -> dict[str, Any]:
    """Return the life-cycle place of one recorded status.

    The place depends only on the status. Blockers change the next action,
    not where the case sits.
    """
    mapped = _PATH_STAGES.get(status or "")
    if mapped is None:
        key, label, position = status or "unknown", _life_cycle_label(status), 0
    else:
        key, label, position = mapped
    text = f"{label} ({position} of {STAGE_TOTAL})" if position else label
    return {
        "stage_key": key,
        "stage_label": label,
        "stage_position": position,
        "stage_total": STAGE_TOTAL,
        "stage_text": text,
    }


def _known_issues(application: permit.Application) -> bool:
    """Return whether the applicant submitted anyway with a reason.

    The same gate as the permit workspace flag: a presubmit override dict
    with a non-blank reason.
    """
    raw = application.presubmit_override
    if not isinstance(raw, dict):
        return False
    reason = " ".join(str(raw.get("reason") or "").split())
    return bool(reason)


def _steward(blockers: list[Any]) -> bool:
    """Return whether a blocker list still waits on the Data Steward."""
    return any(blocker.code in STEWARD_CODES for blocker in blockers)


def _fee_open(finance_service: Any, application: permit.Application) -> bool:
    """Return whether an approved case still has a fee to settle.

    No assessment, a balance other than 0.00, or a reconciliation that is
    not exact. The read does not write a reconciliation row.
    """
    assessment = finance_service.current_assessment(application.id)
    if assessment is None:
        return True
    reconciliation = finance_service.compute_reconciliation(assessment, persist=False)
    if reconciliation.balance_cents != 0:
        return True
    return reconciliation.status != "exact"


def _open_blockers(
    application: permit.Application, permits: Any, decisions: Any
) -> tuple[Any, list[Any]]:
    """Return the current evaluation and the blockers the decision path uses.

    A current evaluation goes through ``PermitDecisionService.blockers``.
    With no evaluation, or a stale one, the same permit-service reads that
    method calls are used: site, identity (which includes the parcel link)
    and finance.
    """
    evaluation = permits.current_evaluation(application.id)
    if evaluation is not None and not evaluation.stale:
        return evaluation, decisions.blockers(application, evaluation)
    blockers: list[Any] = []
    blockers.extend(permits.site_blockers(application))
    blockers.extend(permits.identity_link_blockers(application))
    blockers.extend(permits.finance_link_blockers(application))
    return evaluation, blockers


def _approved_action(
    application: permit.Application,
    permits: Any,
    finance_service: Any,
    issuance: Any,
) -> str:
    """Return the next action of an approved case."""
    if _steward(permits.identity_link_blockers(application)):
        return "waiting_on_steward"
    if _fee_open(finance_service, application):
        return "fee_not_settled"
    decision = permits.current_decision(application.id)
    if decision is None:
        return "ready_to_decide"
    blockers = issuance.blockers(application, decision)
    if _steward(blockers):
        return "waiting_on_steward"
    if not blockers:
        return "ready_to_issue"
    codes = {blocker.code for blocker in blockers}
    if codes & _CHECK_AGAIN:
        return "needs_checks"
    return "ready_to_decide"


def _next_action_key(
    application: permit.Application,
    permits: Any,
    decisions: Any,
    finance_service: Any,
    issuance: Any,
) -> str:
    """Return the key of the one next action.

    An approved case is on the fee and issue path before the presubmit flag
    is considered, so an approval is not labelled as submitted with known
    issues. On every earlier status that flag wins, including over an
    unapproved steward link: it is the phrase the reviewer sees when the
    applicant submitted anyway.
    """
    status = application.status
    if status == "issued":
        return "issued"
    if status == "archived":
        return "archived"
    if status == "withdrawn":
        return "withdrawn"
    if status == "returned":
        return "returned"
    if status == "revisions_requested":
        return "waiting_for_applicant"
    if status == "denied":
        return "decision_recorded"
    if status == "approved":
        return _approved_action(application, permits, finance_service, issuance)
    if _known_issues(application):
        return "submitted_issues"
    evaluation, blockers = _open_blockers(application, permits, decisions)
    if _steward(blockers):
        return "waiting_on_steward"
    if status == "needs_information":
        return "early_resolution"
    if evaluation is None or evaluation.stale:
        return "needs_checks"
    from acme_city.permits.decisions import DECIDABLE_STATUSES

    if status in DECIDABLE_STATUSES:
        return "ready_to_decide"
    return "needs_checks"


def queue_place(session: Session, application: permit.Application) -> dict[str, Any]:
    """Return the stage and the next action of one case.

    Read-only. The services are the ones the decision and issuance paths
    already use. Nothing here evaluates, decides, issues or submits.
    """
    from acme_city.finance.service import FinanceService
    from acme_city.permits.decisions import PermitDecisionService
    from acme_city.permits.issuance import PermitIssuanceService
    from acme_city.permits.service import PermitService

    permits = PermitService(session)
    stage = stage_of(application.status)
    key = _next_action_key(
        application,
        permits,
        PermitDecisionService(session),
        FinanceService(session),
        PermitIssuanceService(session),
    )
    stage["next_action_key"] = key
    stage["next_action"] = NEXT_ACTION_LABELS[key]
    return stage


def review_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    """Sort ready to decide, then ready to issue, then the older cases first."""
    rank = _SORT_RANK.get(str(row.get("next_action_key") or ""), 2)
    age = row.get("age_days")
    try:
        age_value = int(age) if age is not None else 0
    except (TypeError, ValueError):
        age_value = 0
    return (rank, -age_value, str(row.get("reference") or ""))


def _review_href(area: str, action: str, query: str = "", tag: str = "") -> str:
    """Return a review-queue address that keeps the area, the action, the search and the tag."""
    from acme_city.ui.queue_find import review_href

    return review_href(area, action, query, tag)


def present_review_queue(
    session: Session,
    queue: dict[str, Any],
    next_action: str = "",
    query: str = "",
    page: int = 1,
    tag: str = "",
    page_size: int | str | None = None,
) -> dict[str, Any]:
    """Copy a review queue, then add stage, next action, chips, search and sort.

    Membership and area counts stay as the queue service returned them.
    The action filter and the sort happen here. An unknown action shows
    every row. Counts are taken after the area filter and before the
    action filter, so the selected chip's count is the number of rows
    in that action. The search runs after the chip and before the page,
    so a match is not dropped because it would have been on a later page.
    A recommendation tag narrows the same list and combines with both.
    ``page_size`` is how many rows one page shows. It comes from the request
    as an integer clamped to 1..500, and the page links keep it.
    """
    from acme_city.ui.queue_find import (
        matches_query,
        normalize_query,
        page_size_of,
        paginate,
        paging_links,
        search_summary,
        sole_open,
    )
    from acme_city.ui.queue_tags import load_tags, normalize_tag, tag_chips

    presented = dict(queue)
    area = str(queue.get("area") or "")
    selected = next_action if next_action in NEXT_ACTION_KEYS else ""
    text = normalize_query(query)
    annotated: list[dict[str, Any]] = []
    for source in queue.get("rows") or []:
        row = dict(source)
        application_id = row.get("application_id")
        application = (
            session.get(permit.Application, application_id) if application_id else None
        )
        if application is None:
            place = stage_of(str(row.get("status") or ""))
            place["next_action_key"] = "needs_checks"
            place["next_action"] = NEXT_ACTION_LABELS["needs_checks"]
        else:
            place = queue_place(session, application)
        row.update(place)
        annotated.append(row)
    tagged = load_tags(
        session,
        [
            (str(row.get("application_id") or ""), str(row.get("status") or ""))
            for row in annotated
        ],
    )
    for row in annotated:
        row["tags"] = tagged.get(str(row.get("application_id") or ""), [])
    chosen = normalize_tag(tag)
    counts: dict[str, int] = {}
    for row in annotated:
        key = str(row["next_action_key"])
        counts[key] = counts.get(key, 0) + 1
    chips = [
        {
            "key": key,
            "label": label,
            "count": counts[key],
            "href": _review_href(area, key, text, chosen),
        }
        for key, label in NEXT_ACTIONS
        if counts.get(key, 0) > 0
    ]
    visible = annotated
    if selected:
        visible = [row for row in annotated if row["next_action_key"] == selected]
    # Tag counts stay on this list, before the tag itself and before the search.
    tag_all_count = len(visible)
    recommendation_chips = tag_chips(
        [list(row.get("tags") or []) for row in visible],
        lambda key: _review_href(area, selected, text, key),
    )
    if chosen:
        visible = [
            row
            for row in visible
            if any(item["key"] == chosen for item in row.get("tags") or [])
        ]
    if text:
        visible = [
            row
            for row in visible
            if matches_query(
                str(row.get("reference") or ""),
                str(row.get("applicant_name") or ""),
                str(row.get("address") or ""),
                text,
            )
        ]
    visible.sort(key=review_row_sort_key)
    back = _review_href(area, selected, text, chosen)
    size = page_size_of(page_size)
    shown, paging = paginate(visible, page, size)
    paging.update(paging_links(back, paging["page"], paging["pages"], size))
    names = list(queue.get("areas") or [])
    presented["area_hrefs"] = {"": _review_href("", selected, text, chosen)}
    for name in names:
        presented["area_hrefs"][name] = _review_href(str(name), selected, text, chosen)
    presented["rows"] = shown
    presented["next_action"] = selected
    presented["next_all_href"] = _review_href(area, "", text, chosen)
    presented["next_all_count"] = len(annotated)
    presented["next_actions"] = chips
    presented["tag"] = chosen
    presented["tag_filters"] = recommendation_chips
    presented["tag_all_href"] = _review_href(area, selected, text, "")
    presented["tag_all_count"] = tag_all_count
    presented["query"] = text
    presented["search_summary"] = search_summary(len(visible), text) if text else ""
    presented["clear_href"] = _review_href(area, selected, "", chosen)
    presented["sole"] = sole_open(visible, text, back)
    presented["paging"] = paging
    presented["match_total"] = len(visible)
    return presented


def _data_follow_up_open(session: Session, application: permit.Application) -> bool:
    """Return whether a parcel or identity link is still open on the case."""
    from acme_city.permits.decisions import DATA_FOLLOW_UP_CODES
    from acme_city.permits.service import PermitService

    return any(
        item.code in DATA_FOLLOW_UP_CODES
        for item in PermitService(session).identity_link_blockers(application)
    )

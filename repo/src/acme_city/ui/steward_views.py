"""View models of the Data Steward screens.

The steward has four work areas: Data issues, Master records, Source records
and Activity.  This module builds what those screens show, and registers the
detail drawer kinds they open (record profiles, source details, credentials,
parcels, evidence and related applications).

Every view model reads what the services recorded and decides nothing.  A
drawer kind is registered through ``patterns.register_detail`` with the grants
of the screen it belongs to; its resolver does the record-level checks, so a
persona outside the grants gets 403 and a record outside the scope gets 404,
and neither answer carries a value.
"""
# REQUIRES: UX-01, UX-02, SEC-01, MDM-02, MDM-03
# The steward screens use readable values, keep record status, credential
# status and data issue apart, explain every match by its evidence before any
# score, and preview what an action will do before it is pressed.

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.core.clock import app_now
from acme_city.fixtures.loader import REPO_ROOT
from acme_city.ingestion.normalization import (
    normalize_address,
    normalize_email,
    normalize_identifier,
    normalize_name,
    normalize_phone,
    normalize_text,
)
from acme_city.persistence.models import (
    audit,
    change,
    gis,
    governance,
    model_run,
    permit,
    registry,
    source,
)
from acme_city.registry.candidates import (
    CONFLICTING_WEIGHTS,
    SUPPORTING_WEIGHTS,
    generate_candidates,
    entity_target_for,
)
from acme_city.registry.provenance import affected_dependents, current_accepted_snapshot
from acme_city.ui import display, patterns, property_views, steward_queue_views, view_models
from acme_city.ui.patterns import DetailContext, DetailForbidden, DetailView, Row, Section

PAGE_SIZE = 50

#: The datasets whose records a steward can link to a master record.
LINKABLE_DATASETS = frozenset(
    {
        "applicant_profiles",
        "applications_and_permits",
        "business_licensing_register",
        "contractor_register",
        "finance_accounts",
        "parcel_register",
        "address_register",
    }
)

#: The statuses of a link that mean a steward has decided it.
DECIDED_LINKS = ("approved", "rejected", "no_match", "removed")

#: Change-case states that wait for a person, for the source, or are finished.
CASE_NEEDS_REVIEW = ("requested", "in_review", "awaiting_approval")
CASE_AWAITING_SOURCE = ("approved", "sent_to_source", "source_acknowledged", "synchronization_failed")
CASE_RESOLVED = ("registry_committed", "published", "closed", "rejected")

#: The four filters of the Data issues queue, in order.  The queue module
#: owns them; the names stay here for the screens that already read them.
QUEUE_FILTERS: tuple[tuple[str, str], ...] = steward_queue_views.QUEUE_FILTERS

#: The label of each state of a task.
STATUS_LABELS: dict[str, str] = steward_queue_views.STATUS_LABELS

#: What the steward does next in a focused case that is still open.
OPEN_NEXT_STEPS: dict[str, str] = {
    "link": "Compare the record with each candidate, then confirm the link, reject it or defer it.",
    "linked": "Open the master record to see where each value came from.",
    "parcel": "Compare the submitted address with the parcel, then approve or reject the link.",
    "case": "Move the case to the next state, or wait for the source to answer.",
    "issue": "Resolve the recorded issue so the work it blocks can continue.",
}

#: What the steward does next in a focused case that is finished.
CLOSED_NEXT_STEPS: dict[str, str] = {
    "link": "The link is decided. Open the master record to see where each value came from.",
    "linked": "The link is decided. Open the master record to see where each value came from.",
    "parcel": "The parcel link is decided. The Permit Reviewer still confirms the parcel.",
    "case": "The case is closed. Open the record to see what the source answered.",
    "issue": "The issue is closed. Open the record to see what changed.",
}

#: The four collections of Master records, in tab order.
MASTER_TABS: tuple[tuple[str, str], ...] = (
    ("people", "People & organizations"),
    ("properties", "Properties"),
    ("licenses", "Business licenses"),
    ("registrations", "Contractor registrations"),
)

#: The families of record a focused case can compare.
COMPARISON_FAMILIES: tuple[str, ...] = ("party", "parcel", "address")

#: The order the rows of a comparison are read in: what disagrees first,
#: then what is missing on one side, and only then what agrees.
COMPARISON_ORDER: tuple[str, ...] = ("conflicts", "no_comparison", "agrees")

#: The link states of the source-record catalogue, and the label each one
#: carries.  The action a record asks for follows from its state.
SOURCE_LINK_STATES: dict[str, tuple[str, str]] = {
    "not_compared": ("Not compared", "Find matches"),
    "proposed": ("Match proposed", "Review match"),
    "linked": ("Linked", "View master record"),
    "decided": ("No suitable match", "Review next step"),
    "not_linkable": ("Not a master record", ""),
}

#: Grants that open the drawer kinds (the same predicate as the screens).
RECORD_GRANTS: tuple[tuple[str, str | None], ...] = view_models.SCREEN_PERMISSIONS["applicants"]
MASTER_GRANTS: tuple[tuple[str, str | None], ...] = view_models.SCREEN_PERMISSIONS["masters"]
STEWARD_GRANTS: tuple[tuple[str, str | None], ...] = view_models.SCREEN_PERMISSIONS["steward"]
SOURCE_DOMAINS = ("applicants", "parcels", "businesses", "contractors", "finance", "permits")
SOURCE_GRANTS: tuple[tuple[str, str | None], ...] = tuple(
    ("registry.provenance.view", domain) for domain in SOURCE_DOMAINS
)


# ---------------------------------------------------------------- small helpers


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _norm(value: Any) -> str:
    """Return a comparison key: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _pretty_action(action: str) -> str:
    names = _display_config().get("audit_actions", {})
    if action in names:
        return str(names[action])
    text = action.replace("ui.", "").replace(".", " ").replace("_", " ")
    return text[:1].upper() + text[1:]


def _display_config() -> dict[str, Any]:
    return dict(json.loads(Path(display.DISPLAY_PATH).read_text(encoding="utf-8")))


def _evidence_phrase(method: str) -> str:
    return str(_display_config().get("evidence_methods", {}).get(method, method.replace("_", " ")))


def _synthetic_ids(session: Session) -> set[str]:
    """Return the ids of the generated historical records (never steward work)."""
    ids: set[str] = set()
    ids.update(
        session.execute(select(registry.Party.id).where(registry.Party.synthetic.is_(True))).scalars()
    )
    ids.update(
        session.execute(
            select(permit.Application.id).where(permit.Application.synthetic.is_(True))
        ).scalars()
    )
    ids.update(
        session.execute(
            select(registry.CanonicalEntity.entity_id).where(
                registry.CanonicalEntity.synthetic.is_(True)
            )
        ).scalars()
    )
    return ids


def _party_label(session: Session, party_id: str | None, cache: dict[str, str] | None = None) -> str:
    if not party_id:
        return "Not named"
    if cache is not None and party_id in cache:
        return cache[party_id]
    party = session.get(registry.Party, party_id)
    label = party.display_name if party is not None else display.pretty(party_id)
    if cache is not None:
        cache[party_id] = label
    return label


def _party_type(session: Session, party_id: str | None) -> str:
    """Return the type of a party, so the queue can name the task it asks for."""
    if not party_id:
        return ""
    party = session.get(registry.Party, party_id)
    return party.party_type if party is not None else ""


def _age_label(since: datetime | None) -> str:
    return steward_queue_views.age_label(since)


def _page(rows: list[Any], page: int) -> tuple[list[Any], dict[str, Any]]:
    total = len(rows)
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * PAGE_SIZE
    return rows[start : start + PAGE_SIZE], {
        "page": page,
        "pages": pages,
        "total": total,
        "first": start + 1 if total else 0,
        "last": min(start + PAGE_SIZE, total),
    }


def _href(path: str, **params: str | int | None) -> str:
    pairs = {key: value for key, value in params.items() if value not in (None, "", 1, "all")}
    query = urlencode(pairs)
    return f"{path}?{query}" if query else path


# ------------------------------------------------------- freshness (config only)


def freshness_warning(
    system_id: str | None,
    dataset_key: str | None,
    last_checked: datetime | None,
    *,
    contracts: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> str:
    """Return a freshness warning only when the config states a refresh expectation.

    A source contract may carry ``refresh_expectation_days``.  No contract
    does today, so no warning is ever shown unless one is configured.
    """
    if contracts is None:
        path = REPO_ROOT / "config" / "source_contracts.json"
        contracts = list(json.loads(path.read_text(encoding="utf-8")).get("source_contracts", []))
    for contract in contracts:
        if contract.get("source_system_id") != system_id or contract.get("dataset_key") != dataset_key:
            continue
        days = contract.get("refresh_expectation_days")
        if not days or last_checked is None:
            return ""
        age = ((now or app_now()) - last_checked).days
        if age > int(days):
            return f"Last checked {age} days ago; the source is expected to refresh every {int(days)} days."
    return ""


def source_summary(
    session: Session,
    system_id: str | None,
    dataset_key: str | None,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Return Source, Source last changed, Last received or checked and the details address."""
    changed, received = view_models.source_times(session, system_id, dataset_key, record_id)
    detail_id = ":".join(item for item in (system_id, dataset_key, record_id) if item) if system_id else ""
    return {
        "name": display.source_name(session, system_id, dataset_key),
        "changed": _iso(changed),
        "received": _iso(received),
        "detail_id": detail_id,
        "warning": freshness_warning(system_id, dataset_key, received),
        "record_id": record_id or "",
    }


# ---------------------------------------------------------------- party helpers


def _open_issue_counts(session: Session) -> dict[str, list[str]]:
    """Return the open issues per record: governance issues, cases and waiting matches."""
    found: dict[str, list[str]] = defaultdict(list)
    for row in session.execute(
        select(change.GovernanceIssue).where(change.GovernanceIssue.status == "open")
    ).scalars():
        found[row.subject_id].append(row.description)
    for row in session.execute(
        select(change.ChangeCase).where(change.ChangeCase.status.notin_(("closed", "rejected", "published")))
    ).scalars():
        found[row.target_id].append(row.title)
    decided = {
        (row.source_system_id, row.source_record_id)
        for row in session.execute(
            select(registry.Crosswalk).where(registry.Crosswalk.link_status.in_(DECIDED_LINKS))
        ).scalars()
    }
    snapshots = {
        row.source_snapshot_id: row
        for row in session.execute(select(source.SourceSnapshot)).scalars()
    }
    for proposal in session.execute(select(registry.MatchProposal)).scalars():
        snap = snapshots.get(proposal.source_snapshot_id)
        if snap is None or (snap.source_system_id, snap.source_record_id) in decided:
            continue
        for candidate in proposal.candidate_ids or []:
            found[str(candidate)].append(
                f"Source record {snap.source_record_id} may match this record"
            )
    return found


def _primary_contact(contacts: list[registry.PartyContact]) -> str:
    current = [row for row in contacts if row.valid_to is None] or contacts
    for kind in ("email", "phone"):
        for row in current:
            if row.contact_type == kind:
                return row.value
    return current[0].value if current else ""


def people_collection(
    session: Session,
    actor: ActorContext,
    *,
    kind: str = "all",
    query: str = "",
    page: int = 1,
    base_path: str = "/masters",
) -> dict[str, Any]:
    """Return the People & organizations collection."""
    parties = view_models.visible_parties(session, actor)
    ids = {party.id for party in parties}
    aliases: dict[str, list[str]] = defaultdict(list)
    for row in session.execute(select(registry.PartyAlias)).scalars():
        if row.party_id in ids:
            aliases[row.party_id].append(row.alias_value)
    contacts: dict[str, list[registry.PartyContact]] = defaultdict(list)
    for row in session.execute(select(registry.PartyContact)).scalars():
        if row.party_id in ids:
            contacts[row.party_id].append(row)
    counts: dict[str, int] = defaultdict(int)
    for owner in session.execute(select(permit.Application.applicant_party_id)).scalars():
        if owner in ids:
            counts[str(owner)] += 1
    issues = _open_issue_counts(session)
    needle = query.strip().lower()

    base: list[registry.Party] = []
    for party in parties:
        if needle:
            haystack = " ".join(
                [party.display_name, party.legal_name or ""] + aliases[party.id]
            ).lower()
            if needle not in haystack:
                continue
        base.append(party)
    totals = {
        "all": len(base),
        "people": sum(1 for party in base if party.party_type == "person"),
        "organizations": sum(1 for party in base if party.party_type == "organization"),
    }
    wanted = {"people": "person", "organizations": "organization"}.get(kind)
    chosen = [party for party in base if wanted is None or party.party_type == wanted]
    window, paging = _page(chosen, page)
    rows = []
    for party in window:
        relevant = ""
        if needle:
            relevant = next((alias for alias in aliases[party.id] if needle in alias.lower()), "")
        if not relevant and aliases[party.id]:
            relevant = sorted(aliases[party.id])[0]
        open_here = issues.get(party.id, [])
        rows.append(
            {
                "party_id": party.id,
                "name": party.display_name,
                "alias": relevant,
                "type": display.pretty(party.party_type),
                "contact": _primary_contact(contacts[party.id]),
                "applications": counts.get(party.id, 0),
                "attention": len(open_here),
                "attention_text": open_here[0] if open_here else "",
                "synthetic": bool(party.synthetic),
            }
        )
    filters = [
        {
            "key": key,
            "label": label,
            "count": totals[key],
            "active": kind == key or (key == "all" and kind not in ("people", "organizations")),
            "href": _href(base_path, tab="people" if base_path == "/masters" else None, kind=key, q=query),
        }
        for key, label in (("all", "All"), ("people", "People"), ("organizations", "Organizations"))
    ]
    return {"rows": rows, "filters": filters, "paging": paging, "query": query, "kind": kind}


def properties_collection(
    session: Session, actor: ActorContext, *, query: str = "", page: int = 1
) -> dict[str, Any]:
    """Return the Properties collection: the address leads, the parcel number reads plainly."""
    masters = view_models.masters(session, actor)
    needle = query.strip().lower()
    rows = []
    for parcel in masters["properties"]:
        official = [item for item in parcel["addresses"] if not item.get("unit_number")]
        units = sorted({str(item["unit_number"]) for item in parcel["addresses"] if item.get("unit_number")})
        lead = (official[0] if official else (parcel["addresses"][0] if parcel["addresses"] else None))
        address = lead["source_string"] if lead else "No official address"
        if needle and needle not in f"{address} {parcel['source_parcel_number']}".lower():
            continue
        rows.append(
            {
                "parcel_id": parcel["parcel_id"],
                "address": address,
                "parcel_number": parcel["source_parcel_number"],
                "units": units,
                "units_text": _join_units(units),
                "jurisdiction": display.pretty(parcel["jurisdiction_id"]),
                "status": display.pretty(parcel["status"]),
            }
        )
    window, paging = _page(rows, page)
    return {"rows": window, "paging": paging, "query": query}


def _join_units(units: list[str]) -> str:
    if not units:
        return ""
    if len(units) == 1:
        return f"Unit {units[0]}"
    return "Units " + ", ".join(units[:-1]) + " and " + units[-1]


def credentials_collection(
    session: Session,
    actor: ActorContext,
    *,
    credential_type: str,
    query: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """Return business licenses or contractor registrations.

    Three labels stay apart on every row: the record status of the person or
    organization, the status of the license or registration, and a data issue.
    """
    parties = {party.id: party for party in view_models.visible_parties(session, actor)}
    issues = _open_issue_counts(session)
    needle = query.strip().lower()
    rows = []
    for credential in session.execute(
        select(registry.Credential)
        .where(registry.Credential.credential_type == credential_type)
        .order_by(registry.Credential.number)
    ).scalars():
        party = parties.get(credential.holder_party_id)
        if party is None:
            continue
        if needle and needle not in f"{party.display_name} {credential.number}".lower():
            continue
        system_id, _, dataset = (credential.issuing_authority_id or "").partition(":")
        rows.append(
            {
                "party_id": party.id,
                "name": party.display_name,
                "record_status": display.pretty(party.status),
                "party_type": display.pretty(party.party_type),
                "credential_id": credential.credential_id,
                "number": credential.number,
                "status_key": credential.status,
                "status": display.pretty(credential.status),
                "valid_through": _iso(credential.valid_to),
                "category": display.pretty(credential.business_category) if credential.business_category else "",
                "source": display.issuer_name(session, credential.issuing_authority_id),
                "source_detail": ":".join(
                    item for item in (credential.source_system_id or system_id, dataset, credential.source_record_id) if item
                ),
                "issue_count": len(issues.get(party.id, [])),
                "synthetic": bool(credential.synthetic),
            }
        )
    window, paging = _page(rows, page)
    return {"rows": window, "paging": paging, "query": query}


# -------------------------------------------------------------- record profile


def open_issue_lines(session: Session, party_id: str) -> list[dict[str, str]]:
    """Return the open data issues of one record in plain words, with a link."""
    lines: list[dict[str, str]] = []
    for row in session.execute(
        select(change.GovernanceIssue).where(
            change.GovernanceIssue.subject_id == party_id, change.GovernanceIssue.status == "open"
        )
    ).scalars():
        lines.append({"text": row.description, "href": f"/steward/issues/issue/{row.id}"})
    for row in session.execute(
        select(change.ChangeCase).where(
            change.ChangeCase.target_id == party_id,
            change.ChangeCase.status.notin_(("closed", "rejected", "published")),
        )
    ).scalars():
        lines.append({"text": row.title, "href": f"/steward/issues/case/{row.id}"})
    snapshots = {
        row.source_snapshot_id: row
        for row in session.execute(select(source.SourceSnapshot)).scalars()
    }
    for proposal in session.execute(select(registry.MatchProposal)).scalars():
        snap = snapshots.get(proposal.source_snapshot_id)
        if snap is None or party_id not in (proposal.candidate_ids or []):
            continue
        if _decided_crosswalk(session, snap.source_system_id, snap.source_record_id) is not None:
            continue
        lines.append(
            {
                "text": f"Source record {snap.source_record_id} may match this record",
                "href": f"/steward/issues/link/{proposal.id}",
            }
        )
    return lines


def _decided_crosswalk(session: Session, system_id: str, record_id: str) -> registry.Crosswalk | None:
    rows = [
        row
        for row in session.execute(
            select(registry.Crosswalk).where(
                registry.Crosswalk.source_system_id == system_id,
                registry.Crosswalk.source_record_id == record_id,
                registry.Crosswalk.link_status.in_(DECIDED_LINKS),
            )
        ).scalars()
    ]
    if not rows:
        return None
    latest = max(rows, key=lambda row: (row.decided_at or row.created_at, row.version))
    # A link proposed again after the decision (for example after a removal) is open again.
    newer_proposal = session.execute(
        select(registry.Crosswalk).where(
            registry.Crosswalk.source_system_id == system_id,
            registry.Crosswalk.source_record_id == record_id,
            registry.Crosswalk.link_status == "proposed",
            registry.Crosswalk.created_at > (latest.decided_at or latest.created_at),
        )
    ).first()
    return None if newer_proposal is not None else latest


def record_profile(session: Session, actor: ActorContext, party_id: str) -> dict[str, Any]:
    """Return the record profile: identity, aliases, contacts, credentials, sources, history."""
    detail = view_models.party_detail(session, actor, party_id)
    if not detail:
        return {}
    party = session.get(registry.Party, party_id)
    assert party is not None
    credentials = []
    for item in detail["credentials"]:
        credentials.append(
            {
                **item,
                "type_label": display.pretty(item["credential_type"]),
                "status_label": display.pretty(item["status"]),
                "issuer_label": display.issuer_name(session, item["issuing_authority_id"]),
            }
        )
    applications = []
    for application in view_models._party_applications(session, party_id):
        if not view_models._application_in_scope(actor, application):
            continue
        applications.append(
            {
                "number": application.source_application_number,
                "status": display.pretty(application.status),
                "href": f"/permits/{application.id}",
                "synthetic": bool(application.synthetic),
            }
        )
    sources = []
    for link in detail["sources"]:
        sources.append(
            {
                "source": display.source_name(
                    session, link["source_system_id"], link.get("source_dataset_key")
                ),
                "record_id": link["source_record_id"],
                "status_key": link["link_status"],
                "status": display.pretty(link["link_status"]),
                "decided_by": view_models.actor_label(session, link.get("decision_actor_id")),
                "decided_at": link.get("decided_at"),
                "decision": link.get("decision") or "",
                "detail_id": ":".join(
                    item
                    for item in (
                        link["source_system_id"],
                        link.get("source_dataset_key") or "",
                        link["source_record_id"],
                    )
                    if item
                ),
            }
        )
    extra_ids = sorted(
        {item["source_record_id"] for item in detail["sources"]} - {party_id}
    )
    history = list(detail["history"])
    if extra_ids:
        for row in session.execute(
            select(audit.AuditEvent)
            .where(audit.AuditEvent.target_id.in_(extra_ids))
            .order_by(audit.AuditEvent.occurred_at.desc())
        ).scalars():
            history.append(view_models._history_entry(session, row))
        history.sort(key=lambda entry: entry["occurred_at"] or "", reverse=True)
    linked = next((item for item in detail["sources"] if item["link_status"] == "approved"), None)
    summary = (
        source_summary(
            session, linked["source_system_id"], linked.get("source_dataset_key"), linked["source_record_id"]
        )
        if linked
        else source_summary(session, "permitting", "applicant_profiles")
    )
    issues = open_issue_lines(session, party_id)
    trusted_values = [
        field for field in detail["trusted_fields"] if field.get("value") is not None
    ]
    credential_states = sorted({item["status_label"] for item in credentials})
    return {
        "detail": detail,
        "party": party,
        "name": party.display_name,
        "legal_name": party.legal_name or "",
        "type": display.pretty(party.party_type),
        "record_status": display.pretty(party.status),
        "aliases": [item["value"] for item in detail["current"]["aliases"]],
        "contacts": detail["current"]["contacts"],
        "credentials": credentials,
        "applications": applications,
        "issues": issues,
        "trusted_values": trusted_values,
        "identity_status": "Open data issue" if issues else "No open identity issue",
        "credential_status": ", ".join(credential_states) or "No credential recorded",
        "sources": sources,
        "source_summary": summary,
        "history": history,
        "responsibility": detail["responsibility"],
    }


def _can_open_master(session: Session, actor: ActorContext) -> bool:
    return any(view_models.holds_grant(session, actor, p, d) for p, d in MASTER_GRANTS)


def _record_tabs(party_id: str, active: str) -> tuple[tuple[str, str, str, bool], ...]:
    return (
        ("Overview", "record", party_id, active == "record"),
        ("Sources", "record-sources", party_id, active == "record-sources"),
        ("History", "record-history", party_id, active == "record-history"),
    )


def _profile_or_none(ctx: DetailContext, party_id: str) -> dict[str, Any] | None:
    profile = record_profile(ctx.session, ctx.actor, party_id)
    return profile or None


def _resolve_record(ctx: DetailContext, party_id: str) -> DetailView | None:
    profile = _profile_or_none(ctx, party_id)
    if profile is None:
        return None
    party_rows = [
        Row("Name", profile["name"]),
        Row("Type", profile["type"]),
        Row("Record status", profile["record_status"], info="party_record_status"),
    ]
    if profile["legal_name"] and profile["legal_name"] != profile["name"]:
        party_rows.insert(1, Row("Legal name", profile["legal_name"]))
    sections = [Section("Identity", tuple(party_rows))]
    if profile["aliases"]:
        sections.append(Section("Aliases", lines=tuple(profile["aliases"])))
    contact_rows = tuple(
        Row(display.pretty(item["contact_type"]), item["value"]) for item in profile["contacts"]
    )
    sections.append(
        Section("Contacts", contact_rows)
        if contact_rows
        else Section("Contacts", lines=("No contact is recorded.",))
    )
    if profile["credentials"]:
        sections.append(
            Section(
                "Licenses and registrations",
                tuple(
                    Row(
                        f"{item['type_label']} {item['number']}",
                        f"{item['status_label']}"
                        + (f", valid through {display.readable_date(item['valid_to'])}" if item["valid_to"] else ""),
                        info="license_status",
                    )
                    for item in profile["credentials"]
                ),
            )
        )
    related = tuple(
        Row(item["number"], item["status"]) for item in profile["applications"] if not item["synthetic"]
    )
    sections.append(
        Section("Related applications", related)
        if related
        else Section("Related applications", lines=("No application names this record.",))
    )
    issue_lines = tuple(item["text"] for item in profile["issues"])
    sections.append(
        Section("Data issues", lines=issue_lines)
        if issue_lines
        else Section("Data issues", lines=("No open data issue.",))
    )
    summary = profile["source_summary"]
    sections.append(
        Section(
            "Source",
            (
                Row("Source", summary["name"]),
                Row("Source last changed", display.readable_date(summary["changed"]) or "unknown", info="source_last_changed"),
                Row("Last received or checked", display.readable_date(summary["received"]) or "unknown"),
            ),
        )
    )
    links = [("Open the full profile page", f"/masters/{party_id}" if _can_open_master(ctx.session, ctx.actor) else f"/applicants/{party_id}")]
    if summary["detail_id"]:
        links.append(("View source details", f"?detail=source:{summary['detail_id']}"))
    return DetailView(
        title=profile["name"],
        subtitle=f"{profile['type']} · Overview",
        sections=tuple(sections),
        links=tuple(links),
        tabs=_record_tabs(party_id, "record"),
    )


def _resolve_record_sources(ctx: DetailContext, party_id: str) -> DetailView | None:
    profile = _profile_or_none(ctx, party_id)
    if profile is None:
        return None
    sections: list[Section] = []
    if profile["sources"]:
        sections.append(
            Section(
                "Where each value came from",
                tuple(
                    Row(
                        item["source"],
                        f"{item['record_id']} · {item['status']}"
                        + (f" · decided by {item['decided_by']}" if item["status_key"] != "proposed" else " · waiting for a decision")
                        + (f" on {display.readable_date(item['decided_at'])}" if item["decided_at"] else ""),
                        mono=False,
                    )
                    for item in profile["sources"]
                ),
            )
        )
    else:
        sections.append(Section("Where each value came from", lines=("No source record is linked to this record yet.",)))
    trusted = [item for item in profile["detail"]["trusted_fields"] if item["value"] is not None]
    if trusted:
        sections.append(
            Section(
                "Values the policy trusts",
                tuple(
                    Row(
                        display.pretty(item["attribute_path"]),
                        f"{item['value'] if item['value'] is not None else 'No value'}"
                        f" · {display.pretty(item.get('source_system_id') or 'not declared')}",
                    )
                    for item in trusted
                ),
            )
        )
    summary = profile["source_summary"]
    links = []
    if summary["detail_id"]:
        links.append(("View source details", f"?detail=source:{summary['detail_id']}"))
    return DetailView(
        title=profile["name"],
        subtitle=f"{profile['type']} · Sources",
        sections=tuple(sections),
        links=tuple(links),
        tabs=_record_tabs(party_id, "record-sources"),
    )


def _resolve_record_history(ctx: DetailContext, party_id: str) -> DetailView | None:
    profile = _profile_or_none(ctx, party_id)
    if profile is None:
        return None
    history = [item for item in profile["history"] if not item["action"].startswith("ui.")]
    rows = tuple(
        Row(
            display.readable_date(item["occurred_at"]) or "unknown",
            f"{_pretty_action(item['action'])} · {item['actor_label']}"
            + (f" · {item['reason']}" if item.get("reason") else ""),
        )
        for item in history[:40]
    )
    return DetailView(
        title=profile["name"],
        subtitle=f"{profile['type']} · History",
        sections=(
            Section("Changes and steward decisions", rows)
            if rows
            else Section("Changes and steward decisions", lines=("No history is recorded for this record.",)),
        ),
        tabs=_record_tabs(party_id, "record-history"),
    )


def _resolve_applications(ctx: DetailContext, party_id: str) -> DetailView | None:
    profile = _profile_or_none(ctx, party_id)
    if profile is None:
        return None
    rows = tuple(Row(item["number"], item["status"]) for item in profile["applications"])
    links = tuple((f"Open {item['number']}", item["href"]) for item in profile["applications"][:12])
    return DetailView(
        title=f"Applications of {profile['name']}",
        sections=(
            Section("Applications", rows)
            if rows
            else Section("Applications", lines=("No application names this record.",)),
        ),
        links=links,
    )


# --------------------------------------------------------- source / credential


def _split_source_id(item_id: str) -> tuple[str, str, str]:
    parts = item_id.split(":")
    parts += [""] * (3 - len(parts))
    return parts[0], parts[1], ":".join(parts[2:])


def _accepted_values(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the accepted values of a source record, in a readable order.

    These are the values the source sent and the registry accepted.  A value
    that holds a document rather than a field is left out.
    """
    rows: list[tuple[str, str]] = []
    for key in sorted(payload):
        value = payload[key]
        if isinstance(value, (dict, list)):
            continue
        text = str(value)
        if len(text) > 240:
            text = text[:237] + "..."
        rows.append((display.pretty(key), text))
    return rows


def _resolve_source(ctx: DetailContext, item_id: str) -> DetailView | None:
    system_id, dataset_key, record_id = _split_source_id(item_id)
    system = ctx.session.execute(
        select(source.SourceSystem).where(source.SourceSystem.source_system_id == system_id)
    ).scalar_one_or_none()
    if system is None:
        return None
    contract = ctx.session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.source_system_id == system_id,
            governance.SourceContract.dataset_key == dataset_key,
        )
    ).scalars().first()
    snapshot = (
        current_accepted_snapshot(ctx.session, system_id, dataset_key, record_id)
        if record_id and dataset_key
        else None
    )
    if record_id and snapshot is None:
        return None
    domain_id = contract.domain_id if contract is not None else "applicants"
    panel = view_models.responsibility(
        ctx.session,
        domain_id=domain_id,
        source_system_id=system_id,
        dataset_key=dataset_key or None,
        source_record_id=record_id or None,
    )
    summary = source_summary(ctx.session, system_id, dataset_key or None, record_id or None)
    sections = [
        Section(
            "Source",
            (
                Row("Source", display.source_name(ctx.session, system_id, dataset_key or None)),
                Row("Source last changed", display.readable_date(summary["changed"]) or "unknown", info="source_last_changed"),
                Row("Last received or checked", display.readable_date(summary["received"]) or "unknown"),
            ),
        ),
        Section(
            "Ownership and routing",
            (
                Row("Owner", panel["owner_label"]),
                Row("Steward", panel["steward_label"]),
                Row("Source system", panel["source_label"] or "not declared"),
                Row("Change this in", panel["change_this_in"] or "not declared"),
                Row("Open recorded issues", str(len(panel["open_issues"]))),
            ),
        ),
    ]
    if panel.get("queue_label"):
        sections[-1] = Section(
            "Ownership and routing",
            sections[-1].rows
            + (
                Row(
                    "Queue",
                    f"{panel['queue_label']}; first review target {panel['response_target']} "
                    "(a configured demonstration target that makes no service promise)",
                ),
            ),
        )
    if snapshot is not None:
        values = _accepted_values(dict(snapshot.raw_payload or {}))
        if values:
            sections.insert(
                1,
                Section(
                    "Accepted values",
                    tuple(Row(label, value) for label, value in values),
                ),
            )
        crosswalk = ctx.session.execute(
            select(registry.Crosswalk)
            .where(
                registry.Crosswalk.source_system_id == system_id,
                registry.Crosswalk.source_record_id == record_id,
            )
            .order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
        ).scalars().all()
        if crosswalk:
            latest = crosswalk[-1]
            sections.append(
                Section(
                    "Current link",
                    (
                        Row("State", display.pretty(latest.link_status)),
                        Row("Master record", _party_label(ctx.session, latest.entity_id)),
                        Row("Decided by", view_models.actor_label(ctx.session, latest.decision_actor_id)),
                        Row("Decided at", display.readable_date(latest.decided_at) or "not decided"),
                    ),
                )
            )
    if summary["warning"]:
        sections.append(Section("Freshness", lines=(summary["warning"],)))
    technical = [
        Row("Source system id", system_id, mono=True),
        Row("Dataset key", dataset_key or "not named", mono=True),
        Row("Last source update", display.precise_time(summary["changed"]) or "unknown", mono=True),
        Row("Last received or checked", display.precise_time(summary["received"]) or "unknown", mono=True),
        Row(
            "Version",
            str(snapshot.source_record_version if snapshot is not None and snapshot.source_record_version else (panel["version"] if panel["version"] is not None else "not recorded")),
            mono=True,
        ),
    ]
    if contract is not None:
        technical.append(Row("Contract", contract.contract_id, mono=True))
    if snapshot is not None:
        technical += [
            Row("Record id", snapshot.source_record_id, mono=True),
            Row("Snapshot id", snapshot.source_snapshot_id, mono=True),
        ]
    sections.append(Section("Technical identifiers", tuple(technical)))
    title = display.source_name(ctx.session, system_id, dataset_key or None)
    return DetailView(
        title="Source details",
        subtitle=title + (f" · {snapshot.source_record_id}" if snapshot is not None else ""),
        sections=tuple(sections),
    )


def _resolve_credential(ctx: DetailContext, credential_id: str) -> DetailView | None:
    credential = ctx.session.execute(
        select(registry.Credential).where(registry.Credential.credential_id == credential_id)
    ).scalar_one_or_none()
    if credential is None:
        return None
    holder = {p.id: p for p in view_models.visible_parties(ctx.session, ctx.actor)}.get(
        credential.holder_party_id
    )
    if holder is None:
        return None
    issues = open_issue_lines(ctx.session, holder.id)
    system_id, _, dataset = (credential.issuing_authority_id or "").partition(":")
    summary = source_summary(
        ctx.session, credential.source_system_id or system_id, dataset or None, credential.source_record_id
    )
    sections = [
        Section(
            display.pretty(credential.credential_type),
            (
                Row("Number", credential.number),
                Row("License or registration status", display.pretty(credential.status), info="license_status"),
                Row("Valid from", display.readable_date(credential.valid_from) or "unknown"),
                Row("Valid through", display.readable_date(credential.valid_to) or "no end date"),
                Row("Issued by", display.issuer_name(ctx.session, credential.issuing_authority_id)),
            )
            + (
                (Row("Business category", display.pretty(credential.business_category)),)
                if credential.business_category
                else ()
            ),
        ),
        Section(
            "Holder",
            (
                Row("Name", holder.display_name),
                Row("Record status", display.pretty(holder.status), info="party_record_status"),
                Row("Data issue", issues[0]["text"] if issues else "None", info="data_issue"),
            ),
        ),
        Section(
            "Source",
            (
                Row("Source", summary["name"]),
                Row("Source last changed", display.readable_date(summary["changed"]) or "unknown", info="source_last_changed"),
                Row("Last received or checked", display.readable_date(summary["received"]) or "unknown"),
            ),
        ),
        Section(
            "Technical identifiers",
            (
                Row("Credential id", credential.credential_id, mono=True),
                Row("Source record", credential.source_record_id or "not recorded", mono=True),
                Row("Version", str(credential.version), mono=True),
                Row("Valid through (precise)", display.precise_time(credential.valid_to) or "none", mono=True),
            ),
        ),
    ]
    links = [("Open the organization profile", f"?detail=record:{holder.id}")]
    if summary["detail_id"]:
        links.append(("View source details", f"?detail=source:{summary['detail_id']}"))
    return DetailView(
        title=f"{display.pretty(credential.credential_type)} {credential.number}",
        subtitle=holder.display_name,
        sections=tuple(sections),
        links=tuple(links),
    )


# ------------------------------------------------------------------- parcels


def parcel_profile(session: Session, actor: ActorContext, parcel_key: str) -> dict[str, Any]:
    """Return one parcel: addresses, units, related applications and the open unit question."""
    parcel = session.execute(
        select(registry.Parcel).where(
            (registry.Parcel.parcel_id == parcel_key) | (registry.Parcel.source_parcel_number == parcel_key)
        )
    ).scalars().first()
    if parcel is None:
        return {}
    addresses = session.execute(
        select(registry.Address)
        .join(registry.ParcelAddress, registry.ParcelAddress.address_id == registry.Address.address_id)
        .where(registry.ParcelAddress.parcel_id == parcel.parcel_id)
        .order_by(registry.Address.address_id)
    ).scalars().all()
    units = sorted({str(a.unit_number) for a in addresses if a.unit_number})
    unit_ids = {a.id for a in addresses if a.unit_number}
    applications = []
    questions = []
    for site in session.execute(
        select(permit.ApplicationSite).where(permit.ApplicationSite.parcel_id == parcel.id)
    ).scalars():
        application = session.get(permit.Application, site.application_id)
        if application is None or application.synthetic or not view_models._application_in_scope(actor, application):
            continue
        unit = ""
        chosen = next((a for a in addresses if a.id == site.address_id), None)
        if chosen is not None and chosen.unit_number:
            unit = f"Unit {chosen.unit_number}"
        needs_unit = bool(units) and not unit
        applications.append(
            {
                "number": application.source_application_number,
                "status": display.pretty(application.status),
                "href": f"/permits/{application.id}",
                "unit": unit,
                "submitted": site.submitted_address_text or "",
                "needs_unit": needs_unit,
            }
        )
        if needs_unit:
            questions.append(
                f"{application.source_application_number}: which unit? A parcel match does not "
                f"resolve the unit ({_join_units(units).lower()} are on this parcel)."
            )
    sources = []
    for link in session.execute(
        select(registry.Crosswalk).where(registry.Crosswalk.entity_id == parcel.parcel_id)
    ).scalars():
        sources.append(
            {
                "source": display.source_name(session, link.source_system_id, link.source_dataset_key),
                "record_id": link.source_record_id,
                "status": display.pretty(link.link_status),
            }
        )
    history = view_models.history(session, actor, parcel.parcel_id)
    address_text = next((a.source_string for a in addresses if not a.unit_number), None) or (
        addresses[0].source_string if addresses else "No official address"
    )
    return {
        "parcel": parcel,
        "address": address_text,
        "parcel_number": parcel.source_parcel_number,
        "jurisdiction": display.pretty(parcel.jurisdiction_id),
        "status": display.pretty(parcel.status),
        "addresses": [
            {"text": a.source_string or "", "unit": a.unit_number or ""} for a in addresses
        ],
        "units": units,
        "units_text": _join_units(units),
        "applications": applications,
        "questions": questions,
        "sources": sources,
        "history": history,
        "responsibility": view_models.responsibility(
            session, domain_id="parcels", source_system_id="gis", dataset_key="parcel_register"
        ),
    }


def _resolve_parcel(ctx: DetailContext, parcel_key: str) -> DetailView | None:
    profile = parcel_profile(ctx.session, ctx.actor, parcel_key)
    if not profile:
        return None
    summary = source_summary(ctx.session, "gis", "parcel_register")
    sections = [
        Section(
            "Parcel",
            (
                Row("Address", profile["address"]),
                Row("Parcel number", profile["parcel_number"]),
                Row("Jurisdiction", profile["jurisdiction"]),
                Row("Status", profile["status"]),
            ),
        ),
        Section(
            "Official addresses and units",
            tuple(
                Row("Unit " + item["unit"] if item["unit"] else "Building", item["text"])
                for item in profile["addresses"]
            ),
        ),
    ]
    if profile["questions"]:
        sections.append(Section("Open question", lines=tuple(profile["questions"])))
    related = tuple(
        Row(item["number"], item["status"] + (f" · {item['unit']}" if item["unit"] else ""))
        for item in profile["applications"]
    )
    sections.append(
        Section("Related applications", related)
        if related
        else Section("Related applications", lines=("No application is on this parcel.",))
    )
    sections.append(
        Section(
            "Sources",
            tuple(Row(item["source"], f"{item['record_id']} · {item['status']}") for item in profile["sources"]),
        )
        if profile["sources"]
        else Section(
            "Sources",
            (
                Row("Source", summary["name"]),
                Row("Source last changed", display.readable_date(summary["changed"]) or "unknown", info="source_last_changed"),
                Row("Last received or checked", display.readable_date(summary["received"]) or "unknown"),
            ),
        )
    )
    history = [item for item in profile["history"] if not item["action"].startswith("ui.")]
    sections.append(
        Section(
            "History",
            tuple(
                Row(display.readable_date(item["occurred_at"]), f"{_pretty_action(item['action'])} · {item['actor_label']}")
                for item in history[:15]
            ),
        )
        if history
        else Section("History", lines=("No history is recorded for this property.",))
    )
    sections.append(
        Section(
            "Technical identifiers",
            (Row("Parcel key", profile["parcel"].parcel_id, mono=True), Row("Version", str(profile["parcel"].version), mono=True)),
        )
    )
    return DetailView(
        title=profile["address"],
        subtitle=f"Parcel {profile['parcel_number']}",
        sections=tuple(sections),
        links=((f"Open the property record", f"/property/{profile['parcel_number']}"),),
    )


# ------------------------------------------------------------------ comparison


def _payload_values(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if payload.get(key):
            return str(payload[key])
    return ""


def _comparison_row(
    field: str,
    left: str,
    right: str,
    result: str,
    note: str = "",
    left_normalized: str = "",
    right_normalized: str = "",
) -> dict[str, str]:
    """Return one row of a comparison.

    The raw value stays as it was recorded.  The normalized value, when the
    matcher computed one, sits beside it and is never shown as the value
    itself, so a reader sees what was recorded and what was compared.
    """
    return {
        "field": field,
        "source": left or "No value",
        "master": right or "No value",
        "result": result,
        "note": note,
        "source_normalized": left_normalized,
        "master_normalized": right_normalized,
    }


def typed_comparison(
    rows: list[dict[str, str]],
    *,
    family: str = "party",
    caption: str = "",
    current: bool = False,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return one typed comparison, ready for the comparison renderer.

    The rows come in the order a reader needs them: what disagrees first,
    then what is missing on one side, and only then what agrees.  A missing
    value stays missing; it is never filled in.  ``current`` marks a
    comparison that was computed again after a decision was recorded.
    """
    def rank(row: dict[str, str]) -> int:
        result = str(row.get("result", ""))
        return COMPARISON_ORDER.index(result) if result in COMPARISON_ORDER else len(COMPARISON_ORDER)

    ordered = sorted(rows, key=rank)
    for row in ordered:
        # A value that is not there is shown as missing, never as an empty
        # cell that could be read as an empty value.
        row["source"] = row.get("source") or "No value"
        row["master"] = row.get("master") or "No value"
        row.setdefault("note", "")
        row.setdefault("source_normalized", "")
        row.setdefault("master_normalized", "")
    return {
        "family": family,
        "caption": caption,
        "headers": {"source": "Source record", "master": "Master record", **(headers or {})},
        "rows": ordered,
        "conflicts": [row for row in ordered if row.get("result") == "conflicts"],
        "missing": [row for row in ordered if row.get("result") == "no_comparison"],
        "agreements": [row for row in ordered if row.get("result") == "agrees"],
        "current": current,
        "has_conflicts": any(row.get("result") == "conflicts" for row in ordered),
        "has_missing": any(row.get("result") == "no_comparison" for row in ordered),
    }


def compare_with_party(
    session: Session, payload: dict[str, Any], party: registry.Party
) -> list[dict[str, str]]:
    """Compare the values of a source record with one master record, field by field.

    Each row is ``agrees``, ``conflicts`` or ``no_comparison`` (a value is
    missing on one side).  Nothing is inferred: a missing value is shown as
    missing, never filled in.
    """
    aliases = [
        row.alias_value
        for row in session.execute(
            select(registry.PartyAlias).where(registry.PartyAlias.party_id == party.id)
        ).scalars()
    ]
    contacts = session.execute(
        select(registry.PartyContact).where(registry.PartyContact.party_id == party.id)
    ).scalars().all()
    credentials = session.execute(
        select(registry.Credential).where(registry.Credential.holder_party_id == party.id)
    ).scalars().all()
    rows: list[dict[str, str]] = []

    def add(
        field: str,
        left: str,
        right: str,
        result: str,
        note: str = "",
        left_normalized: str = "",
        right_normalized: str = "",
    ) -> None:
        rows.append(
            _comparison_row(field, left, right, result, note, left_normalized, right_normalized)
        )

    name = _payload_values(payload, ("organization_name", "holder_name", "display_name", "full_name"))
    if name:
        names = [party.display_name, party.legal_name or "", *aliases]
        hit = next((item for item in names if item and _norm(item) == _norm(name)), "")
        if hit:
            note = "matches a recorded alias" if hit in aliases and hit != party.display_name else ""
            shown = hit if hit != party.display_name else party.display_name
            add(
                "Name",
                name,
                shown,
                "agrees",
                note,
                normalize_name(name).normalized,
                normalize_name(shown).normalized,
            )
        else:
            add(
                "Name",
                name,
                party.display_name,
                "conflicts",
                "similar words do not make the same organization",
                normalize_name(name).normalized,
                normalize_name(party.display_name).normalized,
            )
    else:
        add("Name", "", party.display_name, "no_comparison")

    ref = _payload_values(payload, ("party_ref", "holder_ref"))
    if ref:
        named = _party_label(session, ref)
        add(
            "Master record named by the source",
            named,
            party.display_name,
            "agrees" if ref == party.id else "conflicts",
            "",
            normalize_identifier(ref),
            normalize_identifier(party.id),
        )

    email = _payload_values(payload, ("contact_email",))
    if email:
        mine = next((c.value for c in contacts if c.contact_type == "email"), "")
        add(
            "Email",
            email,
            mine,
            ("agrees" if _norm(mine) == _norm(email) else "conflicts") if mine else "no_comparison",
            "",
            normalize_email(email),
            normalize_email(mine),
        )
    phone = _payload_values(payload, ("contact_phone",))
    if phone:
        mine = next((c.value for c in contacts if c.contact_type == "phone"), "")
        add(
            "Phone",
            phone,
            mine,
            ("agrees" if _norm(mine) == _norm(phone) else "conflicts") if mine else "no_comparison",
            "",
            normalize_phone(phone),
            normalize_phone(mine),
        )

    number = _payload_values(payload, ("license_number", "registration_number"))
    if number:
        numbers = [c.number for c in credentials]
        if not numbers:
            add("License or registration number", number, "", "no_comparison")
        elif any(_norm(n) == _norm(number) for n in numbers):
            add(
                "License or registration number",
                number,
                number,
                "agrees",
                "",
                normalize_identifier(number),
                normalize_identifier(number),
            )
        else:
            add(
                "License or registration number",
                number,
                ", ".join(numbers),
                "conflicts",
                "a different number",
                normalize_identifier(number),
                normalize_identifier(", ".join(numbers)),
            )

    address = _payload_values(payload, ("business_address",))
    if address:
        from acme_city.registry.candidates import _party_addresses

        official = _party_addresses(session, party.id)
        if not official:
            add(
                "Site address",
                address,
                "",
                "no_comparison",
                "",
                normalize_address(address).normalized,
                "",
            )
        elif any(_norm(a) == _norm(address) for a in official):
            add(
                "Site address",
                address,
                address,
                "agrees",
                "",
                normalize_address(address).normalized,
                normalize_address(address).normalized,
            )
        else:
            add(
                "Site address",
                address,
                ", ".join(official),
                "conflicts",
                "a different address or unit",
                normalize_address(address).normalized,
                normalize_address(", ".join(official)).normalized,
            )
    return rows


def compare_with_parcel(
    session: Session, payload: dict[str, Any], parcel: registry.Parcel
) -> list[dict[str, str]]:
    """Compare the values of a source record with one official parcel.

    The parcel number and the jurisdiction are the identity of a parcel.  A
    value the source did not send stays missing; it is never filled in.
    """
    rows: list[dict[str, str]] = []

    def add(
        field: str,
        left: str,
        right: str,
        result: str,
        note: str = "",
        left_normalized: str = "",
        right_normalized: str = "",
    ) -> None:
        rows.append(
            _comparison_row(field, left, right, result, note, left_normalized, right_normalized)
        )

    number = _payload_values(payload, ("parcel_number", "submitted_parcel"))
    official_number = parcel.source_parcel_number
    if number:
        same = _norm(number) == _norm(official_number)
        add(
            "Parcel number",
            number,
            official_number,
            "agrees" if same else "conflicts",
            "" if same else "a different parcel",
            normalize_identifier(number),
            normalize_identifier(official_number),
        )
    else:
        add("Parcel number", "", official_number, "no_comparison")
    jurisdiction = _payload_values(payload, ("jurisdiction_id", "jurisdiction"))
    if jurisdiction:
        same = _norm(jurisdiction) == _norm(parcel.jurisdiction_id)
        add(
            "Jurisdiction",
            jurisdiction,
            parcel.jurisdiction_id,
            "agrees" if same else "conflicts",
            "" if same else "another jurisdiction",
            normalize_identifier(jurisdiction),
            normalize_identifier(parcel.jurisdiction_id),
        )
    else:
        add("Jurisdiction", "", parcel.jurisdiction_id, "no_comparison")
    return rows


def _written_unit(raw: str, address: Any) -> str:
    """Return the unit of an address as it was written.

    The comparison form of an address folds the case away, so the unit is
    read back from the text the source sent.
    """
    if not address.unit_key:
        return ""
    pattern = re.escape(address.unit_key).replace(r"\ ", r"\s+")
    match = re.search(pattern, raw, re.IGNORECASE)
    return match.group(0) if match else address.unit_key


def compare_with_address(
    session: Session, payload: dict[str, Any], address: registry.Address
) -> list[dict[str, str]]:
    """Compare the values of a source record with one official address.

    The street and the unit stay apart: two addresses in the same building
    that name the unit differently are not the same place.  A missing value
    stays missing.
    """
    rows: list[dict[str, str]] = []

    def add(
        field: str,
        left: str,
        right: str,
        result: str,
        note: str = "",
        left_normalized: str = "",
        right_normalized: str = "",
    ) -> None:
        rows.append(
            _comparison_row(field, left, right, result, note, left_normalized, right_normalized)
        )

    source_text = _payload_values(payload, ("source_string", "business_address", "address_text"))
    official_text = address.source_string or ""
    source_address = normalize_address(source_text)
    official_address = normalize_address(official_text)
    if source_text and official_text:
        same = (
            source_address.building_key == official_address.building_key
            and source_address.unit_key == official_address.unit_key
        )
        add(
            "Address",
            source_text,
            official_text,
            "agrees" if same else "conflicts",
            "" if same else "a different address or unit",
            source_address.normalized,
            official_address.normalized,
        )
    elif source_text:
        add(
            "Address",
            source_text,
            "",
            "no_comparison",
            "",
            source_address.normalized,
            "",
        )
    else:
        add("Address", "", official_text, "no_comparison")
    source_unit = _written_unit(source_text, source_address)
    official_unit = _written_unit(official_text, official_address)
    if source_unit and official_unit:
        same = _norm(source_unit) == _norm(official_unit)
        add(
            "Unit",
            source_unit,
            official_unit,
            "agrees" if same else "conflicts",
            "" if same else "another unit in the same building",
            normalize_text(source_unit),
            normalize_text(official_unit),
        )
    else:
        add("Unit", source_unit, official_unit, "no_comparison")
    return rows


def _candidate_comparison(
    session: Session, candidate: Any, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the typed comparison of one candidate.

    A party, a parcel and an address are compared in their own fields, so a
    case never shows a party card for a parcel.  ``None`` means the record
    the candidate names is not in the registry.
    """
    if candidate.entity_type == "party":
        party = session.get(registry.Party, candidate.entity_id)
        if party is None:
            return None
        numbers = [
            f"{display.pretty(credential.credential_type)} {credential.number}"
            for credential in session.execute(
                select(registry.Credential).where(
                    registry.Credential.holder_party_id == party.id
                )
            ).scalars()
        ]
        return {
            "family": "party",
            "name": party.display_name,
            "type": display.pretty(party.party_type),
            "credentials": numbers,
            "record_ref": _ref("record", party.id),
            "linkable": True,
            "rows": compare_with_party(session, payload, party),
        }
    if candidate.entity_type == "parcel":
        parcel = session.get(registry.Parcel, candidate.entity_id)
        if parcel is None:
            return None
        return {
            "family": "parcel",
            "name": parcel.source_parcel_number,
            "type": "Parcel",
            "credentials": [],
            "record_ref": _ref("parcel", parcel.parcel_id),
            "linkable": False,
            "rows": compare_with_parcel(session, payload, parcel),
        }
    if candidate.entity_type == "address":
        address = session.get(registry.Address, candidate.entity_id)
        if address is None:
            return None
        return {
            "family": "address",
            "name": address.source_string or address.address_id,
            "type": "Address",
            "credentials": [],
            "record_ref": _ref("address", address.address_id),
            "linkable": False,
            "rows": compare_with_address(session, payload, address),
        }
    return None


def _stored_evidence(
    proposal: registry.MatchProposal | None, entity_id: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]] | None:
    """Return the evidence the proposal recorded for one candidate.

    The proposal stores the evidence it used, so a decision can be read with
    the evidence that was recorded at the time.  ``None`` means the proposal
    holds no evidence for that candidate.
    """
    if proposal is None or proposal.entity_id != entity_id:
        return None
    supporting = [dict(item) for item in (proposal.supporting_evidence or [])]
    conflicting = [dict(item) for item in (proposal.conflicting_evidence or [])]
    if not supporting and not conflicting:
        return None
    return supporting, conflicting


def _evidence_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return the evidence of one direction in the shape the screen reads."""
    return [
        {
            "field": str(item.get("field", "")),
            "text": str(item.get("detail", "")),
            "method": _evidence_phrase(str(item.get("method", ""))),
        }
        for item in items
    ]


def _score_parts(supporting: tuple[Any, ...], conflicting: tuple[Any, ...]) -> list[dict[str, str]]:
    parts = []
    for item in supporting:
        parts.append({"text": _evidence_phrase(item.method), "weight": f"+{SUPPORTING_WEIGHTS.get(item.method, 0.1):.2f}"})
    for item in conflicting:
        parts.append({"text": _evidence_phrase(item.method), "weight": f"-{CONFLICTING_WEIGHTS.get(item.method, 0.2):.2f}"})
    return parts


# -------------------------------------------------------------- Data issues


#: One task of the Data Steward's queue.  The queue module owns the type.
Issue = steward_queue_views.Issue


def _applications_of(session: Session, party_ids: list[str], synthetic: set[str]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for party_id in party_ids:
        for application in view_models._party_applications(session, party_id):
            if application.id in synthetic:
                continue
            found[application.id] = {
                "number": application.source_application_number,
                "href": f"/permits/{application.id}",
                "status": display.pretty(application.status),
            }
    return sorted(found.values(), key=lambda item: item["number"])


def collect_issues(session: Session, actor: ActorContext) -> list[Issue]:
    """Return every steward issue: waiting matches, parcel links, change cases, governance issues.

    Generated historical records (flagged synthetic) never appear.
    """
    synthetic = _synthetic_ids(session)
    issues: list[Issue] = []
    snapshots = {
        row.source_snapshot_id: row
        for row in session.execute(select(source.SourceSnapshot)).scalars()
    }

    # 1. Record matches.
    latest: dict[tuple[str, str], registry.MatchProposal] = {}
    for proposal in session.execute(
        select(registry.MatchProposal).order_by(registry.MatchProposal.created_at, registry.MatchProposal.id)
    ).scalars():
        snap = snapshots.get(proposal.source_snapshot_id)
        if snap is None:
            continue
        latest[(snap.source_system_id, snap.source_record_id)] = proposal
    proposal_keys = set(latest)
    for (system_id, record_id), proposal in latest.items():
        snap = snapshots[proposal.source_snapshot_id]
        candidates = [str(c) for c in proposal.candidate_ids or []]
        if candidates and all(c in synthetic for c in candidates):
            continue
        decided = _decided_crosswalk(session, system_id, record_id)
        lead_id = (decided.entity_id if decided is not None else None) or proposal.entity_id
        lead = _party_label(session, lead_id) if lead_id else "No candidate"
        name = _payload_values(dict(snap.raw_payload or {}), ("organization_name", "holder_name", "display_name", "full_name"))
        title = f"Is {record_id}" + (f" ({name})" if name else "") + (f" the same as {lead}?" if lead_id else " a record we already know?")
        if decided is not None:
            title = f"{record_id}" + (f" ({name})" if name else "") + {
                "approved": f" is linked to {lead}",
                "rejected": f" was not matched to {lead}",
                "no_match": " has no matching master record",
                "removed": f" is no longer linked to {lead}",
            }.get(decided.link_status, "")
        issues.append(
            Issue(
                kind="link",
                item_id=proposal.id,
                title=title,
                record=lead,
                record_ref=_ref("record", lead_id) if lead_id else "",
                applications=_applications_of(session, [lead_id] if lead_id else [], synthetic),
                source=display.source_name(session, system_id, snap.source_dataset_id),
                status="resolved" if decided is not None else "needs_review",
                created_at=decided.decided_at if decided is not None else proposal.created_at,
                legacy_testid=("crosswalk-row" if decided is not None else "match-proposal"),
                link_status=decided.link_status if decided is not None else "proposed",
                sort_key=(proposal.created_at,),
                record_type=_party_type(session, lead_id),
                source_reference=record_id,
            )
        )
    # Decided links nobody proposed through the queue (for example an API decision).
    for crosswalk in session.execute(
        select(registry.Crosswalk).where(registry.Crosswalk.link_status.in_(DECIDED_LINKS))
    ).scalars():
        if (crosswalk.source_system_id, crosswalk.source_record_id) in proposal_keys:
            continue
        if crosswalk.entity_id in synthetic:
            continue
        lead = _party_label(session, crosswalk.entity_id)
        issues.append(
            Issue(
                kind="linked",
                item_id=crosswalk.id,
                title=f"{crosswalk.source_record_id} is {display.pretty(crosswalk.link_status).lower()} for {lead}",
                record=lead,
                record_ref=_ref("record", crosswalk.entity_id),
                applications=_applications_of(session, [crosswalk.entity_id], synthetic),
                source=display.source_name(session, crosswalk.source_system_id, crosswalk.source_dataset_key),
                status="resolved",
                created_at=crosswalk.decided_at or crosswalk.created_at,
                legacy_testid="crosswalk-row",
                link_status=crosswalk.link_status,
                sort_key=(crosswalk.created_at,),
                record_type=_party_type(session, crosswalk.entity_id),
                source_reference=crosswalk.source_record_id,
            )
        )

    # 2. Parcel links.
    for proposal in property_views.steward_parcel_proposals(session, actor):
        application = session.get(permit.Application, proposal["application_id"])
        if application is None or application.id in synthetic:
            continue
        issues.append(
            Issue(
                kind="parcel",
                item_id=proposal["application_id"],
                title=f"Which parcel is “{proposal['submitted_text']}”?",
                record=proposal["parcel_number"] or "No parcel yet",
                record_ref=_ref("parcel", proposal["parcel_number"]) if proposal["parcel_number"] else "",
                applications=[
                    {"number": proposal["number"], "href": proposal["href"], "status": display.pretty(application.status)}
                ],
                source="GIS: Address locator (simulated)",
                status="needs_review",
                created_at=None,
                legacy_testid="parcel-proposal",
                sort_key=(application.created_at,),
                record_type="parcel",
                source_reference=proposal["submitted_text"],
            )
        )
    for match in session.execute(
        select(gis.ApplicationParcelMatch).where(
            gis.ApplicationParcelMatch.link_state.in_(("approved", "rejected"))
        )
    ).scalars():
        application = session.get(permit.Application, match.application_id)
        if application is None or application.id in synthetic:
            continue
        issues.append(
            Issue(
                kind="parcel",
                item_id=match.application_id,
                title=f"Parcel link for “{match.submitted_text}” was {match.link_state}",
                record=match.parcel_number or "No parcel",
                record_ref=_ref("parcel", match.parcel_number) if match.parcel_number else "",
                applications=[
                    {
                        "number": application.source_application_number,
                        "href": f"/permits/{application.id}",
                        "status": display.pretty(application.status),
                    }
                ],
                source="GIS: Address locator (simulated)",
                status="resolved",
                created_at=match.decided_at,
                legacy_testid="parcel-decided",
                sort_key=(match.created_at,),
                record_type="parcel",
                source_reference=match.submitted_text,
            )
        )

    # 3. Change cases (requests to correct a source).
    for case in session.execute(
        select(change.ChangeCase).order_by(change.ChangeCase.created_at, change.ChangeCase.id)
    ).scalars():
        if case.target_id in synthetic:
            continue
        status = (
            "needs_review"
            if case.status in CASE_NEEDS_REVIEW
            else "awaiting_source"
            if case.status in CASE_AWAITING_SOURCE
            else "resolved"
        )
        target_party = case.target_id if case.target_type == "party" else None
        dependents = [
            dep.consumer_id
            for dep in session.execute(
                select(change.ChangeDependency).where(
                    change.ChangeDependency.change_case_id == case.id,
                    change.ChangeDependency.consumer_type == "application",
                )
            ).scalars()
        ]
        applications = []
        for application_id in dependents:
            application = session.get(permit.Application, application_id)
            if application is not None and application.id not in synthetic:
                applications.append(
                    {
                        "number": application.source_application_number,
                        "href": f"/permits/{application.id}",
                        "status": display.pretty(application.status),
                    }
                )
        if not applications and target_party:
            applications = _applications_of(session, [target_party], synthetic)
        issues.append(
            Issue(
                kind="case",
                item_id=case.id,
                title=case.title,
                record=_party_label(session, target_party) if target_party else f"{display.pretty(case.target_type)} {case.target_id}",
                record_ref=_ref("record", target_party) if target_party else "",
                applications=applications,
                source=case.destination or "Configured steward queue",
                status=status,
                assignee_id=case.assignee_actor_id,
                created_at=case.created_at,
                legacy_testid="case-row",
                link_status=case.status,
                sort_key=(case.created_at,),
                record_type=case.change_kind,
            )
        )

    # 4. Governance issues.
    for row in session.execute(
        select(change.GovernanceIssue).order_by(change.GovernanceIssue.created_at, change.GovernanceIssue.id)
    ).scalars():
        if row.subject_id in synthetic:
            continue
        party = session.get(registry.Party, row.subject_id)
        issues.append(
            Issue(
                kind="issue",
                item_id=row.id,
                title=row.description,
                record=party.display_name if party is not None else display.pretty(row.subject_type) + " " + row.subject_id,
                record_ref=_ref("record", party.id) if party is not None else "",
                applications=_applications_of(session, [row.subject_id], synthetic) if party is not None else [],
                source=row.responsible_queue_id or "Steward queue",
                status="needs_review" if row.status == "open" else "resolved",
                assignee_id=row.assigned_actor_id,
                created_at=row.created_at,
                priority="Blocking" if row.blocking and row.status == "open" else "",
                legacy_testid="issue-row",
                sort_key=(row.created_at,),
                record_type=row.issue_type,
            )
        )
    return issues


def _ref(kind: str, item_id: str | None) -> str:
    """Return ``kind:id``, the address of a detail drawer, or an empty string."""
    return f"{kind}:{item_id}" if item_id else ""


def data_issues(
    session: Session,
    actor: ActorContext,
    *,
    filter_key: str = "needs_review",
    query: str = "",
    record_type: str = "",
    source: str = "",
    page: int = 1,
    return_path: str = "",
) -> dict[str, Any]:
    """Return the work queue with the real count behind every view.

    The projection lives in ``steward_queue_views``: it turns the collected
    tasks into the rows of one view, the count of every view and the totals.
    The counts use the same tasks as the rows, so they never describe work
    the persona may not see.
    """
    tasks = collect_issues(session, actor)
    labels = {
        issue.assignee_id: view_models.actor_label(session, issue.assignee_id)
        for issue in tasks
        if issue.assignee_id
    }
    return steward_queue_views.project(
        tasks,
        view_key=filter_key,
        actor_id=actor.actor_id,
        labels=labels,
        query=query,
        record_type=record_type,
        source=source,
        page=page,
        return_path=return_path,
    )


# ----------------------------------------------------------------- focused case


def _action(
    session: Session,
    actor: ActorContext,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build one action; a permission-only refusal reads "Your role cannot do this"."""
    item = view_models.action(session, actor, **kwargs)
    if not item["permitted"] and kwargs.get("state_allowed", True):
        item["reason"] = "Your role cannot do this."
    return item


def _master_choice(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a form field that names the master record to link to.

    The value is the canonical identifier and the text is the name a person
    reads.  The first choice is empty, so an ambiguous case has no implicit
    selection: the steward has to name the record before the link changes.
    """
    return {
        "name": "entity_id",
        "label": "Master record",
        "type": "select",
        "value": "",
        "options": [("", "Choose a master record")]
        + [(str(item["entity_id"]), str(item["name"])) for item in candidates],
        "required": True,
        "hint": "",
    }


def _preview(
    records: str, application: str, source_values: str, issue_after: str
) -> dict[str, str]:
    return {
        "records": records,
        "application": application,
        "source_values": source_values,
        "issue_after": issue_after,
    }


def _dependents_text(session: Session, entity_ids: list[str]) -> tuple[str, int]:
    dependents = affected_dependents(session, entity_ids=tuple(entity_ids))
    total = sum(len(items) for items in dependents.values())
    parts = [f"{len(items)} {kind.replace('_', ' ')}" for kind, items in dependents.items() if items]
    return (", ".join(parts), total)


def _application_outstanding(session: Session, application: permit.Application) -> list[str]:
    """Return what is still outstanding on a permit, in words."""
    from acme_city.agents.findings import blocking_findings
    from acme_city.permits.service import PermitService

    notes: list[str] = []
    try:
        notes += [blocker.detail for blocker in PermitService(session).parcel_link_blockers(application)]
    except Exception:  # a parcel check must never hide the case
        pass
    count = len(blocking_findings(session, application.id))
    if count:
        notes.append(f"{count} blocking finding" + ("" if count == 1 else "s") + " to resolve")
    if application.status not in ("approved", "issued", "denied", "returned", "archived"):
        notes.append("No permit decision has been made")
    return notes


def _outstanding_for(session: Session, applications: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for item in applications:
        application_id = item["href"].rsplit("/", 1)[-1]
        application = session.get(permit.Application, application_id)
        result.append(
            {
                **item,
                "outstanding": _application_outstanding(session, application) if application is not None else [],
            }
        )
    return result


def _events_for(session: Session, target_ids: list[str], prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = session.execute(
        select(audit.AuditEvent)
        .where(audit.AuditEvent.target_id.in_(target_ids))
        .order_by(audit.AuditEvent.occurred_at)
    ).scalars().all()
    events = []
    for row in rows:
        if not any(row.action.startswith(prefix) for prefix in prefixes):
            continue
        events.append(
            {
                "when": _iso(row.occurred_at),
                "who": view_models.actor_label(session, row.actor_id),
                "what": _pretty_action(row.action),
                "note": row.reason or "",
                "outcome": row.outcome,
            }
        )
    return events


def link_case(
    session: Session, actor: ActorContext, proposal_id: str, selected_id: str = ""
) -> dict[str, Any]:
    """Return the focused case of a record match, answering the six questions in order.

    ``selected_id`` is the master record the steward chose in the chooser.  A
    case with one candidate needs no choice, so that candidate is the one the
    decision acts on; an ambiguous case has no candidate chosen until the
    steward chooses one.
    """
    proposal = session.get(registry.MatchProposal, proposal_id)
    if proposal is None:
        return {}
    snap = session.get(source.SourceSnapshot, proposal.source_snapshot_id)
    if snap is None:
        return {}
    system_id, dataset_key, record_id = snap.source_system_id, snap.source_dataset_id, snap.source_record_id
    payload = dict(snap.raw_payload or {})
    synthetic = _synthetic_ids(session)
    rows = session.execute(
        select(registry.Crosswalk)
        .where(
            registry.Crosswalk.source_system_id == system_id,
            registry.Crosswalk.source_record_id == record_id,
        )
        .order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
    ).scalars().all()
    decided = _decided_crosswalk(session, system_id, record_id)
    pending = next((row for row in reversed(rows) if row.link_status == "proposed"), None)
    entity_type = entity_target_for(dataset_key)
    candidate_set = generate_candidates(session, payload, entity_type, snap.source_snapshot_id)
    name = _payload_values(payload, ("organization_name", "holder_name", "display_name", "full_name"))
    source_label = display.source_name(session, system_id, dataset_key)

    candidates = []
    for candidate in sorted(candidate_set.candidates, key=lambda c: c.score, reverse=True):
        typed = _candidate_comparison(session, candidate, payload)
        if typed is None:
            continue
        comparison = typed_comparison(
            typed["rows"],
            family=typed["family"],
            caption=f"Source record values against {typed['name']}",
            current=decided is not None,
        )
        # The proposal keeps the evidence it used.  A candidate the proposal
        # named is read with that evidence; the others are read with the
        # evidence the matcher holds now.
        recorded = _stored_evidence(proposal, candidate.entity_id)
        if recorded is not None:
            agreements = _evidence_items(recorded[0])
            conflicts = _evidence_items(recorded[1])
            evidence_source = "Recorded evidence"
        else:
            agreements = [
                {"field": item.field, "text": item.detail or _evidence_phrase(item.method), "method": _evidence_phrase(item.method)}
                for item in candidate.supporting
            ]
            conflicts = [
                {"field": item.field, "text": item.detail or _evidence_phrase(item.method), "method": _evidence_phrase(item.method)}
                for item in candidate.conflicting
            ]
            evidence_source = "Current evidence"
        candidates.append(
            {
                "entity_id": candidate.entity_id,
                "name": typed["name"],
                "type": typed["type"],
                "credentials": typed["credentials"],
                "comparison": comparison,
                "agreements": agreements,
                "conflicts": conflicts,
                "evidence_source": evidence_source,
                "no_comparison": [row["field"] for row in comparison["missing"]],
                "score": candidate.score,
                "score_parts": _score_parts(candidate.supporting, candidate.conflicting),
                "record_ref": typed["record_ref"],
                "linkable": typed["linkable"],
                "lead": candidate.entity_id == (decided.entity_id if decided is not None else proposal.entity_id),
            }
        )
    lead = next((c for c in candidates if c["lead"]), candidates[0] if candidates else None)
    # The record the steward chose, and the one the matcher put first.  An
    # ambiguous case has no chosen record until the steward chooses one.
    chosen = next((c for c in candidates if c["entity_id"] == selected_id), None)
    if chosen is None and len(candidates) == 1:
        chosen = candidates[0]
    # One comparison is shown open; the other candidates stay in a disclosure.
    shown = chosen or lead
    for candidate in candidates:
        candidate["selected"] = chosen is not None and candidate["entity_id"] == chosen["entity_id"]
        candidate["recommended"] = lead is not None and candidate["entity_id"] == lead["entity_id"]
        candidate["open"] = shown is not None and candidate["entity_id"] == shown["entity_id"]

    # 1. The problem.
    if decided is not None:
        problem = (
            f"Source record {record_id}" + (f" ({name})" if name else "") + f" from {source_label} "
            + {
                "approved": f"is linked to {_party_label(session, decided.entity_id)}.",
                "rejected": f"was not matched to {_party_label(session, decided.entity_id)}.",
                "no_match": "was recorded as having no matching master record.",
                "removed": f"was linked to {_party_label(session, decided.entity_id)}; the link has been removed.",
            }.get(decided.link_status, "has a recorded decision.")
        )
    elif len(candidates) > 1:
        problem = (
            f"Source record {record_id}" + (f" ({name})" if name else "")
            + f" from {source_label} could belong to {len(candidates)} master records. A person must choose, or say it is none of them."
        )
    elif candidates:
        problem = (
            f"Source record {record_id}" + (f" ({name})" if name else "")
            + f" from {source_label} is not linked to a master record yet. The matcher found one likely candidate."
        )
    else:
        problem = f"Source record {record_id} from {source_label} matches no master record the matcher knows."

    # 2. Why it matters.
    party_ids = [c["entity_id"] for c in candidates][:3]
    applications = _outstanding_for(session, _applications_of(session, party_ids, synthetic))
    dependents_text, dependents_total = _dependents_text(session, party_ids)
    why = (
        "The applications below name these master records. A link is used by the checks, assessments and permits that depend on that identity."
        if applications
        else "No open application names these master records yet. The link still decides which record owns the source values."
    )

    # 5. What will this action do.
    actions: list[dict[str, Any]] = []
    domain = None
    contract = session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.source_system_id == system_id,
            governance.SourceContract.dataset_key == dataset_key,
        )
    ).scalars().first()
    domain = contract.domain_id if contract is not None else "applicants"
    common_fields = (
        view_models._field("source_system_id", "Source system", value=system_id, field_type="hidden"),
        view_models._field("dataset_key", "Dataset", value=dataset_key, field_type="hidden"),
        view_models._field("source_record_id", "Source record", value=record_id, field_type="hidden"),
    )
    if decided is None and pending is not None:
        conflict_note = lambda cand: (  # noqa: E731
            f"{len(cand['conflicts'])} conflicting value(s) stay visible in the history: "
            + ", ".join(sorted({c['field'] for c in cand['conflicts']}))
            if cand["conflicts"]
            else "No conflicting value remains."
        )
        # The steward names the master record.  A chosen record is confirmed;
        # an ambiguous case has no chosen record, so the action offers the
        # choice and asks for it.
        if chosen is not None:
            entity_field = view_models._field(
                "entity_id", "Master record", value=chosen["entity_id"], field_type="hidden"
            )
            confirm_label = f"Confirm link to {chosen['name']}"
            confirm_records = f"Links {record_id} ({source_label}) to {chosen['name']}."
            confirm_application = (
                f"{len(_applications_of(session, [chosen['entity_id']], synthetic))} application(s) "
                f"name {chosen['name']}; their applicant is unchanged"
                + (f" and {dependents_text} are marked for recheck." if dependents_total else ".")
            )
            confirm_conflicts = conflict_note(chosen)
        else:
            entity_field = _master_choice(candidates)
            confirm_label = "Confirm link to the selected record"
            confirm_records = f"Links {record_id} ({source_label}) to the master record you choose."
            confirm_application = (
                "The applications that name the chosen record use it; their applicant is unchanged"
                + (f" and {dependents_text} are marked for recheck." if dependents_total else ".")
            )
            confirm_conflicts = "The conflicts of the record you choose stay visible in the history."
        actions.append(
            {
                **_action(
                    session,
                    actor,
                    action_id="registry.decide",
                    label=confirm_label,
                    path="/ui/actions/registry.decide",
                    permission="registry.crosswalk.decide",
                    domain_id=domain,
                    destination="Registry crosswalk",
                    description="Link this source record to the master record. The decision, your name, the time and the note are recorded.",
                    expected_version=pending.version,
                    fields=(
                        *common_fields,
                        entity_field,
                        view_models._field("crosswalk_id", "Link", value=pending.id, field_type="hidden"),
                        view_models._field("expected_version", "Expected link version", value=str(pending.version), field_type="hidden"),
                        view_models._field("reason", "Decision note", field_type="textarea", required=True),
                    ),
                ),
                "dom_id": f"confirm-{chosen['entity_id'] if chosen else 'choice'}",
                "preview": _preview(
                    confirm_records,
                    confirm_application,
                    f"The source record is not edited and no master value is overwritten. Source value kept: {name or 'as received'}."
                    + (" The payer link of the finance account is set to this record." if dataset_key == "finance_accounts" else ""),
                    confirm_conflicts,
                ),
            }
        )
        actions.append(
            {
                **_action(
                    session,
                    actor,
                    action_id="registry.decide",
                    label=f"Reject match proposed for {_party_label(session, pending.entity_id)}",
                    path="/ui/actions/registry.decide",
                    permission="registry.crosswalk.decide",
                    domain_id=domain,
                    destination="Registry crosswalk",
                    description="Say this source record is not the proposed master record.",
                    expected_version=pending.version,
                    fields=(
                        *common_fields,
                        view_models._field("decision", "Decision", value="reject", field_type="hidden"),
                        view_models._field("crosswalk_id", "Link", value=pending.id, field_type="hidden"),
                        view_models._field("expected_version", "Expected link version", value=str(pending.version), field_type="hidden"),
                        view_models._field("reason", "Decision note", field_type="textarea", required=True),
                    ),
                ),
                "dom_id": "reject-match",
                "preview": _preview(
                    f"No record is linked. {record_id} stays unlinked.",
                    "No application relationship changes.",
                    "The source record and the master records keep every value.",
                    "This proposal closes as rejected. Another candidate can be linked by proposing again.",
                ),
            }
        )
        actions.append(
            {
                **_action(
                    session,
                    actor,
                    action_id="registry.defer",
                    label="Keep for review",
                    path="/ui/actions/registry.defer",
                    permission="registry.crosswalk.decide",
                    domain_id=domain,
                    destination="Registry crosswalk",
                    description="Put the decision aside with a note, for example while you wait for more information.",
                    expected_version=pending.version,
                    fields=(
                        *common_fields,
                        view_models._field("expected_version", "Expected link version", value=str(pending.version), field_type="hidden"),
                        view_models._field("reason", "Why are you deferring?", field_type="textarea", required=True),
                    ),
                ),
                "dom_id": "defer",
                "preview": _preview(
                    "Nothing is linked.",
                    "No application relationship changes.",
                    "Nothing is changed.",
                    "The issue stays in Needs review with your note on the record.",
                ),
            }
        )
    if decided is not None and decided.link_status == "approved":
        actions.append(
            {
                **_action(
                    session,
                    actor,
                    action_id="registry.decide",
                    label="Remove link",
                    path="/ui/actions/registry.decide",
                    permission="registry.crosswalk.decide",
                    domain_id=domain,
                    destination="Registry crosswalk",
                    description="Take the link away again, with a reason. The earlier decision stays in the history.",
                    expected_version=decided.version,
                    state_allowed=dataset_key != "finance_accounts",
                    state_reason="A finance account link cannot be removed. Correct it by linking the right party.",
                    fields=(
                        *common_fields,
                        view_models._field("decision", "Decision", value="remove", field_type="hidden"),
                        view_models._field("crosswalk_id", "Link", value=decided.id, field_type="hidden"),
                        view_models._field("expected_version", "Expected link version", value=str(decided.version), field_type="hidden"),
                        view_models._field("reason", "Reason for removing the link", field_type="textarea", required=True),
                    ),
                ),
                "dom_id": "remove-link",
                "preview": _preview(
                    f"{record_id} is no longer linked to {_party_label(session, decided.entity_id)}.",
                    (f"{dependents_text} that depend on this identity are marked for recheck." if dependents_total else "No application relationship changes."),
                    "The source record and the master record keep every value.",
                    "The source record has no link again; propose candidates to link it.",
                ),
            }
        )
    actions.append(
        {
            **_action(
                session,
                actor,
                action_id="change.request",
                label="Request source correction",
                path="/ui/actions/change.request",
                permission="correction.request.submit",
                destination="Configured steward queue",
                description="Ask the system that owns the value to correct it. A corrected value appears here only after the source changes.",
                fields=(
                    view_models._field("target_type", "Target type", value="source_record", field_type="hidden"),
                    view_models._field("target_id", "Target", value=record_id, field_type="hidden"),
                    view_models._field("change_kind", "Change kind", value="factual", field_type="hidden"),
                    view_models._field("title", "Summary", required=True),
                    view_models._field("reason", "Reason", field_type="textarea", required=True),
                    view_models._field("proposed_value", "Corrected value (JSON, optional)", field_type="textarea"),
                ),
            ),
            "dom_id": "request-correction",
            "preview": _preview(
                "No record is linked or unlinked.",
                "No application relationship changes.",
                f"The source value is not changed here. It changes only after {source_label} accepts the request.",
                "A change case opens in this queue under Awaiting source; this issue stays open.",
            ),
        }
    )

    # 6. What happened.
    events = _events_for(session, [record_id], ("registry.crosswalk",))
    result = None
    if decided is not None:
        result = {
            "text": {
                "approved": f"Linked to {_party_label(session, decided.entity_id)}",
                "rejected": f"Rejected: not {_party_label(session, decided.entity_id)}",
                "no_match": "Recorded as no match",
                "removed": f"Link to {_party_label(session, decided.entity_id)} removed",
            }.get(decided.link_status, display.pretty(decided.link_status)),
            "who": view_models.actor_label(session, decided.decision_actor_id),
            "when": _iso(decided.decided_at),
            "note": decided.decision or "",
        }
    provenance = {"label": "Deterministic matcher", "detail": "No model was used for this proposal.", "run_id": ""}
    if proposal.model_run_id:
        run = session.get(model_run.ModelRun, proposal.model_run_id)
        mode = run.mode if run is not None else "unknown"
        provenance = {
            "label": {"replay": "Recorded replay", "live": "Muse Spark (live)"}.get(mode, f"Muse ({mode})"),
            "detail": "A model proposed this link; a steward decides.",
            "run_id": proposal.model_run_id,
        }
    return {
        "kind": "link",
        "id": proposal.id,
        "record_name": name,
        "record_reference": record_id,
        "source_name": source_label,
        "record_type": _party_type(session, lead["entity_id"] if lead else None),
        "title": (
            f"{record_id}" + (f": {name}" if name else "")
        ),
        "status": "resolved" if decided is not None else "needs_review",
        "status_label": STATUS_LABELS["resolved" if decided is not None else "needs_review"],
        "problem": problem,
        "why": why,
        "applications": applications,
        "source_record": {
            "id": record_id,
            "source": source_label,
            "summary": source_summary(session, system_id, dataset_key, record_id),
            "name": name,
        },
        "candidates": candidates,
        "selected_candidate": chosen,
        "recommended_candidate": lead,
        "similar_note": (
            "A similar name does not make these the same organization. Each candidate stays its own record."
            if len(candidates) > 1
            else ""
        ),
        "lead": lead,
        "provenance": provenance,
        "evidence_detail_id": proposal.id,
        "actions": actions,
        "result": result,
        "events": events,
        "target_ids": {row.id for row in rows} | {record_id},
        "separate_note": (
            "Resolving this identity issue does not decide any permit. The Permit Reviewer decides permits separately."
        ),
        "decided_status": decided.link_status if decided is not None else "",
    }


def parcel_case(session: Session, actor: ActorContext, application_id: str) -> dict[str, Any]:
    """Return the focused case of a parcel link, answering the six questions in order."""
    application = session.get(permit.Application, application_id)
    match = session.execute(
        select(gis.ApplicationParcelMatch).where(gis.ApplicationParcelMatch.application_id == application_id)
    ).scalar_one_or_none()
    if application is None or match is None:
        return {}
    proposals = [
        item
        for item in property_views.steward_parcel_proposals(session, actor)
        if item["application_id"] == application_id
    ]
    proposal = proposals[0] if proposals else None
    waiting = proposal is not None
    outstanding = _outstanding_for(
        session,
        [{"number": application.source_application_number, "href": f"/permits/{application.id}", "status": display.pretty(application.status)}],
    )
    actions = []
    if proposal is not None:
        for label, decision_value, preview in (
            (
                "Approve parcel link",
                "approve",
                _preview(
                    f"Links {application.source_application_number} to parcel {proposal['parcel_number'] or 'none'}.",
                    "The application's property relationship becomes the approved parcel. The Permit Reviewer still confirms the parcel.",
                    "The typed address text is kept as submitted; the locator result is kept as evidence.",
                    "The parcel issue closes. A unit, if the parcel has units, is a separate question.",
                ),
            ),
            (
                "Reject parcel link",
                "reject",
                _preview(
                    "No parcel is linked.",
                    "The application stays without a parcel until another candidate is proposed.",
                    "The typed address text is kept as submitted.",
                    "The issue closes as rejected; the application still needs a parcel.",
                ),
            ),
        ):
            item = _action(
                session,
                actor,
                action_id="parcel.link.decide",
                label=f"{label} for {proposal['number']}",
                path="/ui/actions/parcel.link.decide",
                permission="registry.crosswalk.decide",
                domain_id="parcels",
                destination="Parcel link (identity)",
                description="The Data Steward approves the identity link between the application and the parcel.",
                expected_version=proposal["version"],
                state_allowed=decision_value == "reject" or proposal["can_approve"],
                state_reason="This proposal names no parcel; reject it or choose another candidate.",
                fields=(
                    view_models._field("application_id", "Application", value=proposal["application_id"], field_type="hidden"),
                    view_models._field("decision", "Decision", value=decision_value, field_type="hidden"),
                    view_models._field("expected_version", "Expected version", value=str(proposal["version"]), field_type="hidden"),
                    view_models._field("reason", "Decision note", field_type="textarea", required=True),
                ),
            )
            item["application_id"] = proposal["application_id"]
            item["preview"] = preview
            item["dom_id"] = f"{decision_value}-parcel"
            actions.append(item)
    events = _events_for(session, [match.id, application_id], ("parcel.",))
    result = None
    if match.link_state in ("approved", "rejected"):
        result = {
            "text": f"Parcel link {match.link_state}",
            "who": view_models.actor_label(session, match.decided_by),
            "when": _iso(match.decided_at),
            "note": match.decision_reason or "",
        }
    return {
        "kind": "parcel",
        "id": application_id,
        "record_name": match.submitted_text or "",
        "record_reference": application.source_application_number,
        "source_name": "GIS: Address locator (simulated)",
        "record_type": "parcel",
        "title": f"Parcel link for {application.source_application_number}",
        "status": "needs_review" if waiting else "resolved",
        "status_label": STATUS_LABELS["needs_review" if waiting else "resolved"],
        "problem": (
            f"The applicant typed “{match.submitted_text}”. The address locator proposed "
            + (f"{match.matched_address} on parcel {match.parcel_number}." if match.parcel_number else "no single parcel; a person must choose.")
        ),
        "why": f"{application.source_application_number} cannot be decided until its parcel link is approved and the Permit Reviewer confirms the parcel.",
        "applications": outstanding,
        "parcel": proposal,
        "comparison": typed_comparison(
            [
                {
                    "field": "Address",
                    "source": match.submitted_text or "No value",
                    "master": match.matched_address or "No value",
                    "result": (
                        "agrees"
                        if match.matched_address and _norm(match.submitted_text) == _norm(match.matched_address)
                        else ("conflicts" if match.matched_address else "no_comparison")
                    ),
                    "note": "",
                    "source_normalized": normalize_address(match.submitted_text).normalized,
                    "master_normalized": normalize_address(match.matched_address).normalized,
                }
            ],
            family="parcel",
            caption="What the applicant typed against what the locator found",
            headers={"source": "Submitted", "master": "Found by the locator"},
        ),
        "actions": actions,
        "result": result,
        "events": events,
        "target_ids": {match.id, application_id},
        "separate_note": "Approving a parcel link is an identity decision. The Permit Reviewer confirms the parcel, and decides the permit separately.",
        "evidence_detail_id": "",
    }


def case_case(session: Session, actor: ActorContext, case_id: str) -> dict[str, Any]:
    """Return the focused case of a change request (a source correction)."""
    case = session.get(change.ChangeCase, case_id)
    if case is None:
        return {}
    synthetic = _synthetic_ids(session)
    view = None
    try:
        from acme_city.changes.service import ChangeService

        view = ChangeService(session).case_view(case)
    except Exception:
        view = None
    status = (
        "needs_review"
        if case.status in CASE_NEEDS_REVIEW
        else "awaiting_source"
        if case.status in CASE_AWAITING_SOURCE
        else "resolved"
    )
    keys = sorted(set(case.old_value or {}) | set(case.proposed_value or {}))
    rows = [
        {
            "field": display.pretty(key),
            "source": str((case.old_value or {}).get(key, "No value")),
            "master": str((case.proposed_value or {}).get(key, "No value")),
            "result": "conflicts" if (case.old_value or {}).get(key) != (case.proposed_value or {}).get(key) else "agrees",
            "note": "",
            "source_normalized": "",
            "master_normalized": "",
        }
        for key in keys
    ]
    target_party = case.target_id if case.target_type == "party" else None
    applications = _outstanding_for(session, _applications_of(session, [target_party], synthetic)) if target_party else []
    targets = view.allowed_transitions if view is not None else []
    actions = []
    if targets:
        actions.append(
            {
                **_action(
                    session,
                    actor,
                    action_id="change.transition",
                    label="Move change case",
                    path="/ui/actions/change.transition",
                    permission="change.case.transition",
                    domain_id="applicants",
                    destination="Configured steward queue",
                    description="Move the case to the next permitted state.",
                    expected_version=case.version,
                    fields=(
                        view_models._field("change_case_id", "Change case", value=case.id, field_type="hidden"),
                        view_models._field("to_status", "New state", field_type="select", options=tuple(targets), required=True),
                        view_models._field("expected_version", "Expected case version", value=str(case.version), field_type="hidden"),
                        view_models._field("reason", "Decision note", field_type="textarea"),
                    ),
                ),
                "dom_id": "move-case",
                "preview": _preview(
                    "No record is linked or unlinked.",
                    "No application relationship changes until the source accepts the change.",
                    "A corrected value appears only after the source changes. Nothing here overwrites the source.",
                    "The case moves to the state you choose: " + ", ".join(display.pretty(t) for t in targets) + ".",
                ),
            }
        )
    events = _events_for(session, [case.id], ("change.",))
    commands = [
        {
            "operation": command.operation,
            "source": display.source_name(session, command.source_system_id),
            "expected": command.expected_source_version or "",
            "accepted": command.accepted_source_version or "",
            "status": display.pretty(command.status),
        }
        for command in session.execute(
            select(change.SourceCommand)
            .where(change.SourceCommand.change_case_id == case.id)
            .order_by(change.SourceCommand.id)
        ).scalars()
    ]
    deliveries = [
        {
            "destination": delivery.destination,
            "status": display.pretty(delivery.status),
            "attempts": delivery.attempts,
            "acknowledged": _iso(delivery.acknowledged_at),
            "error": delivery.last_error or "",
        }
        for delivery in session.execute(
            select(change.OutboxDelivery)
            .where(change.OutboxDelivery.change_case_id == case.id)
            .order_by(change.OutboxDelivery.id)
        ).scalars()
    ]
    return {
        "kind": "case",
        "commands": commands,
        "deliveries": deliveries,
        "id": case.id,
        "record_name": _party_label(session, target_party) if target_party else case.title,
        "record_reference": case.id,
        "source_name": case.destination or "Configured steward queue",
        "record_type": "correction",
        "title": case.title,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "problem": case.reason or case.title,
        "why": "Applications that depend on this record are rechecked when the source accepts the change.",
        "applications": applications,
        "comparison": typed_comparison(
            rows,
            family="change",
            caption="Current value against the proposed value",
            headers={"source": "Current", "master": "Proposed"},
        ),
        "case_evidence": [str(item) for item in (case.evidence or [])],
        "destination": case.destination or "Configured steward queue",
        "state_label": display.pretty(case.status),
        "actions": actions,
        "result": None
        if status != "resolved"
        else {"text": display.pretty(case.status), "who": view_models.actor_label(session, case.approver_actor_id), "when": None, "note": ""},
        "events": events,
        "target_ids": {case.id},
        "separate_note": "A source correction request is not a permit decision.",
        "evidence_detail_id": "",
    }


def governance_case(session: Session, actor: ActorContext, issue_id: str) -> dict[str, Any]:
    """Return the focused case of a recorded governance issue."""
    row = session.get(change.GovernanceIssue, issue_id)
    if row is None:
        return {}
    synthetic = _synthetic_ids(session)
    party = session.get(registry.Party, row.subject_id)
    applications = (
        _outstanding_for(session, _applications_of(session, [row.subject_id], synthetic)) if party is not None else []
    )
    status = "needs_review" if row.status == "open" else "resolved"
    return {
        "kind": "issue",
        "id": row.id,
        "record_name": party.display_name if party is not None else str(row.subject_id),
        "record_reference": row.id,
        "source_name": row.responsible_queue_id or "Steward queue",
        "record_type": "issue",
        "title": row.description,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "problem": row.description,
        "why": "This issue is recorded against "
        + (party.display_name if party is not None else row.subject_id)
        + (" and blocks work until it is resolved." if row.blocking else "."),
        "applications": applications,
        "compare_rows": [],
        "actions": [],
        "result": None,
        "events": _events_for(session, [row.id, row.subject_id], ("change.", "registry.", "source.")),
        "target_ids": {row.id},
        "separate_note": "Resolving a data issue is separate from deciding a permit.",
        "evidence_detail_id": "",
    }


def focused_case(
    session: Session, actor: ActorContext, kind: str, item_id: str, selected_id: str = ""
) -> dict[str, Any]:
    """Return the focused case for one queue address, or an empty dict."""
    case = _focused_case(session, actor, kind, item_id, selected_id)
    if case:
        case["summary"] = _case_summary(case)
    return case


def _focused_case(
    session: Session, actor: ActorContext, kind: str, item_id: str, selected_id: str = ""
) -> dict[str, Any]:
    """Build the focused case of one queue address."""
    if kind == "linked":
        crosswalk = session.get(registry.Crosswalk, item_id)
        if crosswalk is None:
            return {}
        return _linked_case(session, actor, crosswalk)
    builder = {"link": link_case, "parcel": parcel_case, "case": case_case, "issue": governance_case}.get(kind)
    if builder is None:
        return {}
    if kind == "link":
        return builder(session, actor, item_id, selected_id=selected_id)
    return builder(session, actor, item_id)


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    """Return the compact summary of a focused case.

    The summary names the task, the record, the source, the status, the
    affected applications and the next step.  It repeats nothing the six
    questions below it already say, so the steward reads the situation once
    and then the evidence.
    """
    kind = str(case.get("kind", ""))
    task = steward_queue_views.TASK_TITLES.get(kind, steward_queue_views.TASK_TITLES["issue"])
    if kind in ("link", "linked"):
        task = steward_queue_views.IDENTITY_TASKS.get(str(case.get("record_type", "")), task)
    status = str(case.get("status", "needs_review"))
    steps = CLOSED_NEXT_STEPS if status == "resolved" else OPEN_NEXT_STEPS
    applications = list(case.get("applications") or [])
    return {
        "task": task,
        "record": str(case.get("record_name", "")),
        "reference": str(case.get("record_reference", "")),
        "source": str(case.get("source_name", "")),
        "status": status,
        "status_label": str(case.get("status_label", "")),
        "application_count": len(applications),
        "next_step": steps.get(kind, OPEN_NEXT_STEPS["issue"]),
    }


def _linked_case(session: Session, actor: ActorContext, crosswalk: registry.Crosswalk) -> dict[str, Any]:
    """A decided link that has no stored proposal (for example one decided through the API)."""
    lead = _party_label(session, crosswalk.entity_id)
    synthetic = _synthetic_ids(session)
    return {
        "kind": "linked",
        "id": crosswalk.id,
        "record_name": lead,
        "record_reference": crosswalk.source_record_id,
        "source_name": display.source_name(session, crosswalk.source_system_id, crosswalk.source_dataset_key),
        "record_type": _party_type(session, crosswalk.entity_id),
        "title": f"{crosswalk.source_record_id}: {display.pretty(crosswalk.link_status)}",
        "status": "resolved",
        "status_label": STATUS_LABELS["resolved"],
        "problem": f"Source record {crosswalk.source_record_id} from {display.source_name(session, crosswalk.source_system_id, crosswalk.source_dataset_key)} has a recorded link decision for {lead}.",
        "why": "Applications that name this record use the link.",
        "applications": _outstanding_for(session, _applications_of(session, [crosswalk.entity_id], synthetic)),
        "compare_rows": [],
        "actions": [],
        "result": {
            "text": display.pretty(crosswalk.link_status),
            "who": view_models.actor_label(session, crosswalk.decision_actor_id),
            "when": _iso(crosswalk.decided_at),
            "note": crosswalk.decision or "",
        },
        "events": _events_for(session, [crosswalk.source_record_id], ("registry.crosswalk",)),
        "target_ids": {crosswalk.id, crosswalk.source_record_id},
        "separate_note": "Resolving an identity issue is separate from deciding a permit.",
        "evidence_detail_id": "",
    }


# ------------------------------------------------------------ evidence drawer


def _resolve_evidence(ctx: DetailContext, proposal_id: str) -> DetailView | None:
    proposal = ctx.session.get(registry.MatchProposal, proposal_id)
    if proposal is None:
        return None
    snap = ctx.session.get(source.SourceSnapshot, proposal.source_snapshot_id)
    sections = []
    for heading, items in (
        ("Agreements", proposal.supporting_evidence or []),
        ("Conflicts", proposal.conflicting_evidence or []),
    ):
        rows = tuple(
            Row(
                f"{display.pretty(item.get('field', ''))}: {_evidence_phrase(str(item.get('method', '')))}",
                f"Source value {item.get('raw_value')!s}; compared as {item.get('normalized_value')!s}. {item.get('detail', '')}",
            )
            for item in items
        )
        sections.append(Section(heading, rows) if rows else Section(heading, lines=("None recorded.",)))
    sections.append(
        Section(
            "Technical identifiers",
            (
                Row("Proposal id", proposal.id, mono=True),
                Row("Method", proposal.method, mono=True),
                Row("Source snapshot", proposal.source_snapshot_id, mono=True),
                Row("Proposed", display.precise_time(proposal.created_at), mono=True),
                Row("Score is calibrated", "no" if not proposal.score_is_calibrated else "yes"),
            ),
        )
    )
    links = []
    if snap is not None:
        links.append(
            (
                "View source details",
                f"?detail=source:{snap.source_system_id}:{snap.source_dataset_id}:{snap.source_record_id}",
            )
        )
    return DetailView(title="Evidence for this match", sections=tuple(sections), links=tuple(links))


# ---------------------------------------------------------- source records page


def _source_domain(session: Session, system_id: str, dataset: str) -> str:
    """Return the domain the source contract of a dataset belongs to."""
    contract = session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.source_system_id == system_id,
            governance.SourceContract.dataset_key == dataset,
        )
    ).scalars().first()
    return contract.domain_id if contract is not None else "applicants"


def _find_matches_action(
    session: Session,
    actor: ActorContext,
    *,
    system_id: str,
    dataset: str,
    record_id: str,
    domain_id: str,
) -> dict[str, Any]:
    """Return the action that compares one source record with the master records."""
    return view_models.action(
        session,
        actor,
        action_id="registry.propose",
        label="Find matches",
        path="/ui/actions/registry.propose",
        permission="registry.crosswalk.propose",
        domain_id=domain_id,
        destination="Registry candidate comparison",
        description=(
            "Compare this source record with the master records and record the "
            "evidence. A steward still has to decide."
        ),
        fields=(
            view_models._field("source_system_id", "Source system", value=system_id, field_type="hidden"),
            view_models._field("dataset_key", "Dataset", value=dataset, field_type="hidden"),
            view_models._field("source_record_id", "Source record", value=record_id, field_type="hidden"),
        ),
    )


def source_records(
    session: Session,
    actor: ActorContext,
    *,
    system: str = "",
    query: str = "",
    page: int = 1,
    link_state: str = "",
) -> dict[str, Any]:
    """Return the source-record catalogue: accepted records with the master record each links to.

    Every row names the record a person recognizes, the source it came from,
    the state of its link and the one action that state asks for.  The search
    and the filters are read from the address of the request, so a steward can
    come back to the same catalogue.
    """
    latest: dict[tuple[str, str, str], source.SourceSnapshot] = {}
    for row in session.execute(
        select(source.SourceSnapshot).where(source.SourceSnapshot.record_status == "accepted")
    ).scalars():
        key = (row.source_system_id, row.source_dataset_id, row.source_record_id)
        current = latest.get(key)
        if current is None or (row.ingested_at, row.source_record_version or "") > (
            current.ingested_at,
            current.source_record_version or "",
        ):
            latest[key] = row
    links: dict[tuple[str, str], registry.Crosswalk] = {}
    for crosswalk in session.execute(select(registry.Crosswalk)).scalars():
        key = (crosswalk.source_system_id, crosswalk.source_record_id)
        existing = links.get(key)
        if existing is None or (crosswalk.link_status in ("approved",) and existing.link_status != "approved") or (
            existing.link_status not in ("approved", "proposed") and crosswalk.link_status == "proposed"
        ):
            links[key] = crosswalk
    proposals: dict[tuple[str, str], registry.MatchProposal] = {}
    for proposal in session.execute(
        select(registry.MatchProposal).order_by(registry.MatchProposal.created_at, registry.MatchProposal.id)
    ).scalars():
        snapshot = session.get(source.SourceSnapshot, proposal.source_snapshot_id)
        if snapshot is None:
            continue
        proposals[(snapshot.source_system_id, snapshot.source_record_id)] = proposal
    needle = query.strip().lower()
    by_system: dict[str, int] = defaultdict(int)
    by_state: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    for (system_id, dataset, record_id), snapshot in sorted(latest.items()):
        payload = dict(snapshot.raw_payload or {})
        name = _payload_values(
            payload,
            (
                "organization_name",
                "holder_name",
                "display_name",
                "full_name",
                "applicant_name",
                "name",
            ),
        )
        text = f"{record_id} {name} {display.source_name(session, system_id, dataset)}".lower()
        if needle and needle not in text:
            continue
        by_system[system_id] += 1
        if system and system != system_id:
            continue
        crosswalk = links.get((system_id, record_id))
        proposal = proposals.get((system_id, record_id))
        action = None
        if dataset not in LINKABLE_DATASETS:
            linked = "Not a record that links to a master record"
            state = "not_linkable"
            detail = ""
            action_label = ""
            action_href = ""
        elif crosswalk is None:
            linked = "Not linked"
            state = "not_compared"
            detail = "Not linked"
            action_label = "Find matches"
            action_href = ""
            action = _find_matches_action(
                session,
                actor,
                system_id=system_id,
                dataset=dataset,
                record_id=record_id,
                domain_id=_source_domain(session, system_id, dataset),
            )
        elif crosswalk.link_status == "proposed":
            linked = "Match waiting for a decision"
            state = "proposed"
            detail = "Match waiting for a decision"
            action_label = "Review match"
            action_href = (
                f"/steward/issues/link/{proposal.id}" if proposal is not None else ""
            )
        elif crosswalk.link_status == "approved":
            linked = _party_label(session, crosswalk.entity_id)
            state = "linked"
            detail = ""
            action_label = "View master record"
            action_href = f"/masters/{crosswalk.entity_id}"
        else:
            linked = display.pretty(crosswalk.link_status)
            state = "decided"
            detail = display.pretty(crosswalk.link_status)
            action_label = "Review next step"
            action_href = f"/steward/issues/linked/{crosswalk.id}"
        by_state[state] += 1
        rows.append(
            {
                "source": display.source_name(session, system_id, dataset),
                "name": name or record_id,
                "record_id": record_id,
                "version": snapshot.source_record_version or "",
                "changed": _iso(snapshot.source_updated_at),
                "received": _iso(snapshot.ingested_at),
                "linked": linked,
                "linked_ref": _ref("record", crosswalk.entity_id) if state == "linked" else "",
                "state": state,
                "state_label": SOURCE_LINK_STATES.get(state, ("", ""))[0],
                "detail": detail,
                "action_label": action_label,
                "action_href": action_href,
                "action": action,
                "detail_id": f"{system_id}:{dataset}:{record_id}",
                "scenario": snapshot.scenario_id or "",
            }
        )
    if link_state:
        rows = [row for row in rows if row["state"] == link_state]
    window, paging = _page(rows, page)
    systems = [
        {
            "key": system_id,
            "label": display.source_name(session, system_id),
            "count": count,
            "active": system == system_id,
            "href": _href("/source-records", system=system_id, q=query, link_state=link_state),
        }
        for system_id, count in sorted(by_system.items())
    ]
    states = [
        {
            "key": key,
            "label": label,
            "count": by_state.get(key, 0),
            "active": link_state == key,
            "href": _href("/source-records", system=system or None, q=query, link_state=key),
        }
        for key, label in SOURCE_LINK_STATES.items()
    ]
    return {
        "rows": window,
        "paging": paging,
        "systems": systems,
        "states": states,
        "all_count": sum(by_system.values()),
        "all_href": _href("/source-records", q=query, link_state=link_state),
        "system": system,
        "query": query,
        "link_state": link_state,
    }


# ------------------------------------------------------------------- activity

#: What the Activity screen shows: steward decisions and changes, not the audit log.
ACTIVITY_PREFIXES = ("registry.crosswalk", "change.case", "change.command", "parcel.", "source.record", "extraction.")


def activity(session: Session, actor: ActorContext, *, page: int = 1) -> dict[str, Any]:
    """Return recorded steward decisions and changes."""
    synthetic = _synthetic_ids(session)
    rows = session.execute(
        select(audit.AuditEvent).order_by(audit.AuditEvent.occurred_at.desc())
    ).scalars().all()
    entries = []
    for row in rows:
        if not any(row.action.startswith(prefix) for prefix in ACTIVITY_PREFIXES):
            continue
        if row.target_id in synthetic:
            continue
        entries.append(
            {
                "when": _iso(row.occurred_at),
                "who": view_models.actor_label(session, row.actor_id),
                "what": _pretty_action(row.action),
                "target": row.target_id or "",
                "note": row.reason or row.denial_reason or "",
                "outcome": "Refused" if row.outcome == "denied" else "Recorded",
                "outcome_key": row.outcome,
                "href": _activity_href(session, row),
            }
        )
    window, paging = _page(entries, page)
    return {"rows": window, "paging": paging}


def _activity_href(session: Session, row: audit.AuditEvent) -> str:
    if row.target_type == "source_record" and row.target_id:
        proposal = session.execute(
            select(registry.MatchProposal)
            .join(source.SourceSnapshot, source.SourceSnapshot.source_snapshot_id == registry.MatchProposal.source_snapshot_id)
            .where(source.SourceSnapshot.source_record_id == row.target_id)
            .order_by(registry.MatchProposal.created_at.desc())
        ).scalars().first()
        if proposal is not None:
            return f"/steward/issues/link/{proposal.id}"
    if row.target_type == "change_case" and row.target_id:
        return f"/steward/issues/case/{row.target_id}"
    return ""


# ------------------------------------------------------------ registration


def register() -> None:
    """Register the detail kinds of the steward screens (idempotent)."""
    patterns.register_detail("record", _resolve_record, label="Record profile", any_grant=RECORD_GRANTS)
    patterns.register_detail("record-sources", _resolve_record_sources, label="Record sources", any_grant=RECORD_GRANTS)
    patterns.register_detail("record-history", _resolve_record_history, label="Record history", any_grant=RECORD_GRANTS)
    patterns.register_detail("applications", _resolve_applications, label="Applications", any_grant=RECORD_GRANTS)
    patterns.register_detail("source", _resolve_source, label="Source details", any_grant=SOURCE_GRANTS)
    patterns.register_detail("credential", _resolve_credential, label="License or registration", any_grant=MASTER_GRANTS)
    patterns.register_detail("parcel", _resolve_parcel, label="Property", any_grant=MASTER_GRANTS)
    patterns.register_detail("evidence", _resolve_evidence, label="Match evidence", any_grant=STEWARD_GRANTS)


register()

__all__ = [
    "MASTER_TABS",
    "QUEUE_FILTERS",
    "activity",
    "collect_issues",
    "compare_with_party",
    "credentials_collection",
    "data_issues",
    "focused_case",
    "freshness_warning",
    "people_collection",
    "properties_collection",
    "record_profile",
    "register",
    "source_records",
    "source_summary",
]

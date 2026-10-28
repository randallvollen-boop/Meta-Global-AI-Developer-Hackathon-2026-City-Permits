"""One bulk read of the permit history, shared by the City view and the public view.

Every figure the insight screens show is computed from these rows.  The rows
are plain data: no ORM object leaves this module, so a screen can only show
what a field below names.  The public read model builds its own allowlist on
top and adds the exclusions (drafts, withdrawn, returned, archived).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.gis.catalog import PropertyCatalog
from acme_city.persistence.models import permit, registry

#: The statuses that count as permit activity in the City view.
ACTIVITY_EXCLUDED_STATUSES: frozenset[str] = frozenset({"draft", "archived"})


@dataclass
class PermitRow:
    """One application with the facts the insight screens use."""

    application_id: str
    number: str
    permit_number: str | None
    type_key: str
    type_label: str
    district: str
    parcel_number: str
    address: str
    description: str
    status: str
    submitted_at: datetime | None
    decided_at: datetime | None
    issued_at: datetime | None
    decision_outcome: str | None
    conditions: list[str]
    waivers: int
    category: str | None
    contractor: str
    synthetic: bool
    archived: bool
    exception_kinds: list[str] = field(default_factory=list)

    @property
    def outcome_key(self) -> str:
        """``approved``, ``conditions``, ``denied`` or ``undecided``."""
        if self.decision_outcome == "denied":
            return "denied"
        if self.decision_outcome == "approved":
            return "conditions" if self.conditions else "approved"
        return "undecided"


def load_rows(session: Session) -> list[PermitRow]:
    """Return every application as a :class:`PermitRow`, oldest first."""
    types = {row.permit_type_id: row for row in session.execute(select(permit.PermitType)).scalars()}
    sites = {
        row.application_id: row
        for row in session.execute(
            select(permit.ApplicationSite).order_by(
                permit.ApplicationSite.is_primary.asc(), permit.ApplicationSite.id
            )
        ).scalars()
    }
    parcels_by_id = {row.id: row for row in session.execute(select(registry.Parcel)).scalars()}
    catalog = PropertyCatalog(session)
    address_text: dict[str, str] = {}

    def official_address(parcel: registry.Parcel) -> str:
        if parcel.id not in address_text:
            text = catalog.site_address(parcel)
            address_text[parcel.id] = f"{text}, ACME City" if text else ""
        return address_text[parcel.id]

    decisions: dict[str, permit.Decision] = {}
    for decision in session.execute(
        select(permit.Decision)
        .where(permit.Decision.status == "current")
        .order_by(permit.Decision.decided_at)
    ).scalars():
        decisions[decision.application_id] = decision
    permits_by_app: dict[str, permit.Permit] = {}
    for issued in session.execute(select(permit.Permit).order_by(permit.Permit.issued_at)).scalars():
        permits_by_app[issued.application_id] = issued

    parties = {row.id: row for row in session.execute(select(registry.Party)).scalars()}
    business_category: dict[str, str] = {}
    for credential in session.execute(
        select(registry.Credential).where(registry.Credential.credential_type == "business_license")
    ).scalars():
        if credential.business_category:
            business_category[credential.holder_party_id] = credential.business_category
    contractor_of: dict[str, str] = {}
    category_of: dict[str, str] = {}
    for link in session.execute(
        select(permit.ApplicationParty).order_by(permit.ApplicationParty.id)
    ).scalars():
        party = parties.get(link.party_id)
        if party is None:
            continue
        if link.party_role == "contractor" and party.party_type == "organization":
            contractor_of.setdefault(link.application_id, party.display_name)
        if link.party_id in business_category:
            category_of.setdefault(link.application_id, business_category[link.party_id])

    rows: list[PermitRow] = []
    applications = session.execute(
        select(permit.Application).order_by(
            permit.Application.initial_submitted_at, permit.Application.source_application_number
        )
    ).scalars()
    for application in applications:
        type_row = types.get(application.permit_type_id)
        if type_row is None:
            continue
        site = sites.get(application.id)
        parcel = parcels_by_id.get(site.parcel_id) if site is not None and site.parcel_id else None
        decision = decisions.get(application.id)
        issued = permits_by_app.get(application.id)
        facts: dict[str, Any] = application.submitted_facts or {}
        conditions = [str(item) for item in (decision.conditions or [])] if decision else []
        waivers = len(decision.waivers or []) if decision else 0
        row = PermitRow(
            application_id=application.id,
            number=application.source_application_number,
            permit_number=issued.permit_number if issued is not None else None,
            type_key=type_row.key,
            type_label=type_row.label,
            district=(parcel.zoning_code if parcel is not None else "") or "",
            parcel_number=parcel.source_parcel_number if parcel is not None else "",
            address=(
                official_address(parcel)
                if parcel is not None and official_address(parcel)
                else (site.submitted_address_text if site is not None else "") or ""
            ),
            description=str(application.description or facts.get("project_description") or ""),
            status=application.status,
            submitted_at=application.initial_submitted_at,
            decided_at=decision.decided_at if decision else None,
            issued_at=issued.issued_at if issued is not None else None,
            decision_outcome=decision.outcome if decision else None,
            conditions=conditions,
            waivers=waivers,
            category=category_of.get(application.id),
            contractor=contractor_of.get(application.id, ""),
            synthetic=bool(application.synthetic),
            archived=application.archived_at is not None or application.status == "archived",
        )
        kinds: list[str] = []
        if row.type_key == "zoning_variance":
            kinds.append("variance")
        if waivers:
            kinds.append("waiver")
        if row.decision_outcome == "denied":
            kinds.append("denial")
        if row.decision_outcome == "approved" and conditions:
            kinds.append("conditions")
        row.exception_kinds = kinds
        rows.append(row)
    return rows


__all__ = ["ACTIVITY_EXCLUDED_STATUSES", "PermitRow", "load_rows"]

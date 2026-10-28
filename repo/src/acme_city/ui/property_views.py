"""View models of the property master: the Property card, the record and the map.

Everything here reads the registry tables that the simulated GIS also serves,
so the screens and the simulated ArcGIS services can never disagree.  The
parcel number is the key; an address is only a way to find a parcel.
"""
# REQUIRES: GIS-05, GIS-06
# The parcel is the key; the reviewer sees the typed address, the standardized
# address, the parcel number, the locator score and the other candidates.

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.gis import svg
from acme_city.gis.catalog import SIMULATED_LABEL, PropertyCatalog, full_address
from acme_city.gis.matching import ParcelMatchService
from acme_city.persistence.models import gis, permit, registry

#: What the locator status letters mean, in plain words.
STATUS_WORDS: dict[str, str] = {
    "M": "Match (M)",
    "T": "Tie (T)",
    "U": "Unmatched (U)",
}

#: The plain label of every state of the parcel link.
LINK_LABELS: dict[str, str] = {
    "proposed": "Proposed, waiting for the Data Steward",
    "needs_choice": "A person must choose the property",
    "not_found": "Not found in the city locator",
    "approved": "Approved by the Data Steward",
    "rejected": "Rejected by the Data Steward",
}

DEPARTMENT_NOTICE = (
    "These departments are simulated consumers. No tax, fire, code enforcement or "
    "utility system is built; each row shows what one shared property master would "
    "give a department. Every signal is synthetic."
)


def _money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.0f}"


def parcel_summary(parcel: registry.Parcel) -> dict[str, Any]:
    """Return the attributes of one parcel the screens show."""
    total = (parcel.land_value_cents or 0) + (parcel.improvement_value_cents or 0)
    return {
        "parcel_number": parcel.source_parcel_number,
        "owner": parcel.owner_name or "unknown",
        "use": parcel.use_description or "unknown",
        "use_code": parcel.use_code or "",
        "zoning": parcel.zoning_code or "unknown",
        "subdivision": parcel.subdivision or "",
        "acres": parcel.area_acres,
        "land_value": _money(parcel.land_value_cents),
        "improvement_value": _money(parcel.improvement_value_cents),
        "assessed_value": _money(total),
        "tax_district": parcel.tax_district or "",
        "school_district": parcel.school_district or "",
        "flood_zone": parcel.flood_zone or "unknown",
    }


def parcel_addresses(session: Session, parcel: registry.Parcel) -> list[dict[str, Any]]:
    """Return every address and unit on a parcel."""
    rows = session.execute(
        select(registry.Address)
        .join(registry.ParcelAddress, registry.ParcelAddress.address_id == registry.Address.id)
        .where(
            registry.ParcelAddress.parcel_id == parcel.id,
            registry.ParcelAddress.effective_to.is_(None),
        )
        .order_by(registry.Address.source_string)
    ).scalars().all()
    return [
        {
            "address_id": row.address_id,
            "label": full_address(row),
            "unit": row.unit_number or "",
            "kind": "Unit" if row.unit_number else "Building",
        }
        for row in rows
    ]


def parcel_applications(
    session: Session, actor: ActorContext, parcel: registry.Parcel
) -> list[dict[str, Any]]:
    """Return the applications and permits on a parcel, as the actor may see them."""
    from acme_city.ui.view_models import _application_in_scope

    application_ids = {
        site.application_id
        for site in session.execute(
            select(permit.ApplicationSite).where(permit.ApplicationSite.parcel_id == parcel.id)
        ).scalars().all()
    }
    application_ids |= {
        match.application_id
        for match in session.execute(
            select(gis.ApplicationParcelMatch).where(
                gis.ApplicationParcelMatch.parcel_id == parcel.id
            )
        ).scalars().all()
    }
    rows = []
    for application_id in sorted(application_ids):
        application = session.get(permit.Application, application_id)
        if application is None or not _application_in_scope(actor, application):
            continue
        permit_type = session.get(permit.PermitType, application.permit_type_id)
        rows.append(
            {
                "application_id": application.id,
                "number": application.source_application_number,
                "permit_type": permit_type.label if permit_type else application.permit_type_id,
                "status": application.status,
                "status_label": svg._mark(application.status)[1],
                "href": f"/permits/{application.id}",
            }
        )
    return rows


def _markers_by_parcel(
    session: Session, actor: ActorContext, only_application: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Return the permit markers of each parcel row id."""
    from acme_city.ui.view_models import _application_in_scope

    parcel_of: dict[str, str] = {}
    for site in session.execute(select(permit.ApplicationSite)).scalars().all():
        if site.parcel_id:
            parcel_of[site.application_id] = site.parcel_id
    for match in session.execute(select(gis.ApplicationParcelMatch)).scalars().all():
        if match.parcel_id and match.application_id not in parcel_of:
            parcel_of[match.application_id] = match.parcel_id
    markers: dict[str, list[dict[str, Any]]] = {}
    for application_id, parcel_row_id in sorted(parcel_of.items()):
        if only_application and application_id != only_application:
            continue
        application = session.get(permit.Application, application_id)
        if application is None or not _application_in_scope(actor, application):
            continue
        markers.setdefault(parcel_row_id, []).append(
            {
                "number": application.source_application_number,
                "status": application.status,
                "application_id": application.id,
            }
        )
    return markers


def map_parcels(
    session: Session,
    actor: ActorContext,
    catalog: PropertyCatalog,
    *,
    subject: str = "",
    candidates: tuple[str, ...] = (),
    only_application: str | None = None,
    linked: bool = True,
) -> list[svg.MapParcel]:
    """Return the parcels of the town as the map draws them."""
    markers = _markers_by_parcel(session, actor, only_application)
    out = []
    for parcel in catalog.parcels():
        number = parcel.source_parcel_number
        role = "subject" if number == subject else "candidate" if number in candidates else ""
        out.append(
            svg.MapParcel(
                number=number,
                site_address=catalog.site_address(parcel),
                zoning=parcel.zoning_code or "",
                rings=parcel.geometry,
                href=f"/property/{number}" if linked else "",
                applications=markers.get(parcel.id, []),
                role=role,
            )
        )
    return out


def _street_rows(catalog: PropertyCatalog) -> list[dict[str, Any]]:
    return [
        {"street_key": row.street_key, "name": row.name, "path": row.path}
        for row in catalog.streets()
    ]


def application_property(
    session: Session, actor: ActorContext, application: permit.Application
) -> dict[str, Any] | None:
    """Return the Property card of one application, or ``None`` without a match."""
    match = ParcelMatchService(session).for_application(application.id)
    if match is None:
        return None
    catalog = PropertyCatalog(session)
    parcel = catalog.parcel_by_number(match.parcel_number) if match.parcel_number else None
    candidates = []
    for item in match.candidates or []:
        candidates.append(
            {
                **item,
                "status_word": STATUS_WORDS.get(str(item.get("status")), str(item.get("status"))),
                "current": item.get("address_id") == _address_key(session, match),
            }
        )
    parcels = map_parcels(
        session,
        actor,
        catalog,
        subject=match.parcel_number or "",
        candidates=tuple(
            sorted({str(c.get("parcel_number")) for c in candidates if c.get("parcel_number")})
        ),
        only_application=application.id,
        linked=False,
    )
    points = [
        svg.MapPoint(float(c["x"]), float(c["y"]), f"Candidate: {c['address']} (score {c['score']:g})", "candidate")
        for c in candidates
        if c.get("x") is not None
    ]
    if match.x is not None and match.y is not None:
        points.append(
            svg.MapPoint(
                float(match.x),
                float(match.y),
                f"Point of {match.matched_address or 'the located address'}",
                "address",
            )
        )
    inset = ""
    if match.parcel_number:
        inset = svg.parcel_inset_svg(
            parcels,
            match.parcel_number,
            points,
            caption=(
                f"Parcel {match.parcel_number} with the located address point and its "
                "neighbouring parcels"
            ),
            linked=False,
        )
    from acme_city.ui.view_models import allows

    can_open = allows(session, actor, "property.view")
    return {
        "match_id": match.id,
        "version": match.version,
        "submitted_text": match.submitted_text or "(no address text)",
        "matched_address": match.matched_address or "",
        "parcel_number": match.parcel_number or "",
        "score": match.score,
        "status": match.locator_status,
        "status_word": STATUS_WORDS.get(match.locator_status, match.locator_status),
        "state": match.link_state,
        "state_label": LINK_LABELS.get(match.link_state, match.link_state),
        "note": match.note or "",
        "method": match.method,
        "proposed_by": match.proposed_by or "",
        "decided_by": match.decided_by or "",
        "decision_reason": match.decision_reason or "",
        "confirmed_by": match.confirmed_by or "",
        "confirmed": match.confirmed_at is not None,
        "approved": match.link_state == "approved",
        "candidates": candidates,
        "parcel": parcel_summary(parcel) if parcel is not None else None,
        "inset": inset,
        "can_open": can_open,
        "map_href": f"/map?application={application.id}",
        "record_href": f"/property/{match.parcel_number}" if match.parcel_number and can_open else "",
        "simulated_label": SIMULATED_LABEL,
    }


def _address_key(session: Session, match: gis.ApplicationParcelMatch) -> str:
    if not match.address_id:
        return ""
    row = session.get(registry.Address, match.address_id)
    return row.address_id if row is not None else ""


def steward_parcel_proposals(session: Session, actor: ActorContext) -> list[dict[str, Any]]:
    """Return the open parcel-link proposals with their locator evidence."""
    catalog = PropertyCatalog(session)
    rows = []
    matches = session.execute(
        select(gis.ApplicationParcelMatch)
        .where(gis.ApplicationParcelMatch.link_state.in_(["proposed", "needs_choice", "not_found"]))
        .order_by(gis.ApplicationParcelMatch.created_at, gis.ApplicationParcelMatch.id)
    ).scalars().all()
    for match in matches:
        application = session.get(permit.Application, match.application_id)
        if application is None:
            continue
        parcel = catalog.parcel_by_number(match.parcel_number) if match.parcel_number else None
        candidate_numbers = tuple(
            sorted({str(c.get("parcel_number")) for c in match.candidates or [] if c.get("parcel_number")})
        )
        parcels = map_parcels(
            session,
            actor,
            catalog,
            subject=match.parcel_number or "",
            candidates=candidate_numbers,
            only_application=application.id,
            linked=False,
        )
        points = [
            svg.MapPoint(float(c["x"]), float(c["y"]), f"Candidate: {c['address']}", "candidate")
            for c in match.candidates or []
            if c.get("x") is not None
        ]
        inset = ""
        anchor = match.parcel_number or (candidate_numbers[0] if candidate_numbers else "")
        if anchor:
            inset = svg.parcel_inset_svg(
                parcels,
                anchor,
                points,
                caption=(
                    f"The submitted point against the candidate parcels for "
                    f"{application.source_application_number}"
                ),
                linked=False,
                margin=110.0,
            )
        rows.append(
            {
                "application_id": application.id,
                "number": application.source_application_number,
                "match_id": match.id,
                "version": match.version,
                "submitted_text": match.submitted_text or "(no address text)",
                "matched_address": match.matched_address or "",
                "parcel_number": match.parcel_number or "",
                "score": match.score,
                "status_word": STATUS_WORDS.get(match.locator_status, match.locator_status),
                "state": match.link_state,
                "state_label": LINK_LABELS.get(match.link_state, match.link_state),
                "note": match.note or "",
                "candidates": list(match.candidates or []),
                "parcel": parcel_summary(parcel) if parcel is not None else None,
                "inset": inset,
                "can_approve": match.link_state == "proposed" and bool(match.parcel_id),
                "href": f"/permits/{application.id}",
            }
        )
    return rows


def _collection_day(parcel: registry.Parcel) -> str:
    """Return the synthetic next collection day Sanitation plans for a parcel.

    The day follows the City's published trash days (Monday north, Tuesday
    south, here chosen by the parcel number) and a commercial parcel is
    collected three times a week.  It is a synthetic signal, not a schedule.
    """
    if (parcel.use_code or "").startswith("4"):
        return "Monday, Wednesday and Friday (commercial pickup)"
    digits = "".join(ch for ch in parcel.source_parcel_number if ch.isdigit())
    return "Monday" if int(digits or "0") % 2 == 0 else "Tuesday"


def _late_night_premises(session: Session, parcel: registry.Parcel) -> str:
    """Return the synthetic count of licensed late-night premises on a parcel.

    A premises counts when a business whose licence category is ``bar`` has a
    permit application sited on the parcel.
    """
    count = session.execute(
        select(func.count(func.distinct(registry.Credential.holder_party_id)))
        .select_from(permit.ApplicationSite)
        .join(
            permit.ApplicationParty,
            permit.ApplicationParty.application_id == permit.ApplicationSite.application_id,
        )
        .join(
            registry.Credential,
            registry.Credential.holder_party_id == permit.ApplicationParty.party_id,
        )
        .where(
            permit.ApplicationSite.parcel_id == parcel.id,
            registry.Credential.credential_type == "business_license",
            registry.Credential.business_category == "bar",
        )
    ).scalar_one()
    return str(count) if count else "none on file"


def subscribers_for(session: Session, parcel: registry.Parcel | None) -> list[dict[str, Any]]:
    """Return the simulated subscriber departments, with one signal each."""
    rows = session.execute(
        select(gis.DatasetSubscriber)
        .where(gis.DatasetSubscriber.dataset_key == "property_master")
        .order_by(gis.DatasetSubscriber.position)
    ).scalars().all()
    signals = dict(parcel.department_signals or {}) if parcel is not None else {}
    out = []
    for row in rows:
        value = "no parcel selected"
        if parcel is not None:
            if row.signal_key == "assessed_value":
                total = (parcel.land_value_cents or 0) + (parcel.improvement_value_cents or 0)
                value = _money(total)
            elif row.signal_key == "fire_last_inspection":
                value = str(signals.get("fire_last_inspection", "no inspection on file"))
            elif row.signal_key == "code_open_cases":
                value = str(signals.get("code_open_cases", 0))
            elif row.signal_key == "utility_account_active":
                value = "yes" if signals.get("utility_account_active", True) else "no"
            elif row.signal_key == "next_collection_day":
                value = str(
                    signals.get("next_collection_day") or _collection_day(parcel)
                )
            elif row.signal_key == "late_night_premises":
                value = str(
                    signals.get("late_night_premises")
                    if signals.get("late_night_premises") is not None
                    else _late_night_premises(session, parcel)
                )
            else:
                value = str(signals.get(row.signal_key, "not recorded"))
        out.append(
            {
                "department_key": row.department_key,
                "department_label": row.department_label,
                "consumed_fields": list(row.consumed_fields or []),
                "contract_text": row.contract_text,
                "signal_label": row.signal_label,
                "signal_value": value,
            }
        )
    return out


def property_record(
    session: Session, actor: ActorContext, parcel_number: str
) -> dict[str, Any]:
    """Return the property record of one parcel, or ``{}`` when it does not exist."""
    catalog = PropertyCatalog(session)
    parcel = catalog.parcel_by_number(parcel_number)
    if parcel is None:
        return {}
    applications = parcel_applications(session, actor, parcel)
    parcels = map_parcels(session, actor, catalog, subject=parcel.source_parcel_number)
    addresses = parcel_addresses(session, parcel)
    points = []
    for record in catalog.addresses():
        if record.parcel_row_id == parcel.id and record.address.x is not None:
            points.append(
                svg.MapPoint(
                    float(record.address.x),
                    float(record.address.y),
                    f"Official address point: {full_address(record.address)}",
                    "address",
                )
            )
    inset = svg.parcel_inset_svg(
        parcels,
        parcel.source_parcel_number,
        points,
        caption=f"Parcel {parcel.source_parcel_number} and its neighbours",
        linked=True,
        margin=120.0,
    )
    from acme_city.ui.view_models import history, responsibility

    return {
        "parcel": parcel_summary(parcel),
        "parcel_number": parcel.source_parcel_number,
        "parcel_row_id": parcel.id,
        "site_address": catalog.site_address(parcel),
        "addresses": addresses,
        "applications": applications,
        "zoning_district": _zoning(session, parcel.zoning_code),
        "subscribers": subscribers_for(session, parcel),
        "department_notice": DEPARTMENT_NOTICE,
        "inset": inset,
        "map_href": f"/map?parcel={parcel.source_parcel_number}",
        "source": {
            "system": "GIS parcel register (simulated)",
            "version": parcel.version,
            "valid_from": parcel.valid_from.isoformat() if parcel.valid_from else None,
            "status": parcel.status,
            "label": SIMULATED_LABEL,
        },
        "history": history(session, actor, parcel.id),
        "responsibility": responsibility(
            session,
            domain_id="parcels",
            version=parcel.version,
            source_system_id="gis",
            dataset_key="parcel_register",
            subject_ids=(parcel.id,),
        ),
    }


def _zoning(session: Session, code: str | None) -> dict[str, str]:
    if not code:
        return {"code": "unknown", "name": "", "description": ""}
    row = session.execute(
        select(gis.ZoningDistrict).where(gis.ZoningDistrict.code == code)
    ).scalar_one_or_none()
    if row is None:
        return {"code": code, "name": "", "description": ""}
    return {"code": row.code, "name": row.name, "description": row.description}


def town_map(
    session: Session,
    actor: ActorContext,
    *,
    parcel: str = "",
    application: str = "",
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the whole-town map and the parcel table that mirrors it."""
    catalog = PropertyCatalog(session)
    subject = parcel
    candidate_numbers: tuple[str, ...] = ()
    points: list[svg.MapPoint] = []
    only: str | None = None
    note = ""
    if application:
        match = ParcelMatchService(session).for_application(application)
        if match is not None:
            subject = subject or (match.parcel_number or "")
            candidate_numbers = tuple(
                sorted({str(c.get("parcel_number")) for c in match.candidates or [] if c.get("parcel_number")})
            )
            if match.x is not None and match.y is not None:
                points.append(
                    svg.MapPoint(float(match.x), float(match.y), "Point as submitted (located)", "submitted")
                )
            points.extend(
                svg.MapPoint(float(c["x"]), float(c["y"]), f"Candidate: {c['address']}", "candidate")
                for c in match.candidates or []
                if c.get("x") is not None
            )
            note = f"Showing the parcel match of {application}."
    for candidate in candidates or []:
        location = candidate.get("location") or {}
        if location.get("x") is None:
            continue
        points.append(
            svg.MapPoint(
                float(location["x"]),
                float(location["y"]),
                f"Candidate: {candidate.get('address')} (score {candidate.get('score')})",
                "candidate",
            )
        )
        pn = (candidate.get("attributes") or {}).get("PARCELID")
        if pn:
            candidate_numbers += (str(pn),)
    parcels = map_parcels(
        session, actor, catalog, subject=subject, candidates=candidate_numbers, only_application=only
    )
    for record in catalog.addresses():
        if record.address.unit_number:
            continue
        points.append(
            svg.MapPoint(
                float(record.address.x),
                float(record.address.y),
                f"Official address point: {record.address.source_string}",
                "address",
            )
        )
    drawing = svg.town_map_svg(
        parcels,
        _street_rows(catalog),
        points,
        caption=(
            "Map of the fictional town of ACME City: parcels, streets, address points "
            "and permit markers (simulated data)"
        ),
        focus=subject,
    )
    table = [
        {
            "number": item.number,
            "site_address": item.site_address,
            "zoning": item.zoning,
            "href": item.href,
            "applications": item.applications,
            "role": item.role,
        }
        for item in parcels
    ]
    return {
        "svg": drawing,
        "legend": svg.legend_html(),
        "parcels": table,
        "subject": subject,
        "note": note,
        "simulated_label": SIMULATED_LABEL,
    }


__all__ = [
    "DEPARTMENT_NOTICE",
    "application_property",
    "parcel_summary",
    "property_record",
    "steward_parcel_proposals",
    "subscribers_for",
    "town_map",
]

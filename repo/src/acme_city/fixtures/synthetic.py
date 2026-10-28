"""Load the seeded synthetic permit history, and backfill business categories.

The default reset never calls :func:`load_synthetic_year`.  The demo-synthetic
prepare mode does, after a reset to the fixtures.  Every row written here
carries ``synthetic = true``; the applications also carry the population id.
The loader writes historical records only: it never runs an agent or a
decision service and it writes **no audit events**, so no row claims that a
person or an agent acted.  The decision and the issuance carry the actor id
``synthetic_history``, which is neither a persona nor an agent.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from acme_city.persistence.models import permit, registry
from acme_city.portal_intake.scenarios import (
    SYNTHETIC_ACTOR_ID,
    SYNTHETIC_SCENARIO_ID,
    SyntheticCase,
    generate_synthetic_year,
    load_distributions,
)

#: The categories of a business licence.
BUSINESS_CATEGORIES: tuple[str, ...] = ("restaurant", "bar", "retail", "office", "other")

#: The words that place a business in a category, tried in this order.  The
#: same table ran in migration 0008 for the businesses that already existed.
CATEGORY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bar", ("tavern", "pub", "brewery", "taproom", "lounge", " bar")),
    (
        "restaurant",
        ("coffee", "cafe", "bakery", "grill", "kitchen", "diner", "bistro", "restaurant"),
    ),
    ("retail", ("imports", "market", "shop", "goods", "store", "boutique")),
    ("office", ("property", "realty", "consulting", "partners", "office", "law")),
)


def category_for_name(name: str) -> str:
    """Return the category the words of a business name suggest."""
    lowered = f" {name.lower()}"
    for category, words in CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return category
    return "other"


def backfill_business_categories(session: Session) -> dict[str, int]:
    """Give every business licence without a category one, and report it.

    Only a ``business_license`` credential whose category is blank is
    touched.  Returns the number of licences set, per category, plus the
    ``total``.  A contractor registration keeps a blank category.
    """
    rows = session.execute(
        select(registry.Credential, registry.Party)
        .join(registry.Party, registry.Party.id == registry.Credential.holder_party_id)
        .where(
            registry.Credential.credential_type == "business_license",
            registry.Credential.business_category.is_(None),
        )
        .order_by(registry.Credential.credential_id)
    ).all()
    report: dict[str, int] = {}
    for credential, party in rows:
        category = category_for_name(party.display_name)
        credential.business_category = category
        report[category] = report.get(category, 0) + 1
    session.flush()
    report["total"] = len(rows)
    return report


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def synthetic_application_count(session: Session) -> int:
    """Return how many synthetic applications the database holds."""
    return int(
        session.execute(
            select(func.count()).select_from(permit.Application).where(permit.Application.synthetic.is_(True))
        ).scalar_one()
    )


def remove_synthetic(session: Session) -> dict[str, int]:
    """Delete every synthetic row, children first; return the counts."""
    removed: dict[str, int] = {}
    synthetic_apps = select(permit.Application.id).where(permit.Application.synthetic.is_(True))
    removed["permits"] = session.execute(
        delete(permit.Permit).where(permit.Permit.synthetic.is_(True))
    ).rowcount
    removed["decisions"] = session.execute(
        delete(permit.Decision).where(permit.Decision.synthetic.is_(True))
    ).rowcount
    for model, name in (
        (permit.ApplicationRevision, "application_revisions"),
        (permit.ApplicationSite, "application_sites"),
        (permit.ApplicationParty, "application_parties"),
    ):
        removed[name] = session.execute(
            delete(model).where(model.synthetic.is_(True))
        ).rowcount
    removed["applications"] = session.execute(
        delete(permit.Application).where(permit.Application.id.in_(synthetic_apps))
    ).rowcount
    removed["credentials"] = session.execute(
        delete(registry.Credential).where(registry.Credential.synthetic.is_(True))
    ).rowcount
    removed["parties"] = session.execute(
        delete(registry.Party).where(registry.Party.synthetic.is_(True))
    ).rowcount
    removed["canonical_entities"] = session.execute(
        delete(registry.CanonicalEntity).where(registry.CanonicalEntity.synthetic.is_(True))
    ).rowcount
    session.flush()
    return removed


def _party(
    session: Session,
    cache: dict[str, str],
    *,
    key: str,
    name: str,
    party_type: str,
) -> str:
    if key in cache:
        return cache[key]
    session.add(
        registry.CanonicalEntity(
            id=f"entity_{key}",
            entity_id=key,
            entity_type="party",
            label=name,
            status="active",
            synthetic=True,
        )
    )
    session.flush()
    session.add(
        registry.Party(
            id=key,
            entity_id=key,
            party_type=party_type,
            display_name=name,
            legal_name=name,
            status="active",
            synthetic=True,
        )
    )
    session.flush()
    cache[key] = key
    return key


def load_synthetic_year(
    session: Session, *, seed: int, count: int, root: Path | None = None
) -> dict[str, Any]:
    """Generate the synthetic year and write it as flagged historical rows.

    Refuses when synthetic rows already exist (run the default reset to start
    again).  Returns the counts written and the generator's identity.
    """
    if synthetic_application_count(session):
        raise RuntimeError(
            "synthetic rows already exist; reset to the fixtures before loading another population"
        )
    year = generate_synthetic_year(seed=seed, count=count, root=root)
    config = load_distributions(root)

    type_ids = {
        row.key: row for row in session.execute(select(permit.PermitType)).scalars().all()
    }
    parcel_rows = {
        row.source_parcel_number: row for row in session.execute(select(registry.Parcel)).scalars().all()
    }
    from acme_city.portal_intake.scenarios import _town_parcels

    address_by_parcel: dict[str, str] = {}
    for parcels in _town_parcels(root).values():
        for entry in parcels:
            address_by_parcel[entry["parcel_number"]] = entry["address_id"]
    known_addresses = {
        row.address_id for row in session.execute(select(registry.Address)).scalars().all()
    }

    parties: dict[str, str] = {}
    credentials_added: set[str] = set()
    written = {
        "applications": 0, "decisions": 0, "permits": 0, "parties": 0, "credentials": 0,
        "application_parties": 0, "application_sites": 0, "application_revisions": 0,
    }

    def add_credential(party_id: str, kind: str, number: str, category: str | None, when: datetime) -> None:
        if party_id in credentials_added:
            return
        credentials_added.add(party_id)
        session.add(
            registry.Credential(
                id=f"cred_{party_id}",
                credential_id=f"cred_{party_id}",
                holder_party_id=party_id,
                credential_type=kind,
                issuing_authority_id=(
                    "erp_finance:business_licensing_register"
                    if kind == "business_license"
                    else "permitting:contractor_register"
                ),
                number=number,
                status="active",
                valid_from=year.window_start,
                valid_to=None,
                verified_at=when,
                source_system_id=None,
                source_record_id=None,
                source_snapshot_id=None,
                scenario_id=None,
                business_category=category if kind == "business_license" else None,
                synthetic=True,
            )
        )
        written["credentials"] += 1

    def link(application_id: str, party_id: str, role: str, primary: bool, suffix: str) -> None:
        session.add(
            permit.ApplicationParty(
                id=f"appparty_{application_id}_{suffix}",
                application_id=application_id,
                party_id=party_id,
                party_role=role,
                is_primary=primary,
                authority_evidence_ref=None,
                synthetic=True,
            )
        )
        written["application_parties"] += 1

    for case in year.cases:
        _write_case(
            session, case, year, config, type_ids, parcel_rows, address_by_parcel,
            known_addresses, parties, add_credential, link, written,
        )
    session.flush()
    written["parties"] = len(parties)
    return {
        "population_id": year.population_id,
        "distribution_version": year.distribution_version,
        "seed": year.seed,
        "count": year.count,
        "written": written,
    }


def _write_case(
    session, case: SyntheticCase, year, config, type_ids, parcel_rows, address_by_parcel,
    known_addresses, parties, add_credential, link, written,
) -> None:
    serial = case.number.split("-")[-1]
    application_id = f"app_syn_{serial}"
    permit_type = type_ids[case.permit_type_key]
    parcel = parcel_rows.get(case.parcel_number)

    if case.business_name:
        business_id = _party(
            session, parties, key=f"party_syn_biz_{_slug(case.business_name)}",
            name=case.business_name, party_type="organization",
        )
        add_credential(
            business_id, "business_license", f"SYN-BL-{_slug(case.business_name)[:24]}",
            case.business_category, year.window_start,
        )
        applicant_id = business_id
    else:
        applicant_id = _party(
            session, parties, key=f"party_syn_person_{_slug(case.applicant_name)}",
            name=case.applicant_name, party_type="person",
        )
    contractor_id = None
    if case.contractor_name:
        contractor_id = _party(
            session, parties, key=f"party_syn_ctr_{_slug(case.contractor_name)}",
            name=case.contractor_name, party_type="organization",
        )
        add_credential(
            contractor_id, "contractor_registration", f"SYN-CR-{_slug(case.contractor_name)[:24]}",
            None, year.window_start,
        )
    session.flush()

    facts = dict(case.facts)
    facts.update({"channel": case.channel, "synthetic": True})
    application = permit.Application(
        id=application_id,
        source_application_number=case.number,
        permit_type_id=permit_type.permit_type_id,
        initial_submitted_at=case.arrived_at,
        revision_submitted_at=case.arrived_at,
        status=case.status,
        revision=1,
        description=case.description,
        submitted_facts=facts,
        applicant_party_id=applicant_id,
        correlation_id=f"corr_synthetic_{year.seed}",
        scenario_id=SYNTHETIC_SCENARIO_ID,
        review_area=permit_type.review_area,
        priority=case.priority,
        synthetic=True,
        synthetic_population=year.population_id,
    )
    if case.status == "archived":
        application.status_before_archive = "submitted"
        application.archived_at = case.arrived_at
        application.archived_by_actor_id = SYNTHETIC_ACTOR_ID
        application.archive_reason = "Synthetic history: archived record."
    session.add(application)
    session.flush()
    written["applications"] += 1

    link(application_id, applicant_id, "applicant", True, "applicant")
    if case.business_name:
        link(application_id, applicant_id, "business", False, "business")
    if contractor_id:
        link(application_id, contractor_id, "contractor", False, "contractor")

    address_id = address_by_parcel.get(case.parcel_number) or None
    session.add(
        permit.ApplicationSite(
            id=f"site_{application_id}",
            application_id=application_id,
            parcel_id=parcel.id if parcel is not None else None,
            address_id=address_id if address_id in known_addresses else None,
            is_primary=True,
            resolution_status="resolved",
            submitted_address_text=case.site_address,
            synthetic=True,
        )
    )
    written["application_sites"] += 1
    session.add(
        permit.ApplicationRevision(
            id=f"rev_{application_id}_1",
            application_id=application_id,
            revision_number=1,
            submitted_at=case.arrived_at,
            submitted_by_actor_id=SYNTHETIC_ACTOR_ID,
            snapshot=dict(facts),
            date_basis="synthetic_history",
            synthetic=True,
        )
    )
    written["application_revisions"] += 1

    if case.decided_at is not None and case.outcome is not None:
        decision_id = f"dec_syn_{serial}"
        reason = f"Synthetic history: {case.outcome} on the published rules."
        session.add(
            permit.Decision(
                id=decision_id,
                application_id=application_id,
                decision_type="review",
                outcome=case.outcome,
                decided_by_actor_id=SYNTHETIC_ACTOR_ID,
                decided_at=case.decided_at,
                reason=reason,
                input_versions={"synthetic": True},
                rule_versions={},
                status="current",
                stale=False,
                scenario_id=SYNTHETIC_SCENARIO_ID,
                conditions=list(case.conditions) or None,
                reason_code=case.denial_reason_code,
                waivers=list(case.waivers) or None,
                synthetic=True,
            )
        )
        written["decisions"] += 1
        session.flush()
        if case.issued_at is not None and case.permit_number:
            session.add(
                permit.Permit(
                    id=f"permit_syn_{serial}",
                    application_id=application_id,
                    decision_id=decision_id,
                    permit_number=case.permit_number,
                    issued_at=case.issued_at,
                    expires_at=None,
                    status="issued",
                    snapshot={
                        "permit_number": case.permit_number,
                        "application_number": case.number,
                        "issued_at": case.issued_at.isoformat(),
                        "decision_outcome": case.outcome,
                        "synthetic": True,
                    },
                    artifact_hash=hashlib.sha256(case.permit_number.encode()).hexdigest(),
                    issuance_command_key=f"issue:synthetic:{case.number}",
                    issued_by_actor_id=SYNTHETIC_ACTOR_ID,
                    fictional_demo=True,
                    synthetic=True,
                )
            )
            written["permits"] += 1


__all__ = [
    "BUSINESS_CATEGORIES",
    "backfill_business_categories",
    "category_for_name",
    "load_synthetic_year",
    "remove_synthetic",
    "synthetic_application_count",
]

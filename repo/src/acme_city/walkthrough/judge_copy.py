"""A fresh copy of the café case for one judge.

The hosted demonstration is shared, so every judge needs a case of their own
to walk.  This module builds that copy:

* the three owner records of the café, each one a new source record with a
  candidate link that waits for the Data Steward;
* the case of the café itself, with the facts, the site and the fee of the
  seeded case and with fresh identifiers;
* the receipt of the fee, paid from the old finance account of the copy and
  not yet matched to anybody.

The copy is fictional.  It is capped like the sample data of the
demonstration, it changes nothing that is already there, it decides nothing,
and it writes one audit event that says what it did.  The steward assistant
may then prepare a recommendation for each of the three records, and the
judge decides every one of them.
"""
# REQUIRES: MDM-02, PER-01, FIN-01, UX-04
# The copy is plain fictional data with a cap, a nonce and an audit event.

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import payload_hash
from acme_city.persistence.models import finance, permit, registry, source
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

#: The prefix of the readable reference of every copy.
JUDGE_REFERENCE_PREFIX = "CAFE-2026-"

#: The prefix of the internal identifier of every copy.
JUDGE_APPLICATION_PREFIX = "app_judge_"

#: The prefix of the internal identifier of the receipt of every copy.
JUDGE_PAYMENT_PREFIX = "payment_judge_"

#: The prefix of the internal identifier of the finance account of every copy.
JUDGE_ACCOUNT_PREFIX = "facct_judge_"

#: The most copies the demonstration may hold at the same time.  The sample
#: data of the demonstration is capped the same way.
MAX_JUDGE_COPIES = 20

#: Said when Start fresh cannot make another copy.  There is no nightly reset.
COPIES_IN_USE = "Every copy is in use. Continue with the café case already open."

#: The canonical identity of the café.  The copy is the café's own case, so it
#: names the same owner.
CAFE_PARTY_ID = "party_cedarline"

#: The permit type of the café's case.
CAFE_PERMIT_TYPE_KEY = "com_ti"

#: The case the copy is made of.
CAFE_APPLICATION_ID = "app_synth_001"

#: The actor that proposes the candidate links of the copy.  The proposals
#: are evidence waiting for the Data Steward, exactly as the proposals of the
#: seeded demonstration are.
PROPOSER = ActorContext(
    actor_id="persona_data_steward",
    role_ids=frozenset({"domain_steward"}),
)

#: The amount of the fee of the café's case, in cents.
CAFE_FEE_CENTS = 15000

#: The documents the type of the café's case asks for.  The copy carries
#: every one of them, so the intake agent finds the case complete and routes
#: it to the reviewer instead of holding it for early resolution.
CAFE_DOCUMENTS: tuple[str, ...] = (
    "construction_plans",
    "floor_plan",
    "site_plan",
    "fire_suppression_plan",
    "business_license_copy",
)


@dataclass(frozen=True)
class JudgeCopy:
    """The copy of the café case that one judge walks."""

    nonce: str
    application_id: str
    reference: str
    payment_id: str
    account_id: str
    account_source_id: str
    records: tuple[str, ...]


def new_nonce() -> str:
    """Return the server nonce that names one copy.

    The nonce is the seed of every identifier of the copy, so two judges never
    share a case, a receipt or a source record.
    """
    return secrets.token_hex(3).upper()


def judge_copy_count(session: Session) -> int:
    """Return how many copies the demonstration holds."""
    return int(
        session.execute(
            select(func.count())
            .select_from(permit.Application)
            .where(permit.Application.id.like(f"{JUDGE_APPLICATION_PREFIX}%"))
        ).scalar_one()
    )


def room_for_copies(session: Session) -> int:
    """Return how many more copies the demonstration may hold."""
    return max(MAX_JUDGE_COPIES - judge_copy_count(session), 0)


def _snapshot(
    session: Session,
    *,
    source_system_id: str,
    dataset_key: str,
    record_id: str,
    payload: dict[str, Any],
    now: datetime,
    version: str = "1",
) -> source.SourceSnapshot:
    """Write one source record of the copy and return it."""
    row = source.SourceSnapshot(
        source_snapshot_id=new_id("snap"),
        correlation_id=new_id("corr"),
        ingestion_run_id=None,
        source_system_id=source_system_id,
        source_dataset_id=dataset_key,
        source_record_id=record_id,
        source_record_version=version,
        source_updated_at=now,
        effective_from=now,
        effective_to=None,
        ingested_at=now,
        payload_hash=payload_hash(payload),
        raw_payload=payload,
        record_status="accepted",
        scenario_id=None,
    )
    session.add(row)
    session.flush()
    return row


def _finance_account(
    session: Session, *, account_id: str, source_account_id: str, now: datetime
) -> registry.FinanceAccount:
    """Write the old finance account of the copy and return it."""
    row = registry.FinanceAccount(
        id=account_id,
        account_id=account_id,
        source_account_id=source_account_id,
        source_system_id="erp_finance",
        party_id=None,
        account_role="payer",
        source_version="1",
        link_status="unlinked",
        link_decision=None,
        scenario_id=None,
    )
    session.add(row)
    session.flush()
    return row


def _payment(
    session: Session,
    *,
    payment_id: str,
    account: registry.FinanceAccount,
    source_transaction_id: str,
    now: datetime,
) -> finance.Payment:
    """Write the receipt of the fee of the copy and return it."""
    row = finance.Payment(
        id=payment_id,
        source_transaction_id=source_transaction_id,
        source_system_id="erp_finance",
        source_event_id=f"{source_transaction_id}-EVT-1",
        source_event_version="1",
        payer_account_id=account.id,
        party_id=None,
        paid_at=now,
        amount_cents=CAFE_FEE_CENTS,
        currency="USD",
        settlement_status="settled",
        scenario_id=None,
    )
    session.add(row)
    session.flush()
    return row


def create_judge_copy(session: Session, *, nonce: str | None = None, actor: Any = None) -> JudgeCopy:
    """Create the copy of the café case for one judge.

    The copy holds three source records of the owner, each one with a
    candidate link that waits for the Data Steward, the case itself and the
    receipt of the fee that was paid from the old finance account.

    Args:
        session: The open session.  The copy is written inside the caller's
            transaction, so a failure leaves the demonstration untouched.
        nonce: The server nonce that names the copy.  A new one is drawn
            when it is not given.
        actor: The actor the audit event names.

    Returns:
        The copy that was created.

    Raises:
        ValidationError: When every copy is already in use.
    """
    room = room_for_copies(session)
    if room == 0:
        raise ValidationError(COPIES_IN_USE)
    token = (nonce or new_nonce()).upper()
    now = utc_now()

    seeded = session.get(permit.Application, CAFE_APPLICATION_ID)
    if seeded is None:
        raise ValidationError("the café case of the demonstration is missing")
    permit_type = session.execute(
        select(permit.PermitType).where(permit.PermitType.key == CAFE_PERMIT_TYPE_KEY)
    ).scalar_one_or_none()
    if permit_type is None:
        raise ValidationError("the permit type of the café case is missing")
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == CAFE_APPLICATION_ID
        )
    ).scalar_one_or_none()

    account_source_id = f"ERP-ACC-J{token}-LEG"
    account_id = f"{JUDGE_ACCOUNT_PREFIX}{token.lower()}"
    payment_id = f"{JUDGE_PAYMENT_PREFIX}{token.lower()}"
    application_id = f"{JUDGE_APPLICATION_PREFIX}{token.lower()}"
    reference = f"{JUDGE_REFERENCE_PREFIX}{token}"

    # ---------------------------------------------------- the owner records
    permit_record_id = f"PER-JUDGE-{token}"
    licence_record_id = f"ERP-JUDGE-BL-{token}"
    account_record_id = account_source_id
    owner_payloads = (
        (
            "permitting",
            "applicant_profiles",
            permit_record_id,
            {
                "party_ref": CAFE_PARTY_ID,
                "organization_name": "Cedar Line Coffee Roasters",
                "contact_email": "hello@cedarline.example.invalid",
                "contact_phone": "+1-555-0170",
                "preferred_contact": "email",
            },
        ),
        (
            "erp_finance",
            "business_licensing_register",
            licence_record_id,
            {
                "holder_ref": CAFE_PARTY_ID,
                "license_number": "BL-2026-00412",
                "holder_name": "Cedar Line Coffee Roasters",
                "status": "active",
                "valid_from": "2026-01-15",
                "valid_to": "2026-12-31",
                "business_address": "400 Lantern Row Unit 2",
            },
        ),
        (
            "erp_finance",
            "finance_accounts",
            account_record_id,
            {
                "source_account_id": account_source_id,
                "account_role": "payer",
                "currency": "USD",
                "legacy_account_ref": "ERP-ACC-88231",
                "holder_ref": CAFE_PARTY_ID,
                "holder_name": "Cedar Line Coffee Roasters",
                "business_address": "400 Lantern Row Unit 2",
                "opened_at": "2018-05-02",
            },
        ),
    )
    record_ids: list[str] = []
    for system_id, dataset_key, record_id, payload in owner_payloads:
        _snapshot(
            session,
            source_system_id=system_id,
            dataset_key=dataset_key,
            record_id=record_id,
            payload=payload,
            now=now,
        )
        record_ids.append(record_id)

    # ---------------------------------------------------- the old account
    account = _finance_account(
        session, account_id=account_id, source_account_id=account_source_id, now=now
    )
    _payment(
        session,
        payment_id=payment_id,
        account=account,
        source_transaction_id=f"ERP-TXN-J{token}",
        now=now,
    )

    # ---------------------------------------------------- the case
    facts = dict(seeded.submitted_facts or {})
    facts["organization_name"] = "Cedar Line Coffee Roasters"
    facts["parcel_number"] = str(facts.get("submitted_parcel") or "ACME-P-1001")
    application = permit.Application(
        id=application_id,
        source_application_number=reference,
        permit_type_id=permit_type.id,
        initial_submitted_at=now,
        revision_submitted_at=now,
        status="submitted",
        revision=1,
        description=str(facts.get("project_description") or "") or None,
        submitted_facts=facts,
        applicant_party_id=CAFE_PARTY_ID,
        correlation_id=new_id("corr"),
        scenario_id=None,
    )
    session.add(application)
    session.flush()
    session.add(
        permit.ApplicationRevision(
            id=new_id("rev"),
            application_id=application.id,
            revision_number=1,
            submitted_at=now,
            submitted_by_actor_id=None,
            snapshot=facts,
            date_basis="submitted",
        )
    )
    for role, evidence in (
        ("applicant", None),
        ("payer", f"erp_finance:{account_source_id}"),
        ("permit_holder", None),
    ):
        session.add(
            permit.ApplicationParty(
                id=new_id("appparty"),
                application_id=application.id,
                party_id=CAFE_PARTY_ID,
                party_role=role,
                is_primary=role == "applicant",
                authority_evidence_ref=evidence,
            )
        )
    if site is not None:
        session.add(
            permit.ApplicationSite(
                id=new_id("appsite"),
                application_id=application.id,
                parcel_id=site.parcel_id,
                address_id=site.address_id,
                is_primary=True,
                resolution_status=site.resolution_status,
                submitted_address_text=site.submitted_address_text,
            )
        )
    for document_type in CAFE_DOCUMENTS:
        session.add(
            permit.Document(
                id=new_id("doc"),
                application_id=application.id,
                document_type=document_type,
                version=1,
                file_ref=f"{application.id}:{document_type}",
                content_hash=payload_hash({"document_type": document_type, "copy": token}),
                received_at=now,
                uploaded_by_actor_id=None,
                fictional_demo=True,
                quality=[],
            )
        )
    session.flush()

    # ---------------------------------------------------- the proposals
    registry_service = RegistryService(session)
    for system_id, dataset_key, record_id, _payload in owner_payloads:
        registry_service.propose(
            MatchProposalCommand(
                source_system_id=system_id,
                dataset_key=dataset_key,
                source_record_id=record_id,
            ),
            PROPOSER,
        )

    AuditService(session).append(
        action="walkthrough.start_fresh",
        actor=actor if actor is not None else "service_walkthrough",
        target_type="application",
        target_id=application.id,
        after_version=application.version,
        reason="a judge asked for a copy of the café case",
        references=[reference, account_source_id, payment_id],
        metadata={
            "nonce": token,
            "records": list(record_ids),
            "payment_id": payment_id,
            "account_source_id": account_source_id,
        },
    )
    session.flush()
    return JudgeCopy(
        nonce=token,
        application_id=application.id,
        reference=reference,
        payment_id=payment_id,
        account_id=account.id,
        account_source_id=account_source_id,
        records=tuple(record_ids),
    )


__all__ = [
    "CAFE_APPLICATION_ID",
    "CAFE_FEE_CENTS",
    "CAFE_PARTY_ID",
    "CAFE_PERMIT_TYPE_KEY",
    "JUDGE_ACCOUNT_PREFIX",
    "JUDGE_APPLICATION_PREFIX",
    "JUDGE_PAYMENT_PREFIX",
    "JUDGE_REFERENCE_PREFIX",
    "COPIES_IN_USE",
    "MAX_JUDGE_COPIES",
    "JudgeCopy",
    "create_judge_copy",
    "judge_copy_count",
    "new_nonce",
    "room_for_copies",
]

"""The judge's copy of the café case.

The copy is what the Start fresh button makes: three owner records of the
café with their candidate links waiting for the Data Steward, the case of the
café and the receipt of the fee that was paid from the old finance account.

The copy is fictional, it is capped, it decides nothing, and it writes one
audit event.
"""
# REQUIRES: MDM-02, PER-01, FIN-01, UX-04
# The copy holds the rows the café path needs and nothing else.

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings  # noqa: E402

from acme_city.core.errors import ValidationError  # noqa: E402
from acme_city.persistence.models import audit, finance, permit, registry, source  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.walkthrough import judge_copy  # noqa: E402


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    """A fresh demonstration database for one test."""
    settings = build_settings(tmp_path)
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as open_session:
            yield open_session
    finally:
        factory.dispose()


def test_the_copy_holds_the_three_owner_records_the_case_and_the_receipt(
    session: Session,
) -> None:
    """A copy of the café case holds everything the café path needs."""
    copy = judge_copy.create_judge_copy(session, nonce="TEST01")

    assert copy.reference == "CAFE-2026-TEST01"
    assert copy.application_id == "app_judge_test01"
    assert len(copy.records) == 3

    application = session.get(permit.Application, copy.application_id)
    assert application is not None
    assert application.source_application_number == copy.reference
    assert application.permit_type_id == "permit_type_com_ti"
    assert application.status == "submitted"
    assert application.applicant_party_id == judge_copy.CAFE_PARTY_ID

    account = session.get(registry.FinanceAccount, copy.account_id)
    assert account is not None
    assert account.party_id is None
    assert account.link_status == "unlinked"

    payment = session.get(finance.Payment, copy.payment_id)
    assert payment is not None
    assert payment.payer_account_id == copy.account_id
    assert payment.party_id is None
    assert payment.amount_cents == judge_copy.CAFE_FEE_CENTS
    assert payment.settlement_status == "settled"


def test_the_copy_never_changes_the_seeded_case(session: Session) -> None:
    """The copy adds rows; it changes nothing that is already there."""
    seeded = session.get(permit.Application, judge_copy.CAFE_APPLICATION_ID)
    before = (seeded.status, seeded.source_application_number, seeded.version)

    judge_copy.create_judge_copy(session, nonce="TEST02")

    seeded = session.get(permit.Application, judge_copy.CAFE_APPLICATION_ID)
    assert (seeded.status, seeded.source_application_number, seeded.version) == before
    assert session.get(registry.FinanceAccount, "facct_cedarline_legacy") is not None
    assert session.get(finance.Payment, "payment_d01_settled") is not None


def test_the_copy_proposes_the_three_owner_records(session: Session) -> None:
    """Each owner record of the copy waits for the Data Steward."""
    copy = judge_copy.create_judge_copy(session, nonce="TEST03")

    snapshots = session.execute(
        select(source.SourceSnapshot).where(
            source.SourceSnapshot.source_record_id.in_(copy.records)
        )
    ).scalars().all()
    assert len(snapshots) == 3

    proposals = session.execute(
        select(registry.MatchProposal).where(
            registry.MatchProposal.source_snapshot_id.in_(
                [row.source_snapshot_id for row in snapshots]
            )
        )
    ).scalars().all()
    assert len(proposals) == 3
    for proposal in proposals:
        assert proposal.entity_id == judge_copy.CAFE_PARTY_ID
        assert proposal.disposition == "supported"

    links = session.execute(
        select(registry.Crosswalk).where(
            registry.Crosswalk.source_record_id.in_(copy.records)
        )
    ).scalars().all()
    assert len(links) == 3
    assert all(link.link_status == "proposed" for link in links)


def test_the_copy_writes_one_audit_event(session: Session) -> None:
    """The copy says what it did in the audit trail."""
    copy = judge_copy.create_judge_copy(session, nonce="TEST04", actor="persona_city_administrator")

    events = session.execute(
        select(audit.AuditEvent).where(
            audit.AuditEvent.action == "walkthrough.start_fresh"
        )
    ).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "persona_city_administrator"
    assert event.target_id == copy.application_id
    assert copy.reference in (event.references or [])


def test_the_copy_is_capped(session: Session) -> None:
    """The demonstration holds a bounded number of copies."""
    for index in range(judge_copy.MAX_JUDGE_COPIES):
        judge_copy.create_judge_copy(session, nonce=f"CAP{index:04d}")
    assert judge_copy.judge_copy_count(session) == judge_copy.MAX_JUDGE_COPIES
    assert judge_copy.room_for_copies(session) == 0

    with pytest.raises(ValidationError) as refused:
        judge_copy.create_judge_copy(session, nonce="CAP9999")
    assert "allowance" in str(refused.value)


def test_two_copies_never_share_an_identifier(session: Session) -> None:
    """The nonce of the server names every row of a copy."""
    first = judge_copy.create_judge_copy(session, nonce="ONE001")
    second = judge_copy.create_judge_copy(session, nonce="TWO002")
    assert first.application_id != second.application_id
    assert first.payment_id != second.payment_id
    assert first.account_id != second.account_id
    assert not set(first.records) & set(second.records)


def test_the_nonce_is_drawn_by_the_server(session: Session) -> None:
    """A copy without a nonce still gets one of its own."""
    first = judge_copy.create_judge_copy(session)
    second = judge_copy.create_judge_copy(session)
    assert first.nonce != second.nonce
    assert len(first.nonce) >= 4

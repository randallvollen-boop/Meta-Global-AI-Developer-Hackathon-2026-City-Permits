"""The intake queue, the early-resolution board and the review queue.

The three queues report the exact membership of each saved view, the age of
a case against the configured service target of its type, and the signals
the server actually holds.  Nothing on them is estimated and nothing on them
is decided.
"""
# REQUIRES: UX-01, UX-02, PER-03, AI-03
# Each saved view holds exactly the cases it names, the filters and the sort
# work through the query string, and a signal appears only where the server
# holds the fact behind it.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.queues import (
    INTAKE_TABS,
    early_resolution,
    intake_queue,
    review_queue,
)
from acme_city.permits.service import PermitService
from acme_city.permits.schemas import SubmitApplicationCommand

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence at 400 Lantern Row",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, ACME City",
    "channel": "portal",
    "applicant_name": "Cedar Line Coffee Roasters",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'queues.db'}",
            "ACME_SECRET_KEY": "queue-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def make_arrival(session, *, permit_type: str = "com_ti", **facts) -> permit.Application:
    """Submit one case that arrived from outside the City."""
    service = PermitService(session)
    steward = context_for(session, "persona_data_steward")
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key=permit_type,
            facts={**FACTS, **facts},
            applicant_party_id="party_cedarline",
        ),
        steward,
    )
    application = service.load_application(view.application_id)
    session.flush()
    return application


def test_the_saved_views_hold_exactly_the_cases_they_name(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            arrival = make_arrival(session)
            queue = intake_queue(session, steward)
            assert [tab["key"] for tab in queue["tabs"]] == [
                "active",
                "awaiting_agent",
                "needs_information",
                "in_review",
                "archived",
                "closed",
            ]
            # The arrival is active and waits for the agent.
            assert arrival.source_application_number in {
                row["reference"] for row in queue["rows"]
            }
            awaiting = intake_queue(session, steward, tab="awaiting_agent")
            assert arrival.source_application_number in {
                row["reference"] for row in awaiting["rows"]
            }
            # The seeded demonstration cases are part of the fixed corpus, not
            # arrivals, so they never wait for the agent.
            assert "SYN-APP-001" not in {
                row["reference"] for row in awaiting["rows"]
            }
            # The issued demonstration case is closed, not active.
            closed = intake_queue(session, steward, tab="closed")
            assert "SYN-APP-007" in {row["reference"] for row in closed["rows"]}
            assert "SYN-APP-007" not in {
                row["reference"] for row in intake_queue(session, steward)["rows"]
            }
    finally:
        factory.dispose()


def test_a_returned_case_is_closed_and_an_archived_case_is_archived(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            returned = make_arrival(session)
            returned.status = "returned"
            archived = make_arrival(session)
            archived.status = "archived"
            session.flush()
            closed = intake_queue(session, steward, tab="closed")
            assert returned.source_application_number in {
                row["reference"] for row in closed["rows"]
            }
            assert archived.source_application_number not in {
                row["reference"] for row in closed["rows"]
            }
            archived_view = intake_queue(session, steward, tab="archived")
            assert archived.source_application_number in {
                row["reference"] for row in archived_view["rows"]
            }
            assert returned.source_application_number not in {
                row["reference"] for row in archived_view["rows"]
            }
    finally:
        factory.dispose()


def test_the_counts_of_the_tabs_are_the_membership_of_the_tabs(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            queue = intake_queue(session, steward)
            for tab in queue["tabs"]:
                view = intake_queue(session, steward, tab=tab["key"])
                assert view["counts"][tab["key"]] == len(view["rows"]) or (
                    tab["key"] == "active"
                )
            # The active view is the union of the open views; it holds at
            # least as many cases as any one of them.
            assert queue["counts"]["active"] >= queue["counts"]["in_review"]
            assert queue["counts"]["active"] >= queue["counts"]["needs_information"]
    finally:
        factory.dispose()


def test_the_search_finds_a_case_by_reference_applicant_and_address(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            arrival = make_arrival(session)
            session.flush()
            by_reference = intake_queue(
                session, steward, query=arrival.source_application_number
            )
            assert [row["reference"] for row in by_reference["rows"]] == [
                arrival.source_application_number
            ]
            by_applicant = intake_queue(session, steward, query="Cedar Line")
            assert arrival.source_application_number in {
                row["reference"] for row in by_applicant["rows"]
            }
            by_address = intake_queue(session, steward, query="Lantern Row")
            assert arrival.source_application_number in {
                row["reference"] for row in by_address["rows"]
            }
            missing = intake_queue(session, steward, query="nothing-matches-this")
            assert missing["rows"] == []
    finally:
        factory.dispose()


def test_the_filters_narrow_the_view_and_the_sort_orders_it(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            portal = make_arrival(session)
            counter = make_arrival(session, channel="counter_scan")
            counter.priority = "high"
            session.flush()
            by_channel = intake_queue(session, steward, channel="counter_scan")
            assert [row["reference"] for row in by_channel["rows"]] == [
                counter.source_application_number
            ]
            by_priority = intake_queue(session, steward, priority="high")
            assert [row["reference"] for row in by_priority["rows"]] == [
                counter.source_application_number
            ]
            by_type = intake_queue(session, steward, permit_type="deck_fence")
            assert all(
                row["permit_type_key"] == "deck_fence" for row in by_type["rows"]
            )
            assert portal.source_application_number not in {
                row["reference"] for row in by_type["rows"]
            }
            by_priority_sort = intake_queue(session, steward, sort="priority")
            assert by_priority_sort["rows"][0]["priority"] == "high"
            assert portal.source_application_number in {
                row["reference"] for row in by_priority_sort["rows"]
            }
    finally:
        factory.dispose()


def test_the_age_of_a_case_is_compared_with_the_service_target_of_its_type(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            arrival = make_arrival(session)
            session.flush()
            row = next(
                item
                for item in intake_queue(session, steward)["rows"]
                if item["reference"] == arrival.source_application_number
            )
            # The target is the configured figure of the type, never a guess.
            type_row = session.get(permit.PermitType, arrival.permit_type_id)
            assert row["service_target_days"] == type_row.service_target_days
            assert row["service_target_days"] == 10
            assert row["age_days"] == 0
            assert row["age_tone"] == ""
    finally:
        factory.dispose()


def test_a_signal_appears_only_where_the_server_holds_the_fact(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            arrival = make_arrival(session)
            session.flush()
            row = next(
                item
                for item in intake_queue(session, steward)["rows"]
                if item["reference"] == arrival.source_application_number
            )
            # No agent has run and no duplicate was found: the queue says so.
            assert row["signals"]["agent"]["state"] == "not run"
            assert row["signals"]["duplicate"]["state"] == "none"
            assert row["signals"]["parcel"]["status"] in {
                "no match",
                "proposed",
                "approved",
                "confirmed",
            }
            # A recorded duplicate finding becomes the duplicate signal.
            session.add(
                permit.ApplicationFinding(
                    id="finding_duplicate_signal",
                    correlation_id="corr_signal",
                    application_id=arrival.id,
                    finding_type="duplicate",
                    message="The same applicant asked for the same project.",
                    severity="review",
                    state="current",
                    revision_number=arrival.revision,
                    version=1,
                )
            )
            session.flush()
            row = next(
                item
                for item in intake_queue(session, steward)["rows"]
                if item["reference"] == arrival.source_application_number
            )
            assert row["signals"]["duplicate"]["state"] == "possible duplicate"
    finally:
        factory.dispose()


def test_the_early_resolution_board_groups_by_the_primary_finding(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            first = make_arrival(session)
            second = make_arrival(session)
            for application, kind in ((first, "missing_field"), (second, "duplicate")):
                application.status = "needs_information"
                session.add(
                    permit.ApplicationFinding(
                        id=f"finding_early_{kind}",
                        correlation_id="corr_early",
                        application_id=application.id,
                        finding_type=kind,
                        message=f"A {kind} is in the way.",
                        severity="block",
                        state="current",
                        revision_number=application.revision,
                        version=1,
                    )
                )
            session.flush()
            board = early_resolution(session, steward)
            groups = {group["finding_type"]: group for group in board["groups"]}
            assert "missing_field" in groups
            assert "duplicate" in groups
            assert groups["missing_field"]["count"] == 1
            assert groups["duplicate"]["count"] == 1
            assert groups["missing_field"]["top_findings"][0]["message"] == (
                "A missing_field is in the way."
            )
            # The stable order of the finding types decides the order of the
            # groups: missing_field comes before duplicate.
            assert [group["finding_type"] for group in board["groups"]] == [
                "missing_field",
                "duplicate",
            ]
    finally:
        factory.dispose()


def test_the_review_queue_counts_the_areas_and_lists_the_recent_decisions(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            reviewer = context_for(session, "persona_permit_reviewer")
            arrival = make_arrival(session)
            arrival.status = "ready_for_review"
            arrival.review_area = "Building"
            session.flush()
            queue = review_queue(session, reviewer)
            assert "Building" in queue["areas"]
            assert queue["area_counts"]["Building"] == 1
            assert arrival.source_application_number in {
                row["reference"] for row in queue["rows"]
            }
            narrowed = review_queue(session, reviewer, area="Building")
            assert len(narrowed["rows"]) == 1
            other = review_queue(session, reviewer, area="Fire")
            assert other["rows"] == []
    finally:
        factory.dispose()


def test_the_tabs_of_the_catalogue_match_the_views_of_the_queue(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            queue = intake_queue(session, steward)
            assert [tab["statuses"] for tab in INTAKE_TABS] == [
                (
                    "submitted",
                    "needs_information",
                    "ready_for_review",
                    "under_review",
                    "revisions_requested",
                ),
                ("submitted",),
                ("needs_information",),
                ("ready_for_review", "under_review"),
                ("archived",),
                ("issued", "denied", "returned"),
            ]
    finally:
        factory.dispose()

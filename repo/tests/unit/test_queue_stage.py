"""Stage and next action on the Permit Reviewer's review queue.

Stage is the life-cycle place of the recorded status. Next action is what
that status and its blockers need now. The D01-D11 cases are read as seeded.
Constructed cases use the same temporary database and are rolled back with
the session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from acme_city.applicant_portal.presubmit import FLAG
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.results import ConflictResult
from acme_city.finance.schemas import AllocationCommand, AssessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.permits.decisions import PermitDecisionCommand
from acme_city.permits.issuance import PermitIssuanceService
from acme_city.permits.lifecycle_map import STATUSES
from acme_city.permits.queues import review_queue
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import finance, gis, permit, registry
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.reviewer_views import (
    NEXT_ACTION_LABELS,
    STAGE_EXAMPLE,
    STAGE_PATH,
    present_review_queue,
    queue_place,
    review_row_sort_key,
    stage_of,
)

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
STEWARD = "persona_data_steward"
REVIEWER = "persona_permit_reviewer"
ADMINISTRATOR = "persona_city_administrator"

#: Seeded applications, by scenario, as reference, stage text, next action.
EXPECTED_CASES: dict[str, list[tuple[str, str, str]]] = {
    "D01": [("SYN-APP-001", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D02": [("SYN-APP-002", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D03": [("SYN-APP-003", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D04": [("SYN-APP-004", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D05": [("SYN-APP-005", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D06": [("SYN-APP-006", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D07": [("SYN-APP-007", "Issued (6 of 6)", "Issued")],
    "D08": [("SYN-APP-008", "Submitted (1 of 6)", "Waiting on Data Steward")],
    "D09": [
        ("SYN-APP-009", "Submitted (1 of 6)", "Waiting on Data Steward"),
        ("SYN-APP-010", "Submitted (1 of 6)", "Waiting on Data Steward"),
        ("SYN-APP-011", "Submitted (1 of 6)", "Waiting on Data Steward"),
        ("SYN-APP-012", "Submitted (1 of 6)", "Waiting on Data Steward"),
    ],
    "D11": [("SYN-APP-013", "Submitted (1 of 6)", "Waiting on Data Steward")],
}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Return settings for one freshly reset fictional demonstration database."""
    directory = tmp_path_factory.mktemp("queue-stage")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / 'queue-stage.db'}",
            "ACME_SECRET_KEY": "queue-stage-test-secret-value",
        },
        key_file=directory / "missing.env",
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


def _submit(session, site: str, party_id: str | None = None) -> permit.Application:
    """Submit one application and return the stored row."""
    view = PermitService(session).submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            facts={
                "project_description": "A fictional fence",
                "valuation": "50000.00",
                "valuation_cents": 5000000,
                "submitted_site_text": site,
                "channel": "portal",
            },
            applicant_party_id=party_id,
        ),
        context_for(session, STEWARD),
    )
    application = session.get(permit.Application, view.application_id)
    assert application is not None
    return application


def _place(session, application: permit.Application) -> tuple[str, str]:
    """Return the stage text and next action of one case."""
    place = queue_place(session, application)
    return place["stage_text"], place["next_action"]


def test_stage_follows_the_life_cycle_and_names_the_example() -> None:
    indexes = {item.key: index for index, item in enumerate(STATUSES)}
    places = [stage_of(status) for status in STAGE_PATH]
    assert [place["stage_position"] for place in places] == [1, 2, 3, 4, 5, 6]
    assert [place["stage_text"] for place in places] == [
        "Submitted (1 of 6)",
        "Records matching (2 of 6)",
        STAGE_EXAMPLE,
        "Decision (4 of 6)",
        "Fee (5 of 6)",
        "Issued (6 of 6)",
    ]
    got = [indexes[status] for status in STAGE_PATH]
    assert got == sorted(set(got))
    assert stage_of("ready_for_review")["stage_text"] == STAGE_EXAMPLE == "Checks (3 of 6)"
    keys = [item.key for item in STATUSES]
    assert keys.index("revisions_requested") < keys.index("ready_for_review")
    assert stage_of("revisions_requested")["stage_text"] == "Decision (4 of 6)"
    assert stage_of("under_review")["stage_text"] == "Decision (4 of 6)"
    for status, label in (
        ("denied", "Denied"),
        ("returned", "Returned"),
        ("withdrawn", "Withdrawn"),
        ("archived", "Archived"),
        ("draft", "Draft"),
    ):
        place = stage_of(status)
        assert place["stage_text"] == label
        assert place["stage_position"] == 0
        assert place["stage_label"] == next(item.label for item in STATUSES if item.key == status)
    for item in STATUSES:
        place = stage_of(item.key)
        assert place["stage_total"] == 6
        assert place["stage_text"]
    assert NEXT_ACTION_LABELS["submitted_issues"] == FLAG == "Submitted with known issues"


def test_ready_to_decide_and_ready_to_issue_sort_first() -> None:
    rows = [
        {"next_action_key": "needs_checks", "age_days": 9, "reference": "B"},
        {"next_action_key": "ready_to_issue", "age_days": 1, "reference": "C"},
        {"next_action_key": "ready_to_decide", "age_days": 0, "reference": "A"},
        {"next_action_key": "needs_checks", "age_days": None, "reference": "D"},
    ]
    assert [row["reference"] for row in sorted(rows, key=review_row_sort_key)] == [
        "A",
        "C",
        "B",
        "D",
    ]


def test_seeded_cases_and_a_fresh_submission_map_stage_and_next_action(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            rows = session.execute(select(permit.Application)).scalars().all()
            grouped: dict[str, list[tuple[str, str, str]]] = {}
            for application in rows:
                scenario = application.scenario_id or ""
                if not scenario.startswith("D"):
                    continue
                stage, action = _place(session, application)
                grouped.setdefault(scenario, []).append(
                    (application.source_application_number, stage, action)
                )
            observed = {
                scenario: sorted(items) for scenario, items in grouped.items()
            }
            assert observed == EXPECTED_CASES
            d10 = session.execute(
                select(func.count())
                .select_from(permit.Application)
                .where(permit.Application.scenario_id == "D10")
            ).scalar_one()
            assert d10 == 0
            fresh = _submit(session, "900 Probe Lane, ACME City", "party_cedarline")
            assert fresh.scenario_id is None
            assert fresh.id not in {row.id for row in rows}
            assert _place(session, fresh) == (
                "Submitted (1 of 6)",
                "Waiting on Data Steward",
            )
    finally:
        factory.dispose()


def test_next_action_follows_status_blockers_fee_and_the_presubmit_flag(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            plain = _submit(session, "910 Nowhere Lane, ACME City")
            assert _place(session, plain) == ("Submitted (1 of 6)", "Needs checks")
            plain.presubmit_override = {"reason": "   "}
            session.flush()
            assert _place(session, plain)[1] == "Needs checks"
            plain.presubmit_override = {"reason": "The address is new."}
            session.flush()
            assert _place(session, plain) == (
                "Submitted (1 of 6)",
                "Submitted with known issues",
            )
            match = gis.ApplicationParcelMatch(
                id="pmatch_queue_stage",
                application_id=plain.id,
                correlation_id=plain.correlation_id,
                submitted_text="910 Nowhere Lane, ACME City",
                link_state="proposed",
            )
            session.add(match)
            session.flush()
            assert _place(session, plain)[1] == "Submitted with known issues"
            plain.presubmit_override = None
            session.flush()
            assert _place(session, plain) == (
                "Submitted (1 of 6)",
                "Waiting on Data Steward",
            )
            plain.status = "needs_information"
            session.flush()
            assert _place(session, plain)[1] == "Waiting on Data Steward"
            match.link_state = "approved"
            match.confirmed_at = None
            session.flush()
            assert _place(session, plain) == (
                "Records matching (2 of 6)",
                "In early resolution",
            )

            reviewer = context_for(session, REVIEWER)
            PermitService(session).evaluate(plain.id, reviewer)
            session.refresh(plain)
            assert _place(session, plain) == (STAGE_EXAMPLE, "Ready to decide")
            match.link_state = "proposed"
            session.flush()
            assert _place(session, plain) == (STAGE_EXAMPLE, "Waiting on Data Steward")
            match.link_state = "approved"
            session.flush()
            assert _place(session, plain) == (STAGE_EXAMPLE, "Ready to decide")
            evaluation = PermitService(session).current_evaluation(plain.id)
            assert evaluation is not None
            evaluation.stale = True
            session.flush()
            assert _place(session, plain) == (STAGE_EXAMPLE, "Needs checks")

            closed = _submit(session, "930 Closed Lane, ACME City")
            for status, stage, action in (
                ("denied", "Denied", "Decision recorded"),
                ("returned", "Returned", "Returned"),
                ("withdrawn", "Withdrawn", "Withdrawn"),
                ("archived", "Archived", "Archived"),
                ("revisions_requested", "Decision (4 of 6)", "Waiting for the applicant"),
            ):
                closed.status = status
                session.flush()
                assert _place(session, closed) == (stage, action)

            approved = _submit(session, "940 Fee Lane, ACME City")
            approved.status = "approved"
            approved.presubmit_override = {"reason": "Submitted anyway."}
            session.flush()
            assert _place(session, approved) == ("Fee (5 of 6)", "Fee not settled")

            _settle_d01(session)
            issued_case = session.get(permit.Application, "app_synth_001")
            assert issued_case is not None
            blockers = PermitIssuanceService(session).blockers(
                issued_case, PermitService(session).current_decision(issued_case.id)
            )
            assert [blocker.code for blocker in blockers] == []
            assert _place(session, issued_case) == ("Fee (5 of 6)", "Ready to issue")

            waiting = session.get(permit.Application, "app_d02")
            assert waiting is not None
            waiting.status = "ready_for_review"
            session.flush()
            raw = {
                "rows": [
                    {
                        "application_id": plain.id,
                        "reference": "NEW",
                        "age_days": 0,
                        "status": plain.status,
                    },
                    {
                        "application_id": waiting.id,
                        "reference": waiting.source_application_number,
                        "age_days": 40,
                        "status": waiting.status,
                    },
                    {
                        "application_id": issued_case.id,
                        "reference": issued_case.source_application_number,
                        "age_days": 1,
                        "status": issued_case.status,
                    },
                ],
                "area": "Building",
                "area_counts": {"Building": 99},
            }
            # The evaluated case is stale, so it is Needs checks. Use a fresh
            # evaluated case so Ready to decide is the one that sorts first.
            ready = _submit(session, "950 Decide Lane, ACME City")
            PermitService(session).evaluate(ready.id, reviewer)
            session.refresh(ready)
            assert _place(session, ready) == (STAGE_EXAMPLE, "Ready to decide")
            raw["rows"][0]["application_id"] = ready.id
            snapshot = [dict(row) for row in raw["rows"]]
            presented = present_review_queue(session, raw, "")
            assert raw["rows"] == snapshot
            assert presented["area_counts"] == {"Building": 99}
            assert [row["reference"] for row in presented["rows"]] == [
                "NEW",
                "SYN-APP-001",
                "SYN-APP-002",
            ]
            assert [row["next_action"] for row in presented["rows"]] == [
                "Ready to decide",
                "Ready to issue",
                "Waiting on Data Steward",
            ]
            chips = presented["next_actions"]
            assert [chip["key"] for chip in chips[:2]] == [
                "ready_to_decide",
                "ready_to_issue",
            ]
            narrowed = present_review_queue(session, raw, "ready_to_decide")
            chip = next(
                item for item in narrowed["next_actions"] if item["key"] == "ready_to_decide"
            )
            assert chip["count"] == len(narrowed["rows"]) == 1
            assert narrowed["rows"][0]["reference"] == "NEW"
            assert narrowed["next_all_count"] == 3
            assert narrowed["next_all_href"] == "/queue/review?area=Building"
            assert chip["href"] == "/queue/review?area=Building&next_action=ready_to_decide"
            unknown = present_review_queue(session, raw, "not-an-action")
            assert unknown["next_action"] == ""
            assert len(unknown["rows"]) == unknown["next_all_count"] == 3
            missing = present_review_queue(
                session,
                {
                    "rows": [
                        {
                            "application_id": "missing",
                            "status": "submitted",
                            "reference": "Z",
                            "age_days": 3,
                        }
                    ],
                    "area": "",
                },
                "",
            )
            assert missing["rows"][0]["next_action"] == "Needs checks"
            assert missing["rows"][0]["stage_text"] == "Submitted (1 of 6)"
            assert missing["next_all_href"] == "/queue/review"

            reviewer_queue = review_queue(session, reviewer)
            shown = present_review_queue(session, reviewer_queue, "")
            assert shown["area_counts"] == reviewer_queue["area_counts"]
            assert shown["total_in_review"] == reviewer_queue["total_in_review"]
            assert all("next_action" not in row for row in reviewer_queue["rows"])
            assert shown["next_all_count"] == len(reviewer_queue["rows"])
    finally:
        factory.dispose()


def _settle_d01(session) -> None:
    """Approve, assess and allocate the seeded D01 case. Stop before issuance."""
    for party_id in ("party_cedarline", "party_ironvale"):
        session.add(
            registry.Crosswalk(
                id=f"crosswalk_queue_{party_id}",
                entity_id=party_id,
                entity_type="party",
                source_system_id="permitting",
                source_dataset_key="applicant_profiles",
                source_record_id=f"PER-{party_id}",
                link_status="approved",
                decision="Approved by the data steward.",
                decision_actor_id=STEWARD,
                decided_at=DECIDED_AT,
            )
        )
    session.add(
        finance.FinanceAccountLink(
            id="faclink_queue_stage",
            account_id="facct_cedarline_legacy",
            party_id="party_cedarline",
            link_status="approved",
            decided_by_actor_id=STEWARD,
            decided_at=DECIDED_AT,
        )
    )
    session.flush()
    permits = PermitService(session)
    finance_service = FinanceService(session)
    reviewer = context_for(session, REVIEWER)
    administrator = context_for(session, ADMINISTRATOR)
    evaluation = permits.evaluate("app_synth_001", reviewer)
    before_payment = session.get(permit.Application, "app_synth_001")
    assert before_payment is not None
    decided = permits.decide(
        PermitDecisionCommand(
            application_id="app_synth_001",
            expected_application_version=before_payment.version,
            outcome="approved",
            reason="Fictional demonstration approval.",
            expected_evaluation_version=evaluation.version,
        ),
        reviewer,
    )
    assert not isinstance(decided, ConflictResult), decided
    session.refresh(before_payment)
    assessment = finance_service.assess(
        AssessmentCommand(application_id="app_synth_001"), administrator
    )
    assert _place(session, before_payment) == ("Fee (5 of 6)", "Fee not settled")
    finance_service.allocate(
        AllocationCommand(
            payment_id="payment_d01_settled",
            assessment_id=assessment.assessment_id,
            amount="150.00",
            idempotency_key="alloc:test:queue-stage",
        ),
        administrator,
    )
    session.refresh(before_payment)


def test_the_helper_module_is_the_file_under_test() -> None:
    """The mapping lives in the view layer, not in a schema change."""
    path = Path(queue_place.__code__.co_filename)
    assert path.name == "reviewer_views.py"

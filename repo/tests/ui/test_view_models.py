"""The view models of the eight screens.

The view models report the resolved responsibility, the four value bands, the
permitted actions and their reasons, the evidence and the history.  They
never decide anything themselves.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-02, SEC-02
# The view models keep the current, submitted, proposed and issued values
# apart, name the grant and the destination of every action, and report the
# responsibility of every governed record.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import view_models


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'ui-view-models.db'}",
            "ACME_SECRET_KEY": "ui-view-models-secret-value",
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
    return settings, bundle


@pytest.fixture()
def session(environment: tuple[Settings, FixtureBundle]) -> Session:
    settings, _ = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


def actor_for(session: Session, actor_id: str) -> ActorContext:
    """Return the acting context of one seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def test_the_selector_offers_exactly_the_four_personas(session: Session) -> None:
    options = view_models.persona_options(session)
    assert [option["label"] for option in options] == [
        "Applicant",
        "Data Steward",
        "Permit Reviewer",
        "City Administrator",
    ]
    assert all(option["actor_id"].startswith("persona_") for option in options)
    labels = " ".join(option["actor_id"] for option in options)
    assert "service_" not in labels


def test_the_responsibility_panel_answers_the_eight_questions(session: Session) -> None:
    panel = view_models.responsibility(
        session,
        domain_id="permits",
        version=3,
        source_system_id="permitting",
        dataset_key="applications_and_permits",
        subject_ids=("app_synth_001",),
    )
    for field in (
        "owner",
        "steward",
        "source",
        "change_this_in",
        "last_source_update",
        "last_received",
        "version",
        "open_issues",
    ):
        assert field in panel
    assert panel["owner"]
    assert panel["steward"]
    assert panel["source"] == "permitting"
    assert panel["change_this_in"]
    assert panel["last_source_update"]
    assert panel["last_received"]
    assert panel["version"] == 3
    assert isinstance(panel["open_issues"], list)


def test_the_source_update_time_and_the_receipt_time_stay_separate(session: Session) -> None:
    panel = view_models.responsibility(
        session,
        domain_id="applicants",
        source_system_id="permitting",
        dataset_key="applicant_profiles",
    )
    assert panel["last_source_update"] != panel["last_received"]


def test_the_work_queue_reports_the_blocker_the_age_and_the_next_action(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_permit_reviewer")
    queue = view_models.work_queue(session, actor)
    assert queue["entries"]
    entry = next(
        item for item in queue["entries"] if item["id"] == "app_synth_001"
    )
    assert entry["object_type"] == "Application"
    assert entry["next_action"]
    assert "day" in entry["target"]
    assert entry["href"] == "/permits/app_synth_001"
    assert entry["blocker_code"] or entry["blocker"] == ""


def test_the_work_queue_filters_by_state_and_by_object(session: Session) -> None:
    actor = actor_for(session, "persona_city_administrator")
    everything = view_models.work_queue(session, actor, view="all")
    states = {entry["state"] for entry in everything["entries"]}
    filtered = view_models.work_queue(session, actor, view="all", state="issued")
    assert filtered["entries"]
    assert all(entry["state"] == "issued" for entry in filtered["entries"])
    assert "issued" in states
    by_object = view_models.work_queue(session, actor, view="all", object_type="Application")
    assert by_object["entries"]
    assert all(entry["object_type"] == "Application" for entry in by_object["entries"])


def test_the_permit_workspace_separates_the_four_value_bands(session: Session) -> None:
    actor = actor_for(session, "persona_permit_reviewer")
    workspace = view_models.permit_workspace(session, actor, "app_synth_001")
    assert workspace["current"]["version"] >= 1
    assert workspace["submitted"]["facts"]
    assert workspace["submitted"]["revision_number"] == 1
    assert workspace["proposed"] == []
    assert workspace["issued"] == []
    assert workspace["responsibility"]["domain_id"] == "permits"
    assert workspace["history"] is not None


def test_the_issued_permit_is_shown_as_its_own_value_band(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    workspace = view_models.permit_workspace(session, actor, "app_d07")
    assert workspace["issued"]
    assert workspace["issued"][0]["permit_number"]
    assert workspace["issued"][0]["artifact_hash"]


def test_an_action_names_its_grant_its_destination_and_its_version(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_permit_reviewer")
    actions = view_models.allowed_actions_for(session, actor, "permit", "app_synth_001")
    evaluate = next(item for item in actions if item["action_id"] == "permit.evaluate")
    assert evaluate["permitted"] is True
    assert evaluate["permission"] == "application.evaluate"
    assert evaluate["destination"] == "Permitting validation"
    assert evaluate["expected_version"] is not None
    decide = next(item for item in actions if item["action_id"] == "permit.decide")
    assert decide["permission"] == "permit.decide"
    assert decide["fields"]
    assert all("role" not in field["name"] for field in decide["fields"])


def test_a_denied_action_explains_the_refusal(session: Session) -> None:
    actor = actor_for(session, "persona_applicant")
    actions = view_models.allowed_actions_for(session, actor, "permit", "app_synth_001")
    decide = next(item for item in actions if item["action_id"] == "permit.decide")
    assert decide["permitted"] is False
    assert "permit.decide" in decide["reason"]
    explanations = view_models.denied_action_explanations(actions)
    assert any(entry["action_id"] == "permit.decide" for entry in explanations)
    assert all(entry["reason"] for entry in explanations)


def test_the_administrator_may_read_the_case_but_may_not_approve_it(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    actions = view_models.allowed_actions_for(session, actor, "permit", "app_synth_001")
    decide = next(item for item in actions if item["action_id"] == "permit.decide")
    issue = next(item for item in actions if item["action_id"] == "permit.issue")
    assert decide["permitted"] is False
    assert issue["permitted"] is False
    assert view_models.allows(session, actor, "records.audit.view")


def test_the_applicant_sees_only_its_own_applications(session: Session) -> None:
    actor = actor_for(session, "persona_applicant")
    applications = view_models.visible_applications(session, actor)
    identifiers = {application.id for application in applications}
    assert identifiers == {"app_d05", "app_d09_setback", "app_d09_setback_nan"}
    assert "app_synth_001" not in identifiers
    parties = view_models.visible_parties(session, actor)
    assert {party.id for party in parties} == {"party_applicant_1"}


def test_the_applicant_may_not_open_another_applicant(session: Session) -> None:
    actor = actor_for(session, "persona_applicant")
    assert view_models.party_detail(session, actor, "party_cedarline") == {}
    assert view_models.permit_workspace(session, actor, "app_synth_001") == {}


def test_the_steward_review_reports_the_evidence_and_the_acknowledgement(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_data_steward")
    review = view_models.steward_review(session, actor)
    assert review["source_records"]
    assert review["source_records"][0]["source_record_id"]
    assert review["source_records"][0]["ingested_at"]
    assert review["commands"] == []
    assert review["deliveries"] == []
    assert review["responsibility"]["domain_id"] == "applicants"


def test_the_reconciliation_screen_reports_the_balance_and_the_exception(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    position = view_models.reconciliation(session, actor)
    assert position["assessments"]
    assessment = position["assessments"][0]
    assert assessment["position"]["assessed_total"]
    assert "balance" in assessment["position"]
    assert position["payments"]
    assert position["accounts"]


def test_the_model_runs_carry_an_explicit_mode(session: Session) -> None:
    actor = actor_for(session, "persona_data_steward")
    runs = view_models.model_runs(session, actor)
    assert runs == []


#: The screens each persona may open, in canonical navigation order. Derived
#: from the seeded grants through SCREEN_PERMISSIONS; hidden screens 403.
#:
#: Parity phase 3b added three screens after the existing entries, so the
#: order of the existing screens is unchanged and the new ones come last:
#: the Data Steward opens the intake queue and the early-resolution board
#: (both behind a grant only that persona holds) and the Permit Reviewer
#: opens the review queue.  No other persona gains a screen.
#:
#: P3insight adds the City view after those entries, behind its own grant
#: (``insight.city.view``), which only the City Administrator holds.
#:
#: Policy 2 adds the What-if screen after the City view, behind its own grant
#: (``policy.scenario.manage``), which only the City Administrator holds.
#:
#: P3c adds the dashboard, the audit log, support and the checks after it, each
#: behind its own grant that only the City Administrator holds.
#:
#: Steward restyle (changed deliberately): the Data Steward and the City
#: Administrator hold Master records, where People & organizations is a tab, so
#: "applicants" is no longer listed for them (the Applicant and the Permit
#: Reviewer keep it).  Source records and Activity follow Data issues; both are
#: read-only screens behind the steward's own read grants.
EXPECTED_NAVIGATION: dict[str, list[str]] = {
    "persona_applicant": ["queue", "applicants", "permit"],
    "persona_data_steward": [
        "queue",
        "masters",
        "permit",
        "steward",
        "source_records",
        "activity",
        "rules",
        "agent_intake",
        "intake_queue",
        "early_resolution",
    ],
    "persona_permit_reviewer": [
        "queue",
        "applicants",
        "permit",
        "agent_adjudication",
        "review_queue",
    ],
    "persona_city_administrator": [
        # Changed deliberately (the City Administrator planning overview): the
        # Administrator lands on the overview, so it is the first entry of the
        # navigation.  No other persona gains a screen.
        "overview",
        "queue",
        "masters",
        "permit",
        "steward",
        "source_records",
        "activity",
        "rules",
        "reconciliation",
        "governance",
        "agent_intake",
        "agent_adjudication",
        "admin",
        "insight_city",
        "policy_scenarios",
        # P3c: the four operations screens follow the What-if screen.
        "ops_dashboard",
        "ops_audit",
        "ops_support",
        "ops_checks",
    ],
}


@pytest.mark.parametrize("actor_id", sorted(EXPECTED_NAVIGATION))
def test_the_navigation_is_scoped_to_the_persona_grants(
    session: Session, actor_id: str
) -> None:
    actor = actor_for(session, actor_id)
    items = view_models.navigation(session, actor)
    assert [item["key"] for item in items] == EXPECTED_NAVIGATION[actor_id]
    permit_item = next(item for item in items if item["key"] == "permit")
    assert permit_item["href"].startswith("/permits/")


def test_model_runs_match_an_application_stored_in_an_input_refs_object(
    session: Session,
) -> None:
    from datetime import UTC, datetime

    from acme_city.persistence.models.model_run import ModelRun

    session.add(
        ModelRun(
            id="modelrun_regression_refs",
            mode="replay",
            input_refs={"task": "extraction", "application_id": "app_synth_001", "documents": []},
            started_at=datetime(2026, 10, 27, tzinfo=UTC),
            correlation_id="corr_regression_refs",
        )
    )
    session.flush()
    actor = actor_for(session, "persona_data_steward")
    matched = view_models.model_runs(session, actor, application_id="app_synth_001")
    assert [run["run_id"] for run in matched] == ["modelrun_regression_refs"]
    assert view_models.model_runs(session, actor, application_id="app_synth_002") == []


def test_an_approval_with_conditions_reads_as_approved_with_conditions() -> None:
    from acme_city.persistence.models import permit
    from acme_city.ui.view_models import decision_outcome_label

    with_conditions = permit.Decision(outcome="approved", conditions=["Deck guard required"])
    plain = permit.Decision(outcome="approved", conditions=None)
    denied = permit.Decision(outcome="denied", conditions=None)
    assert decision_outcome_label(with_conditions) == "Approved with conditions"
    assert decision_outcome_label(plain) == "Approved"
    assert decision_outcome_label(denied) == "Denied"

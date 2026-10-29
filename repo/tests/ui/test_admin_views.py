"""The City Administrator screens: the planning overview, the rules and fee
register, the governance and sources screen and the reconciliation screen.

The screens report what the services recorded.  These checks prove that every
figure is counted from the stored rows, that the states of a version stay
apart, that the diff comes from the two stored version records and that the
next action follows the lifecycle and the persona's grants.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-03, GOV-04, REF-01, REF-02, PER-06, FIN-05, SEC-01
# The Administrator screens count stored rows, diff stored version records,
# name the date basis of a version and offer only the action the state and
# the grants allow.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import admin_views


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'admin-views.db'}",
            "ACME_SECRET_KEY": "admin-views-secret-value",
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


# ---------------------------------------------------------------- the overview


def test_the_overview_counts_the_applications_that_need_attention(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    overview = admin_views.planning_overview(session, actor)
    attention = overview["attention"]
    assert attention["count"] == len(attention["entries"])
    assert attention["count"] > 0
    assert attention["label"]
    assert attention["definition"]
    for entry in attention["entries"]:
        assert entry["reference"]
        assert entry["reason"]
        assert entry["href"].startswith("/permits/")


def test_the_overview_links_the_city_view_the_what_if_and_the_dashboard(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    overview = admin_views.planning_overview(session, actor)
    hrefs = [item["href"] for item in overview["related"]]
    assert "/insight/city" in hrefs
    assert "/policy/scenarios" in hrefs
    # Changed deliberately (P3c merged): the Operations dashboard is linked.
    assert "/ops/dashboard" in hrefs


def test_the_overview_counts_the_versions_that_are_not_published(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    overview = admin_views.planning_overview(session, actor)
    changes = overview["changes"]
    assert changes["count"] == len(changes["entries"])
    labels = {entry["version_label"] for entry in changes["entries"]}
    assert "CT-2@2" in labels
    assert "fee_commercial_demo 2026.2" in labels
    for entry in changes["entries"]:
        assert entry["status"] in ("draft", "in_review", "approved")
        assert entry["date"]


def test_the_overview_reports_the_freshness_of_the_three_sources(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    overview = admin_views.planning_overview(session, actor)
    labels = [entry["label"] for entry in overview["sources"]["entries"]]
    assert labels == ["GIS", "Permitting", "ERP/Finance"]
    for entry in overview["sources"]["entries"]:
        assert entry["last_changed"] or entry["last_received"]


# --------------------------------------------------------------- rules, fees


def test_the_register_separates_the_assigned_approver_from_the_approval(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    # A draft has not entered the approval workflow, so nobody approved it.
    assert row["approved_by"] == "not approved yet"
    assert row["approved_on"] == "not approved yet"
    assert row["assigned_approver"] == "Building Safety director (accountable owner)"


def test_the_register_shows_a_published_version_as_approved(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="published")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@1")
    assert row["approved_by"] == "City Administrator"
    assert row["status_label"] == "Published"


def test_awaiting_approval_is_only_used_after_the_review_step(
    session: Session,
) -> None:
    assert admin_views.VERSION_STATUS_LABELS["draft"] == "Draft"
    assert admin_views.VERSION_STATUS_LABELS["in_review"] == "In review, awaiting approval"  # editorial pass (vollencoms): no dash
    for label in admin_views.VERSION_STATUS_LABELS.values():
        assert "awaiting approval" not in label or label.startswith("In review")


def test_the_selected_draft_version_shows_the_diff_of_the_two_records(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    selected = admin_views.rules_register(
        session, actor, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    assert selected is not None
    changed = {change["field"]: change for change in selected["diff"]}
    assert changed["limit_value"]["before"] == "250000"
    assert changed["limit_value"]["after"] == "300000"
    assert changed["effective_from"]["before"] == "1 Jan 2026"
    assert changed["effective_from"]["after"] == "1 Nov 2026"
    assert selected["compared_with"] == "CT-2@1"
    assert selected["published_side"]["label"] == "CT-2@1"
    assert selected["proposed_side"]["label"] == "CT-2@2"


def test_the_selected_version_keeps_the_states_apart(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    selected = admin_views.rules_register(
        session, actor, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    states = selected["states"]
    assert set(states) == {
        "draft",
        "approval",
        "publication",
        "effective_period",
        "applicability",
    }
    assert "has not entered the approval workflow" in states["draft"]
    assert "No approval is recorded" in states["approval"]
    assert states["effective_period"] == "From 1 Nov 2026, open ended"  # editorial pass (vollencoms): no dash
    assert "initial submission time (initial_submitted_at)" in states["applicability"]


def test_the_selected_version_names_the_date_basis_and_the_applicability(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    selected = admin_views.rules_register(
        session, actor, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    assert selected["applicability"]["basis_label"] == "initial_submitted_at"
    assert "later revision does not switch the schedule" in (
        selected["applicability"]["basis_text"]
    )
    # No sample application was submitted inside the proposed period.
    assert selected["applicability"]["applications"] == []
    assert "No sample application" in selected["applicability"]["note"]


def test_a_version_without_a_predecessor_says_that_it_has_nothing_to_compare(
    session: Session,
) -> None:
    administrator = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(
        session, administrator, tab="rules", view="published"
    )
    row = next(item for item in register["rows"] if item["version_label"] == "PA-1@1")
    selected = admin_views.rules_register(
        session, administrator, tab="rules", view="published", version_id=row["row_id"]
    )["selected"]
    assert selected is not None
    assert selected["diff"] == []
    assert (
        selected["diff_note"]
        == "The stored version records hold no differing content to compare."
    )


def test_the_overlapping_effective_period_is_warned_about(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    selected = admin_views.rules_register(
        session, actor, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    assert "CT-2@1" in selected["overlap_warning"]
    assert "overlap" in selected["overlap_warning"]


def test_the_next_action_follows_the_lifecycle_and_the_grants(
    session: Session,
) -> None:
    administrator = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, administrator, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    selected = admin_views.rules_register(
        session, administrator, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    # The draft was authored by the Data Steward, so the Administrator may
    # submit it for review but is not its author.
    assert selected["next_action"]["label"] == "Submit for review"
    assert selected["next_action"]["available"] is True

    steward = actor_for(session, "persona_data_steward")
    author_view = admin_views.rules_register(
        session, steward, tab="rules", view="drafts", version_id=row["row_id"]
    )["selected"]
    assert author_view["next_action"]["label"] == "Submit for review"


def test_the_actions_of_the_selected_version_follow_the_lifecycle_order(
    session: Session,
) -> None:
    administrator = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, administrator, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    actions = admin_views.rules_register(
        session, administrator, tab="rules", view="drafts", version_id=row["row_id"]
    )["actions"]
    assert [item["label"] for item in actions] == [
        "Edit draft",
        "Submit for review",
        "Compare versions",
        "Approve version",
        "Publish version",
        "Retire version",
    ]
    by_label = {item["label"]: item for item in actions}
    assert by_label["Submit for review"]["permitted"] is True
    assert by_label["Compare versions"]["href"].endswith("#version-diff")
    # The other steps are not available on a draft, and each says why.
    for label in ("Approve version", "Publish version", "Retire version"):
        assert by_label[label]["permitted"] is False
        assert by_label[label]["reason"]


def test_an_author_is_told_that_another_administrator_must_approve(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pinned: this test is about the independent policy (approval policy setting, Randall).
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "independent")
    from acme_city.rules.schemas import RuleLifecycleCommand
    from acme_city.rules.service import RuleCatalogService

    steward = actor_for(session, "persona_data_steward")
    register = admin_views.rules_register(session, steward, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    stored = session.get(finance.RuleVersion, row["row_id"])
    assert stored is not None
    RuleCatalogService(session).submit_for_review(
        RuleLifecycleCommand(
            rule_version_id=stored.id,
            expected_version=stored.version,
            reason="a fictional demonstration step",
        ),
        steward,
    )
    session.flush()
    actions = admin_views.rules_register(
        session, steward, tab="rules", view="drafts", version_id=row["row_id"]
    )["actions"]
    approve = next(item for item in actions if item["label"] == "Approve version")
    assert approve["permitted"] is False
    assert "You authored this version; another administrator must approve it." in (
        approve["reason"]
    )


def test_the_history_view_reads_the_recorded_lifecycle_events(
    session: Session,
) -> None:
    from acme_city.rules.schemas import RuleLifecycleCommand
    from acme_city.rules.service import RuleCatalogService

    administrator = actor_for(session, "persona_city_administrator")
    before = admin_views.rules_register(
        session, administrator, tab="rules", view="history"
    )
    assert before["history"] == []
    assert before["row_count_label"].startswith("0 recorded lifecycle event")

    steward = actor_for(session, "persona_data_steward")
    register = admin_views.rules_register(session, steward, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    stored = session.get(finance.RuleVersion, row["row_id"])
    assert stored is not None
    RuleCatalogService(session).submit_for_review(
        RuleLifecycleCommand(
            rule_version_id=stored.id,
            expected_version=stored.version,
            reason="a fictional demonstration step",
        ),
        steward,
    )
    session.flush()
    after = admin_views.rules_register(
        session, administrator, tab="rules", view="history"
    )
    assert len(after["history"]) == 1
    event = after["history"][0]
    assert event["version_label"] == "CT-2@2"
    assert event["actor"] == "Data Steward"
    assert event["reason"] == "a fictional demonstration step"


def test_the_published_version_names_its_approver(
    session: Session,
) -> None:
    administrator = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(
        session, administrator, tab="rules", view="published"
    )
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@1")
    # The published version was authored by the Data Steward.  A version the
    # acting persona authored may never be approved or published by them.
    assert row["assigned_approver"] == "Building Safety director (accountable owner)"
    assert row["approved_by"] == "City Administrator"


def test_the_fee_register_shows_the_fee_component_diff(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, actor, tab="fees", view="drafts")
    row = next(
        item for item in register["rows"] if item["version_label"].endswith("2026.2")
    )
    selected = admin_views.rules_register(
        session, actor, tab="fees", view="drafts", version_id=row["row_id"]
    )["selected"]
    changed = {change["field"]: change for change in selected["diff"]}
    assert changed["valuation_multiplier"]["before"] == "0.001"
    assert changed["valuation_multiplier"]["after"] == "0.0015"


# ------------------------------------------------------------------ governance


def test_the_governance_screen_opens_with_the_sources(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.governance_screen(session, actor)
    assert screen["tab"] == "sources"
    labels = [item["label"] for item in screen["sources"]]
    assert labels == ["GIS", "Permitting", "ERP/Finance"]
    for item in screen["sources"]:
        assert item["responsible_team"]
        assert item["record_count"] >= 0


def test_the_governance_screen_has_the_five_tabs(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.governance_screen(session, actor)
    assert [tab["key"] for tab in screen["tabs"]] == [
        "sources",
        "responsibilities",
        "authority",
        "access",
        "history",
    ]


def test_the_access_tab_reads_the_persisted_grants(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.governance_screen(session, actor, tab="access")
    entries = {entry["actor_id"]: entry for entry in screen["access"]}
    assert set(entries) == {
        "persona_applicant",
        "persona_data_steward",
        "persona_permit_reviewer",
        "persona_city_administrator",
        "persona_agent_operator",
    }
    administrator = entries["persona_city_administrator"]
    assert "admin.overview.view" in administrator["permissions"]
    applicant = entries["persona_applicant"]
    assert "admin.overview.view" not in applicant["permissions"]


# --------------------------------------------------------------- reconciliation


def test_the_reconciliation_screen_shows_the_three_scopes(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(session, actor)
    assert [tab["key"] for tab in screen["tabs"]] == [
        "assessments",
        "receipts",
        "accounts",
    ]
    assert screen["rows"]
    assert screen["receipts"]


def test_an_assessment_is_shown_by_its_readable_reference(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(session, actor)
    row = screen["rows"][0]
    assert row["reference"] == "SYN-APP-007"
    # The internal identifier is a second name of the same record.
    assert row["application_id"] == "app_d07"
    assert row["reference"] != row["application_id"]


def test_the_receipt_register_keeps_the_currencies_apart(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(session, actor, tab="receipts")
    currencies = {receipt["currency"] for receipt in screen["receipts"]}
    assert "EUR" in currencies
    assert "USD" in currencies
    euro = next(receipt for receipt in screen["receipts"] if receipt["currency"] == "EUR")
    assert euro["distinct_currency"] is True


def test_the_exception_measure_is_labelled_and_is_not_styled_when_it_is_zero(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(session, actor)
    exceptions = screen["exceptions"]
    assert exceptions["count"] == 0
    assert exceptions["attention"] is False
    assert exceptions["definition"]


def test_the_selected_assessment_shows_its_receipts_and_allocations(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(
        session, actor, assessment_id="assess_d07_v1"
    )
    selected = screen["selected"]
    assert selected is not None
    assert selected["reference"] == "SYN-APP-007"
    assert selected["assessed_total"] == "220.00"
    assert selected["balance"] == "0.00"
    assert selected["receipts"]
    assert selected["allocations"]
    assert screen["actions"]


def test_the_receipt_register_is_a_separate_tab_from_the_assessment(
    session: Session,
) -> None:
    actor = actor_for(session, "persona_city_administrator")
    screen = admin_views.reconciliation_screen(
        session, actor, tab="receipts", assessment_id="assess_d07_v1"
    )
    assert screen["tab"] == "receipts"
    # The register holds every receipt, not only the one of the assessment.
    assert len(screen["receipts"]) > 1


# ------------------------------------------------------------ approval policy


def _author_in_review(session: Session):
    """Return the Administrator, who authors CT-2@2 here and submits it for review."""
    from acme_city.rules.schemas import RuleLifecycleCommand
    from acme_city.rules.service import RuleCatalogService

    administrator = actor_for(session, "persona_city_administrator")
    register = admin_views.rules_register(session, administrator, tab="rules", view="drafts")
    row = next(item for item in register["rows"] if item["version_label"] == "CT-2@2")
    stored = session.get(finance.RuleVersion, row["row_id"])
    assert stored is not None
    stored.author_actor_id = administrator.actor_id
    RuleCatalogService(session).submit_for_review(
        RuleLifecycleCommand(
            rule_version_id=stored.id, expected_version=stored.version, reason="fictional step"
        ),
        administrator,
    )
    session.flush()
    return administrator, row["row_id"]


@pytest.mark.parametrize("mode", ["independent", "single"])
def test_the_guarded_reason_for_an_author_appears_only_in_independent_mode(
    session: Session, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", mode)
    administrator, row_id = _author_in_review(session)
    register = admin_views.rules_register(
        session, administrator, tab="rules", view="drafts", version_id=row_id
    )
    approve = next(item for item in register["actions"] if item["label"] == "Approve version")
    reason = "You authored this version; another administrator must approve it."
    assert register["approval_policy"]["line"] == (
        "Approval policy: single administrator"
        if mode == "single"
        else "Approval policy: independent approval"
    )
    if mode == "independent":
        assert approve["permitted"] is False and reason in approve["reason"]
        assert reason in register["selected"]["next_action"]["reason"]
    else:
        assert approve["permitted"] is True
        assert register["selected"]["next_action"]["available"] is True
        names = [field["name"] for field in approve["fields"]]
        assert "confirm_author_approval" in names and "reason" in names
        assert next(f for f in approve["fields"] if f["name"] == "reason")["required"]
        assert next(f for f in approve["fields"] if f["name"] == "confirm_author_approval")["required"]


def test_an_approval_by_the_author_shows_its_basis_in_every_view(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from acme_city.rules.schemas import RuleLifecycleCommand
    from acme_city.rules.service import RuleCatalogService

    monkeypatch.setenv("ACME_APPROVAL_POLICY", "single")
    administrator, row_id = _author_in_review(session)
    stored = session.get(finance.RuleVersion, row_id)
    RuleCatalogService(session).approve(
        RuleLifecycleCommand(
            rule_version_id=row_id,
            expected_version=stored.version,
            reason="Agreed.",
            confirm_author_approval=True,
        ),
        administrator,
    )
    session.flush()
    label = "Approved by the author (single-administrator policy)"
    register = admin_views.rules_register(
        session, administrator, tab="rules", view="drafts", version_id=row_id
    )
    assert label in register["selected"]["states"]["approval"]
    assert any(event["basis"] == label for event in register["selected"]["history"])
    history = admin_views.rules_register(session, administrator, tab="rules", view="history")
    assert any(event["basis"] == label for event in history["history"])
    from acme_city.ops import audit_log

    rows = audit_log.audit_log(session, action="rule.version.approve")["rows"]
    assert [row["basis"] for row in rows] == [label]


@pytest.mark.parametrize("mode", ["independent", "single"])
def test_the_overview_card_follows_the_approval_policy(
    session: Session, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", mode)
    overview = admin_views.planning_overview(
        session, actor_for(session, "persona_city_administrator")
    )
    changes = overview["changes"]
    expected = "single administrator" if mode == "single" else "independent approval"
    assert changes["approval_policy"]["line"] == f"Approval policy: {expected}"
    texts = {entry["status"]: entry["next_step"] for entry in changes["entries"]}
    assert texts["draft"] == "Submit for review"

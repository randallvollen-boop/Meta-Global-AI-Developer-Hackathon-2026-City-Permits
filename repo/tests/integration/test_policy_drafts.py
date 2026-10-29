"""Policy 4: a what-if run saved as draft rule and fee changes.

End to end: run the headline scenario (fence side/rear limit 6 to 7 ft, DF-2),
save it as a draft, and show that the Administrator is the recorded author, that
the draft needs independent approval, that the author cannot approve or publish
it, and that nothing published changes.  Also: unsupported and mixed scenarios
are refused whole, the conversion is idempotent per run and version, needs CSRF
and a mandatory version, is audited, and stops when the published rule changed.
"""
# REQUIRES: REF-01, PER-02, PER-04, PER-06, SEC-01, UX-01
# A run converts to drafts only, in the Administrator's name, once and atomically; the author
# cannot approve or publish, and the published rules do not change.

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from insight_support import ADMIN, build_environment, open_factory
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.errors import ConflictError, PermissionDeniedError, ValidationError
from acme_city.persistence.models import audit as audit_models
from acme_city.persistence.models import finance
from acme_city.persistence.models import policy as models
from acme_city.persistence.session import transaction
from acme_city.policy.drafts import (
    HANDOFF_STATUS,
    OWN_VERSION_REASON,
    PolicyDraftService,
    plan_for_run,
)
from acme_city.policy.service import PolicyService
from acme_city.rules.schemas import FeeScheduleLifecycleCommand, PublishRuleCommand, RuleLifecycleCommand
from acme_city.rules.service import RuleCatalogService
from acme_city.ui.router import router as ui_router

STEWARD = "persona_data_steward"
REVIEWER = "persona_permit_reviewer"
APPLICANT = "persona_applicant"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
FENCE = {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}
FEE = {"kind": "fee", "fee_schedule_id": "fee_commercial_demo", "valuation_multiplier": "0.002"}
TARGET = {"kind": "service_target", "permit_type_key": "deck_fence", "service_target_days": 3}
RETIRE = {"kind": "rule_retirement", "rule_id": "DF-3"}


@pytest.fixture()
def settings(tmp_path):
    return build_environment(tmp_path, synthetic=False, name="drafts.db")


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> TestClient:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
    return client


def csrf_of(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "the page carries a form token"
    return match.group(1)


def version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d+)"', body)
    assert match
    return match.group(1)


def actor_context(session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def make_run(session, changes, *, count: str = "60") -> models.PolicyRun:
    admin = actor_context(session, ADMIN)
    service = PolicyService(session, now=NOW)
    scenario = service.create_scenario(admin, name="Draft test", changes=changes, expected_version=0)
    return service.run_scenario(
        admin, scenario.id, expected_version=scenario.version,
        spec={"kind": "synthetic_year", "count": count},
    )


def published_snapshot(session) -> list[str]:
    rules = session.execute(
        select(finance.RuleVersion).where(finance.RuleVersion.status == "published")
        .order_by(finance.RuleVersion.id)
    ).scalars().all()
    fees = session.execute(
        select(finance.FeeScheduleVersion).where(finance.FeeScheduleVersion.status == "published")
        .order_by(finance.FeeScheduleVersion.id)
    ).scalars().all()
    return [
        json.dumps([r.id, r.rule_id, r.limit_value, r.operator, r.message, r.version, r.status], default=str)
        for r in rules
    ] + [json.dumps([f.id, f.version_label, f.definition, f.version, f.status], default=str) for f in fees]


def counts(session) -> tuple[int, int, int]:
    return (
        session.execute(select(func.count()).select_from(finance.RuleVersion)).scalar_one(),
        session.execute(select(func.count()).select_from(finance.FeeScheduleVersion)).scalar_one(),
        session.execute(select(func.count()).select_from(models.PolicyDraftConversion)).scalar_one(),
    )


def fence_run_through_the_screens(client: TestClient) -> tuple[str, str]:
    """Return ``(editor path, run path)`` for the headline scenario made through the screens."""
    page = choose(client, ADMIN).get("/policy/scenarios")
    created = client.post(
        "/policy/scenarios",
        data={"csrf_token": csrf_of(page.text), "expected_version": "0", "suggestion": "fence_height_7ft",
              "name": "Raise the side/rear fence height limit from 6 ft to 7 ft"},
        follow_redirects=False,
    )
    editor = created.headers["location"].split("?")[0]
    page = client.get(editor)
    ran = client.post(
        f"{editor}/run",
        data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
              "kind": "synthetic_year", "seed": "20261028", "count": "300"},
        follow_redirects=False,
    )
    assert ran.status_code == 303, ran.text
    return editor, ran.headers["location"]


# ------------------------------------------------------------ the headline demo


def test_headline_demo_run_to_draft_needs_independent_approval(
    client, settings, monkeypatch
) -> None:
    # Pinned: this test is about the independent policy (approval policy setting, Randall).
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "independent")
    _, run_path = fence_run_through_the_screens(client)
    run_id = run_path.rsplit("/", 1)[1]
    factory = open_factory(settings)
    with factory() as session:
        before_published = published_snapshot(session)
        before_counts = counts(session)
    factory.dispose()

    page = client.get(run_path)
    assert "Save as a draft rule change" in page.text
    assert 'data-testid="policy-draft-submit"' in page.text and "disabled" not in page.text.split(
        'data-testid="policy-draft-form"')[1].split("</form>")[0]
    assert "Draft: needs independent approval" not in page.text  # not before the press

    saved = client.post(
        f"{run_path}/draft",
        data={"csrf_token": csrf_of(page.text), "expected_version": version_of(
            page.text.split('data-testid="policy-draft-form"')[1])},
        follow_redirects=False,
    )
    assert saved.status_code == 303, saved.text
    after = client.get(saved.headers["location"].split("#")[0])
    assert HANDOFF_STATUS in after.text and "Draft: needs independent approval" in after.text
    assert 'data-testid="policy-draft-row"' in after.text and 'data-kind="rule"' in after.text
    assert "DF-2" in after.text
    assert OWN_VERSION_REASON in after.text  # the plain reason beside the guarded buttons
    assert "Who can approve" in after.text

    factory = open_factory(settings)
    with factory() as session:
        # Nothing published changed; exactly one draft rule version and one link were added.
        assert published_snapshot(session) == before_published
        assert counts(session) == (before_counts[0] + 1, before_counts[1], before_counts[2] + 1)
        draft = session.execute(
            select(finance.RuleVersion).where(
                finance.RuleVersion.status == "draft", finance.RuleVersion.rule_id == "DF-2")
        ).scalar_one()
        assert draft.rule_id == "DF-2" and draft.limit_value == "7" and draft.operator == "max"
        assert draft.author_actor_id == ADMIN and draft.approver_actor_id is None
        assert "7 ft" in (draft.message or "") and "6 ft" not in (draft.message or "")
        assert draft.source_mapping["policy_run_id"] == run_id
        link = session.execute(select(models.PolicyDraftConversion)).scalar_one()
        assert link.run_id == run_id and link.converted_by_actor_id == ADMIN
        assert link.drafts[0]["id"] == draft.id
        draft_id = draft.id
    factory.dispose()

    # The link shows both ways: Rules and fees points at the run.
    rules_page = client.get("/rules-fees")
    assert f"/policy/runs/{run_id}#draft" in rules_page.text

    # The author submits it to review (the existing lifecycle), then cannot approve or publish it.
    token = csrf_of(rules_page.text)
    for action_id, extra in (("rule.submit", {}),):
        response = client.post(
            f"/ui/actions/{action_id}",
            data={"csrf_token": token, "rule_version_id": draft_id, "expected_version": "1",
                  "reason": "ready", **extra},
            follow_redirects=False,
        )
        assert response.status_code in (200, 303), response.text
    for action_id, version in (("rule.approve", "2"), ("rule.publish", "2")):
        response = client.post(
            f"/ui/actions/{action_id}",
            data={"csrf_token": token, "rule_version_id": draft_id, "expected_version": version,
                  "reason": "mine"},
        )
        assert response.status_code == 403, (action_id, response.text)
        assert OWN_VERSION_REASON in response.text, action_id
    factory = open_factory(settings)
    with factory() as session:
        row = session.get(finance.RuleVersion, draft_id)
        assert row.status == "in_review" and row.approver_actor_id is None
        assert published_snapshot(session) == before_published
    factory.dispose()


@pytest.mark.parametrize("mode", ["independent", "single"])
def test_the_service_itself_refuses_self_approval_and_self_publication(
    settings, monkeypatch, mode
) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", mode)
    factory = open_factory(settings)
    with transaction(factory) as session:
        admin = actor_context(session, ADMIN)
        conversion, created = PolicyDraftService(session, now=NOW).convert(
            admin, make_run(session, [FENCE]).id, expected_version=0
        )
        assert created
        draft_id = conversion.drafts[0]["id"]
        catalogue = RuleCatalogService(session, now=NOW)
        catalogue.submit_for_review(
            RuleLifecycleCommand(rule_version_id=draft_id, expected_version=1, reason="x"), admin
        )
        if mode == "independent":
            with pytest.raises(PermissionDeniedError):
                catalogue.approve(
                    RuleLifecycleCommand(rule_version_id=draft_id, expected_version=2, reason="x"), admin
                )
            with pytest.raises(PermissionDeniedError):
                catalogue.publish(
                    PublishRuleCommand(rule_version_id=draft_id, expected_version=2, reason="x"), admin
                )
        else:
            # Single: allowed, but only with a reason and an explicit confirmation.
            with pytest.raises(ValidationError):
                catalogue.approve(
                    RuleLifecycleCommand(rule_version_id=draft_id, expected_version=2, reason="x"), admin
                )
            with pytest.raises(ValidationError):
                catalogue.approve(
                    RuleLifecycleCommand(
                        rule_version_id=draft_id, expected_version=2, reason="", confirm_author_approval=True
                    ),
                    admin,
                )
            approved = catalogue.approve(
                RuleLifecycleCommand(
                    rule_version_id=draft_id, expected_version=2, reason="fence limit agreed",
                    confirm_author_approval=True,
                ),
                admin,
            )
            published = catalogue.publish(
                PublishRuleCommand(
                    rule_version_id=draft_id, expected_version=approved.version, reason="in force",
                    precedence="newest_effective_from",
                ),
                admin,
            )
            assert published.value.status == "published"
            events = session.execute(
                select(audit_models.AuditEvent).where(
                    audit_models.AuditEvent.target_id == draft_id,
                    audit_models.AuditEvent.action.in_(("rule.version.approve", "rule.version.publish")),
                )
            ).scalars().all()
            labels = {e.action: e.metadata_json["approval_basis_label"] for e in events}
            assert labels == {
                "rule.version.approve": "Approved by the author (single-administrator policy)",
                "rule.version.publish": "Published by the author (single-administrator policy)",
            }
    factory.dispose()


# -------------------------------------------------------- unsupported and mixed


@pytest.mark.parametrize("changes", [[RETIRE], [TARGET], [FENCE, TARGET], [FENCE, RETIRE]])
def test_unsupported_and_mixed_scenarios_are_refused_whole(settings, changes) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        run = make_run(session, changes)
        plan = plan_for_run(run)
        assert not plan.convertible and plan.blockers
        before = counts(session)
        with pytest.raises(ValidationError) as caught:
            PolicyDraftService(session, now=NOW).convert(actor_context(session, ADMIN), run.id, expected_version=0)
        assert caught.value.code == "unsupported_change"
        assert "Nothing was converted" in caught.value.message
        assert counts(session) == before  # not even the supported part
    factory.dispose()


def test_the_screen_guards_the_button_and_lists_the_simulation_only_changes(client) -> None:
    page = choose(client, ADMIN).get("/policy/scenarios")
    created = client.post(
        "/policy/scenarios",
        data={"csrf_token": csrf_of(page.text), "expected_version": "0", "name": "Mixed",
              "suggestion": "fence_height_7ft"},
        follow_redirects=False,
    )
    editor = created.headers["location"].split("?")[0]
    page = client.get(editor)
    client.post(
        f"{editor}/save",
        data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
              "operation": "add_change", "kind": "service_target", "permit_type_key": "deck_fence",
              "service_target_days": "3"},
    )
    page = client.get(editor)
    ran = client.post(
        f"{editor}/run",
        data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
              "kind": "synthetic_year", "seed": "1", "count": "40"},
        follow_redirects=False,
    )
    assert ran.status_code == 303, ran.text
    run_path = ran.headers["location"]
    body = client.get(run_path).text
    assert 'data-testid="policy-draft-form"' not in body
    assert "disabled" in body.split('data-testid="policy-draft-submit"')[0][-200:] or "disabled" in body
    guard = body.split('data-testid="policy-draft-guard"')[1][:300]
    assert "simulation-only" in guard
    blockers = body.split('data-testid="policy-draft-blockers"')[1].split("</ul>")[0]
    assert "service target" in blockers
    refused = client.post(
        f"{run_path}/draft", data={"csrf_token": csrf_of(body), "expected_version": "0"}
    )
    assert refused.status_code == 422 and "simulation-only" in refused.text


# ------------------------------------------------------ rule and fee together


def test_rule_and_fee_changes_convert_together_in_one_transaction(settings) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        before = published_snapshot(session)
        run = make_run(session, [FENCE, FEE])
        conversion, created = PolicyDraftService(session, now=NOW).convert(
            actor_context(session, ADMIN), run.id, expected_version=0
        )
        assert created and [d["kind"] for d in conversion.drafts] == ["rule", "fee"]
        fee = session.get(finance.FeeScheduleVersion, conversion.drafts[1]["id"])
        assert fee.status == "draft" and fee.author_actor_id == ADMIN
        assert fee.definition["valuation_multiplier"] == "0.002"
        assert fee.definition["fixed_review_charge_cents"] == 10000
        assert not any(key.startswith("example_") for key in fee.definition)
        assert fee.version_label.endswith(run.id[-8:])
        assert published_snapshot(session) == before
    factory.dispose()


def test_a_failure_while_drafting_leaves_no_draft_at_all(settings, monkeypatch) -> None:
    def boom(self, command, actor):
        raise ValidationError("the fee schedule could not be drafted")

    monkeypatch.setattr(RuleCatalogService, "draft_fee_schedule", boom)
    factory = open_factory(settings)
    with transaction(factory) as session:
        run = make_run(session, [FENCE, FEE])
        run_id = run.id
        session.commit()
        before = counts(session)
        with pytest.raises(ValidationError):
            PolicyDraftService(session, now=NOW).convert(actor_context(session, ADMIN), run_id, expected_version=0)
        assert counts(session) == before  # the rule draft made first was rolled back too
    factory.dispose()


# ---------------------------------------------------- idempotent, bound, audited


def test_conversion_is_idempotent_per_run_and_version(settings) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        admin = actor_context(session, ADMIN)
        service = PolicyDraftService(session, now=NOW)
        run = make_run(session, [FENCE])
        first, created = service.convert(admin, run.id, expected_version=0)
        assert created and first.version == 1
        after_first = counts(session)
        again, created_again = service.convert(admin, run.id, expected_version=0)
        assert not created_again and again.id == first.id and counts(session) == after_first
        same, created_same = service.convert(admin, run.id, expected_version=1)
        assert not created_same and same.id == first.id and counts(session) == after_first
        with pytest.raises(ConflictError):
            service.convert(admin, run.id, expected_version=7)
        # A different run converts separately.
        other = make_run(session, [FENCE])
        later = PolicyDraftService(session, now=datetime(2026, 10, 28, 13, 0, tzinfo=UTC))
        assert later.convert(admin, other.id, expected_version=0)[1] is True
        assert counts(session)[2] == 2
    factory.dispose()


def test_the_version_is_mandatory_and_a_wrong_first_version_conflicts(settings) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        admin = actor_context(session, ADMIN)
        service = PolicyDraftService(session, now=NOW)
        run = make_run(session, [FENCE])
        before = counts(session)
        with pytest.raises(ValidationError):
            service.convert(admin, run.id, expected_version=None)
        with pytest.raises(ConflictError):
            service.convert(admin, run.id, expected_version=3)
        assert counts(session) == before
    factory.dispose()


def test_csrf_version_and_grants_on_the_conversion_route(client, settings) -> None:
    _, run_path = fence_run_through_the_screens(client)
    page = client.get(run_path)
    token = csrf_of(page.text)
    assert client.post(f"{run_path}/draft", data={"csrf_token": "wrong", "expected_version": "0"}).status_code == 403
    assert client.post(f"{run_path}/draft", data={"csrf_token": token}).status_code == 422
    assert client.post(f"{run_path}/draft", data={"csrf_token": token, "expected_version": "x"}).status_code == 422
    assert client.post(f"{run_path}/draft", data={"csrf_token": token, "expected_version": "4"}).status_code == 409
    factory = open_factory(settings)
    with factory() as session:
        assert counts(session)[2] == 0
    factory.dispose()
    for actor in (APPLICANT, STEWARD, REVIEWER):
        choose(client, actor)
        assert client.post(f"{run_path}/draft", data={"csrf_token": token, "expected_version": "0"}).status_code == 403, actor
    factory = open_factory(settings)
    with factory() as session:
        assert counts(session)[2] == 0
        resolver = PermissionResolver(session)
        assert "policy.draft.convert" in resolver.permissions_for(ADMIN)
        for actor in (APPLICANT, STEWARD, REVIEWER):
            assert "policy.draft.convert" not in resolver.permissions_for(actor)
    factory.dispose()


def test_the_conversion_is_audited_without_free_text(settings) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        run = make_run(session, [FENCE])
        conversion, _ = PolicyDraftService(session, now=NOW).convert(
            actor_context(session, ADMIN), run.id, expected_version=0
        )
        session.flush()
        event = session.execute(
            select(audit_models.AuditEvent).where(audit_models.AuditEvent.action == "policy.draft.convert")
        ).scalar_one()
        assert event.actor_id == ADMIN and event.target_id == run.id and event.outcome == "accepted"
        assert event.metadata_json["draft_ids"] == [conversion.drafts[0]["id"]]
        assert event.metadata_json["run_content_hash"] == run.content_hash
        draft_audit = session.execute(
            select(audit_models.AuditEvent).where(audit_models.AuditEvent.action == "rule.version.draft")
        ).scalars().all()
        assert draft_audit and all(item.actor_id == ADMIN for item in draft_audit)
    factory.dispose()


def test_a_changed_published_rule_stops_the_conversion(settings) -> None:
    factory = open_factory(settings)
    with transaction(factory) as session:
        run = make_run(session, [FENCE])
        published = session.execute(
            select(finance.RuleVersion).where(
                finance.RuleVersion.rule_id == "DF-2", finance.RuleVersion.status == "published"
            )
        ).scalar_one()
        published.limit_value = "5"  # the published rule moved after the run was made
        session.flush()
        before = counts(session)
        with pytest.raises(ConflictError) as caught:
            PolicyDraftService(session, now=NOW).convert(actor_context(session, ADMIN), run.id, expected_version=0)
        assert "Run the what-if again" in caught.value.message
        session.rollback()
    factory.dispose()
    factory = open_factory(settings)
    with factory() as session:
        assert counts(session)[2] == 0 and before[2] == 0
    factory.dispose()


@pytest.mark.parametrize("mode", ["independent", "single"])
def test_a_fee_draft_still_needs_another_person_to_approve_it(settings, monkeypatch, mode) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", mode)
    factory = open_factory(settings)
    with transaction(factory) as session:
        admin = actor_context(session, ADMIN)
        conversion, _ = PolicyDraftService(session, now=NOW).convert(
            admin, make_run(session, [FEE]).id, expected_version=0
        )
        fee_id = conversion.drafts[0]["id"]
        catalogue = RuleCatalogService(session, now=NOW)
        catalogue.submit_fee_schedule_for_review(
            FeeScheduleLifecycleCommand(fee_schedule_version_id=fee_id, expected_version=1, reason="x"), admin
        )
        view = PolicyDraftService(session, now=NOW).drafts_view(admin, conversion)[0]
        assert view["you_are_author"]
        if mode == "independent":
            with pytest.raises(PermissionDeniedError):
                catalogue.approve_fee_schedule(
                    FeeScheduleLifecycleCommand(fee_schedule_version_id=fee_id, expected_version=2, reason="x"),
                    admin,
                )
            with pytest.raises(PermissionDeniedError):
                catalogue.publish_fee_schedule(
                    FeeScheduleLifecycleCommand(fee_schedule_version_id=fee_id, expected_version=2, reason="x"),
                    admin,
                )
            assert view["reason_you_cannot"] == OWN_VERSION_REASON
            assert all(item["actor_id"] != ADMIN for item in view["approvers"])
            assert view["status_label"] == "In review: needs independent approval"
        else:
            with pytest.raises(ValidationError):
                catalogue.approve_fee_schedule(
                    FeeScheduleLifecycleCommand(fee_schedule_version_id=fee_id, expected_version=2, reason="x"),
                    admin,
                )
            approved = catalogue.approve_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=fee_id, expected_version=2, reason="rate agreed",
                    confirm_author_approval=True,
                ),
                admin,
            )
            published = catalogue.publish_fee_schedule(
                FeeScheduleLifecycleCommand(
                    fee_schedule_version_id=fee_id, expected_version=approved.version, reason="in force",
                    effective_to=None, precedence="newest_effective_from",
                ),
                admin,
            )
            assert published.value.status == "published"
            assert view["reason_you_cannot"] == ""
            assert view["status_label"] == "In review: ready for your approval"
            assert any(item["actor_id"] == ADMIN for item in view["approvers"])
    factory.dispose()

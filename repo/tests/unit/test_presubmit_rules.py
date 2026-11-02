"""The rules layer on unsaved facts, and the three groups the applicant sees.

A draft uses the same evaluation as a saved case.  A broken rule is Must fix.
A pass is Looks good.  A borderline result is Should check.  An address that
matches no parcel is Should check: it never holds the application.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from acme_city.applicant_portal.presubmit import (
    address_item,
    group_review,
    override_record,
    sentence_for,
)
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.presubmit import validate_feedback
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.service import PermitService


def _result(**extra: object) -> SimpleNamespace:
    values = {
        "rule_id": "DF-1",
        "citation": "ACME Code §14-305",
        "status": "fail",
        "message": "Front yard fence is above the 4 ft maximum.",
        "operator": "max",
        "limit_value": "4",
        "unit": None,
    }
    values.update(extra)
    return SimpleNamespace(**values)


def test_a_broken_rule_names_the_section_and_a_pass_does_not_repeat_the_violation() -> None:
    failed = sentence_for(_result(), "Fence height, front yard")
    assert failed == (
        "Front yard fence is above the 4 ft maximum. See ACME Code §14-305. Use 4 or less."
    )
    passed = sentence_for(
        _result(status="pass", message="Front yard fence is above the 4 ft maximum."),
        "Fence height, front yard",
    )
    assert passed == "Fence height, front yard meets ACME Code §14-305."
    assert "above the 4 ft maximum" not in passed
    review = sentence_for(_result(status="condition", rule_id="DF-4"), "Deck height")
    assert review == "Deck height needs a check against ACME Code §14-305."


def test_the_groups_are_must_fix_should_check_and_looks_good() -> None:
    rule_set = SimpleNamespace(
        rules=[
            SimpleNamespace(rule_id="DF-1", title="Fence height, front yard"),
            SimpleNamespace(rule_id="DF-2", title="Fence height, side and rear yard"),
            SimpleNamespace(rule_id="DF-4", title="Deck height"),
        ]
    )
    grouped = group_review(
        [
            _result(),
            _result(rule_id="DF-2", status="pass", citation="ACME Code §14-306"),
            _result(rule_id="DF-4", status="condition", citation="ACME Code §14-218"),
        ],
        rule_set,
        {"parcel_matched": True, "ambiguous": False, "locator_available": True, "message": "ok"},
        address_text="400 Lantern Row",
    )
    assert [item["rule_id"] for item in grouped["must_fix"]] == ["DF-1"]
    assert [item["rule_id"] for item in grouped["looks_good"]] == ["DF-2"]
    assert [item["rule_id"] for item in grouped["should_check"]] == ["DF-4"]
    assert grouped["labels"] == {
        "must_fix": "Must fix",
        "should_check": "Should check",
        "looks_good": "Looks good",
    }


def test_an_unmatched_address_never_holds_the_application() -> None:
    """An address the locator cannot place is Should check, never Must fix."""
    unmatched = address_item(
        {
            "parcel_matched": False,
            "locator_available": True,
            "message": "We could not find that address.",
        },
        "999 Missing Street",
    )
    assert unmatched is not None and unmatched["status"] == "review"
    assert unmatched["kind"] == "address"
    assert unmatched["rule_id"] == ""
    assert unmatched["sentence"] == (
        "We could not match this address to a parcel. The City will match it."
    )
    down = address_item(
        {
            "parcel_matched": False,
            "locator_available": False,
            "message": "The address service is not available. You can still submit.",
        },
        "400 Lantern Row",
    )
    assert down is None
    assert address_item({"parcel_matched": False, "message": ""}, "") is None
    ambiguous = address_item(
        {
            "parcel_matched": True,
            "ambiguous": True,
            "locator_available": True,
            "message": "Did you mean one of these?",
        },
        "400 Lantern",
    )
    assert ambiguous is not None and ambiguous["status"] == "review"


def test_an_unmatched_address_stays_out_of_must_fix() -> None:
    """The grouped review holds the application on a rule, not on an address."""
    rule_set = SimpleNamespace(rules=[SimpleNamespace(rule_id="DF-1", title="Fence height")])
    grouped = group_review(
        [_result(status="pass", citation="ACME Code §14-306")],
        rule_set,
        {
            "parcel_matched": False,
            "locator_available": True,
            "message": "We could not find that address in the city locator.",
        },
        address_text="12 Imaginary Lane",
    )
    assert grouped["must_fix"] == []
    assert [item["kind"] for item in grouped["should_check"]] == ["address"]
    assert grouped["should_check"][0]["sentence"] == (
        "We could not match this address to a parcel. The City will match it."
    )


def test_an_override_record_keeps_the_reason_and_the_flag() -> None:
    review = {"must_fix": [{"sentence": "Too tall.", "citation": "ACME Code §14-305", "kind": "rule"}]}
    record = override_record(review, "  The fence is already built.  ", recorded_at="2026-11-01T00:00:00+00:00")
    assert record["reason"] == "The fence is already built."
    assert record["flag"] == "Submitted with known issues"
    assert record["detail"] == "Submitted with known issues: The fence is already built."
    assert record["issues"] == [
        {"sentence": "Too tall.", "citation": "ACME Code §14-305", "kind": "rule"}
    ]


def test_feedback_may_cite_only_the_rules_that_ran() -> None:
    allowed = {"DF-1"}
    citations = {"ACME Code §14-305"}
    good = {
        "items": [{"rule_id": "DF-1", "text": "Lower the fence. See ACME Code §14-305."}],
        "cannot_review": False,
        "reason": "",
    }
    assert validate_feedback(good, allowed_ids=allowed, allowed_citations=citations) == []
    invented = {
        "items": [{"rule_id": "DF-99", "text": "See ACME Code §99-999."}],
        "cannot_review": False,
        "reason": "",
    }
    assert "invented_rule" in validate_feedback(
        invented, allowed_ids=allowed, allowed_citations=citations
    )
    approved = {
        "items": [{"rule_id": "DF-1", "text": "This application is approved."}],
        "cannot_review": False,
        "reason": "",
    }
    assert "approved" in validate_feedback(
        approved, allowed_ids=allowed, allowed_citations=citations
    )
    declined = {"items": [], "cannot_review": True, "reason": ""}
    assert "cannot_review" in validate_feedback(
        declined, allowed_ids=allowed, allowed_citations=citations
    )


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'presubmit-rules.db'}",
            "ACME_SECRET_KEY": "presubmit-rules-test-secret",
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


def _context_for(session, actor_id: str) -> ActorContext:
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


def _signature(results) -> list[tuple]:
    signed = []
    for result in results:
        data = result.model_dump(mode="json")
        signed.append(
            (
                data["rule_id"],
                data["status"],
                data["citation"],
                data["message"],
                data["observed_value"],
            )
        )
    return signed


def test_unsaved_facts_match_permit_evaluate_for_every_d_scenario(seeded: Settings) -> None:
    """One loop over the seeded D scenarios.  D10 has no application."""
    pattern = re.compile(r"^D\d\d$")
    factory = SessionFactory(seeded.database_url)
    seen: set[str] = set()
    try:
        with transaction(factory) as session:
            reviewer = _context_for(session, "persona_permit_reviewer")
            service = PermitService(session)
            applications = session.execute(select(permit.Application)).scalars().all()
            for application in applications:
                scenario_id = str(application.scenario_id or "")
                if pattern.fullmatch(scenario_id) is None:
                    continue
                seen.add(scenario_id)
                permit_type = session.get(permit.PermitType, application.permit_type_id)
                assert permit_type is not None, application.id
                revision = service.current_revision(application.id)
                basis_at = application.initial_submitted_at or revision.submitted_at
                predicted, _rule_set, _inputs = service.rule_results(
                    permit_type.key,
                    revision.snapshot or {},
                    basis_at=basis_at,
                    extra_inputs=service.parcel_inputs(application),
                )
                if application.status in {"archived", "returned"}:
                    current = service.current_evaluation(application.id)
                    if current is None:
                        continue
                    stored = service.evaluation_view(current).results
                else:
                    before = application.status
                    view = service.evaluate(application.id, reviewer)
                    stored = view.results
                    if before == "issued":
                        assert application.status == "issued", scenario_id
                assert _signature(predicted) == _signature(stored), (scenario_id, application.id)
    finally:
        factory.dispose()
    assert {f"D{number:02d}" for number in range(1, 12)} - {"D10"} <= seen

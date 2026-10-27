"""Unit tests for the deterministic recommendation agent.

The outcome comes only from the rule results, and the rationale cites each
rule with its observed value and limit.  A Muse summary may only explain:
one that names a different outcome is rejected.
"""

from __future__ import annotations

from acme_city.triage.service import build_rationale, recommendation_outcome
from acme_city.triage.summary import deterministic_summary, validate_summary


def result(status: str, reason: str = "rule_satisfied") -> dict:
    return {
        "rule_id": "DF-1",
        "citation": "ACME Code §14-305",
        "status": status,
        "reason": reason,
        "observed_value": "6",
        "limit_value": "4",
        "operator": "max",
        "message": "Front yard fence is above the 4 ft maximum.",
    }


def test_all_pass_recommends_approve() -> None:
    assert recommendation_outcome([result("pass")]) == "approve"


def test_any_fail_recommends_deny() -> None:
    assert recommendation_outcome([result("pass"), result("fail", "rule_violated")]) == "deny"


def test_fail_from_missing_input_requests_information() -> None:
    assert recommendation_outcome([result("fail", "missing_input")]) == "request_information"


def test_any_condition_recommends_approve_with_conditions() -> None:
    assert recommendation_outcome([result("pass"), result("condition")]) == "approve_with_conditions"


def test_review_recommends_reviewer_judgment() -> None:
    assert recommendation_outcome([result("review", "missing_condition_input")]) == "request_information"
    assert recommendation_outcome([result("review", "unknown_category")]) == "needs_reviewer_judgment"


def test_rationale_cites_rule_observed_and_limit() -> None:
    text = build_rationale([result("fail", "rule_violated")], "deny")
    assert "DF-1" in text
    assert "6" in text
    assert "4" in text
    assert "ACME Code §14-305" in text
    assert "above the 4 ft maximum" in text


def test_summary_that_names_another_outcome_is_rejected() -> None:
    assert validate_summary('{"summary": "This case should be approved."}', expected_outcome="deny") is None
    assert validate_summary('{"summary": "The front fence is too tall."}', expected_outcome="deny") == "The front fence is too tall."
    assert validate_summary("not json", expected_outcome="deny") is None


def test_deterministic_summary_is_labelled_deterministic() -> None:
    text = deterministic_summary("approve", "DF-2: passed.")
    assert text.startswith("Deterministic recommendation: approve.")

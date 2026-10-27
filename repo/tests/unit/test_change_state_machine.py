"""Change state machine tests: the two paths, the permissions and self-approval."""

from __future__ import annotations

from acme_city.changes.state_machine import (
    FACTUAL_PATH,
    REGISTRY_PATH,
    allowed_transitions,
    permitted_targets,
    transition_rule,
)


def test_the_factual_path_runs_through_the_source() -> None:
    assert permitted_targets("requested", "factual") == ("in_review", "rejected")
    assert "awaiting_approval" in permitted_targets("in_review", "factual")
    assert "approved" in permitted_targets("in_review", "factual")
    assert "sent_to_source" in permitted_targets("approved", "factual")
    assert "source_acknowledged" in permitted_targets("sent_to_source", "factual")
    assert "published" in permitted_targets("source_acknowledged", "factual")
    assert "closed" in permitted_targets("published", "factual")


def test_the_registry_path_commits_in_the_registry() -> None:
    assert "registry_committed" in permitted_targets("approved", "identity")
    assert "sent_to_source" not in permitted_targets("approved", "identity")
    assert "source_acknowledged" not in permitted_targets("registry_committed", "identity")
    assert "published" in permitted_targets("registry_committed", "identity")


def test_a_case_cannot_skip_its_review() -> None:
    assert transition_rule("requested", "approved", "factual") is None
    assert transition_rule("requested", "sent_to_source", "factual") is None
    assert transition_rule("in_review", "published", "factual") is None
    assert transition_rule("closed", "published", "factual") is None


def test_the_approval_needs_an_approver_and_forbids_self_approval() -> None:
    rule = transition_rule("in_review", "approved", "factual")
    assert rule is not None
    assert rule.requires_approver is True
    assert rule.prohibits_self_approval is True
    assert rule.action == "change.case.transition"


def test_the_dispatcher_owns_the_synchronization_states() -> None:
    for status, target in (
        ("sent_to_source", "source_acknowledged"),
        ("sent_to_source", "synchronization_failed"),
        ("source_acknowledged", "published"),
        ("registry_committed", "published"),
    ):
        rule = transition_rule(status, target, "factual" if status != "registry_committed" else "identity")
        assert rule is not None
        assert rule.performed_by_dispatcher is True


def test_the_declared_paths_match_the_machine() -> None:
    for path, kind in ((FACTUAL_PATH, "factual"), (REGISTRY_PATH, "identity")):
        for current, following in zip(path, path[1:]):
            assert transition_rule(current, following, kind) is not None, (current, following)


def test_a_rejection_needs_a_reason() -> None:
    rule = transition_rule("requested", "rejected", "factual")
    assert rule is not None
    assert rule.reason_required is True

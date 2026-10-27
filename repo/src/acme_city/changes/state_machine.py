"""The change state machine.

The server decides which transition is allowed.  A client may ask for a
transition; it may not perform one.  Each state names the action that is
needed, whether an approver is required and whether the requester may not
approve their own request.
"""
# REQUIRES: CHG-01, CHG-02, EDIT-03
# The permitted transitions, their permissions and the separation of approval
# from synchronization are declared here.

from __future__ import annotations

from dataclasses import dataclass

#: The factual correction path.
FACTUAL_PATH: tuple[str, ...] = (
    "requested",
    "in_review",
    "awaiting_approval",
    "approved",
    "sent_to_source",
    "source_acknowledged",
    "published",
    "closed",
)

#: The registry identity path.
REGISTRY_PATH: tuple[str, ...] = (
    "requested",
    "in_review",
    "awaiting_approval",
    "approved",
    "registry_committed",
    "published",
    "closed",
)

#: The states that only belong to one of the two paths.
FACTUAL_ONLY_STATES: frozenset[str] = frozenset({"sent_to_source", "source_acknowledged"})
REGISTRY_ONLY_STATES: frozenset[str] = frozenset({"registry_committed"})

#: The action a steward needs to move a case.
TRANSITION_ACTION = "change.case.transition"


@dataclass(frozen=True)
class TransitionRule:
    """The rule of one permitted transition."""

    target_status: str
    action: str = TRANSITION_ACTION
    requires_approver: bool = False
    prohibits_self_approval: bool = False
    performed_by_dispatcher: bool = False
    reason_required: bool = False


_ALLOWED: dict[str, tuple[TransitionRule, ...]] = {
    "requested": (
        TransitionRule("in_review"),
        TransitionRule("rejected", reason_required=True),
    ),
    "in_review": (
        TransitionRule("awaiting_approval"),
        TransitionRule("approved", requires_approver=True, prohibits_self_approval=True),
        TransitionRule("rejected", reason_required=True),
    ),
    "awaiting_approval": (
        TransitionRule(
            "approved", requires_approver=True, prohibits_self_approval=True
        ),
        TransitionRule("in_review"),
        TransitionRule("rejected", reason_required=True),
    ),
    "approved": (
        TransitionRule("sent_to_source"),
        TransitionRule("registry_committed"),
        TransitionRule("rejected", reason_required=True),
    ),
    "sent_to_source": (
        TransitionRule("source_acknowledged", performed_by_dispatcher=True),
        TransitionRule("synchronization_failed", performed_by_dispatcher=True),
    ),
    "source_acknowledged": (
        TransitionRule("published", performed_by_dispatcher=True),
        TransitionRule("synchronization_failed", performed_by_dispatcher=True),
    ),
    "registry_committed": (
        TransitionRule("published", performed_by_dispatcher=True),
    ),
    "published": (TransitionRule("closed"),),
    "synchronization_failed": (
        TransitionRule("in_review"),
        TransitionRule("closed"),
    ),
    "rejected": (TransitionRule("closed"),),
    "closed": (),
}

#: The states a change case may end in.
TERMINAL_STATES: frozenset[str] = frozenset({"closed"})


def allowed_transitions(status: str, change_kind: str) -> tuple[TransitionRule, ...]:
    """Return the transitions that are permitted from a state.

    Args:
        status: The current state of the change case.
        change_kind: ``factual`` or ``identity``.  The two paths never share
            their source-specific states.
    """
    rules = _ALLOWED.get(status, ())
    permitted: list[TransitionRule] = []
    for rule in rules:
        if change_kind == "factual" and rule.target_status in REGISTRY_ONLY_STATES:
            continue
        if change_kind == "identity" and rule.target_status in FACTUAL_ONLY_STATES:
            continue
        permitted.append(rule)
    return tuple(permitted)


def transition_rule(
    status: str, target_status: str, change_kind: str
) -> TransitionRule | None:
    """Return the rule of one transition, when it is permitted."""
    for rule in allowed_transitions(status, change_kind):
        if rule.target_status == target_status:
            return rule
    return None


def permitted_targets(status: str, change_kind: str) -> tuple[str, ...]:
    """Return the names of the states a case may move to."""
    return tuple(rule.target_status for rule in allowed_transitions(status, change_kind))


__all__ = [
    "FACTUAL_ONLY_STATES",
    "FACTUAL_PATH",
    "REGISTRY_ONLY_STATES",
    "REGISTRY_PATH",
    "TERMINAL_STATES",
    "TRANSITION_ACTION",
    "TransitionRule",
    "allowed_transitions",
    "permitted_targets",
    "transition_rule",
]

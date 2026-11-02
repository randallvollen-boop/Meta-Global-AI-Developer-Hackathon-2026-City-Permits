"""The permission bundle of the Agent Operator.

``AGENT_OPERATIONS`` is the set of grants the Agent Operator holds: it wakes
and puts to sleep the agents, runs each of them and processes a bounded
selection of waiting cases.  It carries no decision, issuance or
configuration grant.  ``agent.ops.read`` joins it with the agents home
(OPR-16).

The City worker option grants the same bundle to a staff role, with the same
domains, so one list and one table of domains describe the whole bundle.
"""

from __future__ import annotations

#: The grants of the agent operations bundle, in catalogue order.
AGENT_OPERATIONS: tuple[str, ...] = (
    "agent.ops.read",
    "agent.toggle",
    "agent.run.intake",
    "agent.run.adjudication",
    "agent.run.steward_assist",
    "permit.intake.process_selected",
)

#: The domain every bundle grant covers.  Reading the operations screens and
#: waking or putting an agent to sleep are not bound to the permit domain;
#: running an agent and processing the selected cases are.  The steward
#: assistant works on the records of the steward queue, which is not one
#: domain of a permit, so its grant is not bound to a domain either.
AGENT_OPERATION_DOMAINS: dict[str, str | None] = {
    "agent.ops.read": None,
    "agent.toggle": None,
    "agent.run.intake": "permits",
    "agent.run.adjudication": "permits",
    "agent.run.steward_assist": None,
    "permit.intake.process_selected": "permits",
}

__all__ = ["AGENT_OPERATION_DOMAINS", "AGENT_OPERATIONS"]

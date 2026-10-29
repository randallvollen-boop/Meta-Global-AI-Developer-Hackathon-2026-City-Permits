"""The permission bundle of the Agent Operator.

``AGENT_OPERATIONS`` is the set of grants the Agent Operator holds: it wakes
and puts to sleep the two agents, runs each of them and processes a bounded
selection of waiting cases.  It carries no decision, issuance or
configuration grant.  ``agent.ops.read`` joins it with the agents home
(OPR-16).
"""

from __future__ import annotations

#: The grants of the agent operations bundle, in catalogue order.
AGENT_OPERATIONS: tuple[str, ...] = (
    "agent.toggle",
    "agent.run.intake",
    "agent.run.adjudication",
    "permit.intake.process_selected",
)

__all__ = ["AGENT_OPERATIONS"]

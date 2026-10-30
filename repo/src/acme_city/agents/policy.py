"""Persisted processing-policy reads for the Agent Operator lane.

The policy of the City says when the agents work: manually, when a person
asks, or automatically as the work arrives.  It never says what a case
decides: the people of the City review every recommendation.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import agent_ops

#: The mode of a policy that waits for a person to ask for a run.
MODE_MANUAL = "manual"

#: The mode of a policy that processes the work as it arrives.
MODE_AUTOMATIC = "automatic"


def current_policy(session: Session) -> agent_ops.AgentProcessingPolicy | None:
    """Return the single seeded processing policy, if the demo has been reset."""
    return session.execute(
        select(agent_ops.AgentProcessingPolicy).order_by(agent_ops.AgentProcessingPolicy.created_at)
    ).scalars().first()


def processing_mode(session: Session) -> str:
    """Return the mode of the stored policy.

    A database without a policy is a manual one: nothing is processed
    automatically until the City says so.
    """
    policy = current_policy(session)
    return policy.mode if policy is not None else MODE_MANUAL


def automatic_processing(session: Session) -> bool:
    """Return whether the City processes the work automatically."""
    return processing_mode(session) == MODE_AUTOMATIC


__all__ = [
    "MODE_AUTOMATIC",
    "MODE_MANUAL",
    "automatic_processing",
    "current_policy",
    "processing_mode",
]

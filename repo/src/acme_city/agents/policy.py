"""Persisted processing-policy reads for the Agent Operator lane."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import agent_ops


def current_policy(session: Session) -> agent_ops.AgentProcessingPolicy | None:
    """Return the single seeded processing policy, if the demo has been reset."""
    return session.execute(
        select(agent_ops.AgentProcessingPolicy).order_by(agent_ops.AgentProcessingPolicy.created_at)
    ).scalars().first()


__all__ = ["current_policy"]

"""Read-only summary values for the Agent Operator home."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.control import AGENT_KEYS, agent_mode
from acme_city.agents.intake import waiting_applications
from acme_city.persistence.models import agent as agent_models


def operator_summary(session: Session) -> dict[str, object]:
    """Return only stored counts and agent states for the operational home."""
    runs = list(session.execute(select(agent_models.AgentRun)).scalars().all())
    states = [
        {
            "key": key,
            "label": "Intake agent" if key == "intake" else "Adjudication agent",
            "mode": agent_mode(session, key),
        }
        for key in AGENT_KEYS
    ]
    return {
        "waiting": len(waiting_applications(session)),
        "running": len([row for row in runs if row.finished_at is None]),
        "failed": len([row for row in runs if row.outcome == "failed"]),
        "retrying": 0,
        "states": states,
        "engine": "Built in logic",
    }


__all__ = ["operator_summary"]

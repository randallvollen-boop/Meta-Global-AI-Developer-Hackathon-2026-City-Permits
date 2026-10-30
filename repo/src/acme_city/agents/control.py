"""The awake/asleep control of the two agents.

An agent is asleep by default.  Only a persona with the ``agent.toggle``
grant (the City Administrator, the Agent Operator) may wake it or put it back
to sleep, and every change is a governed, audited action.  A run
of an agent is refused while the agent sleeps: the browser never decides that
an agent may act.
"""
# REQUIRES: PER-01, PER-04, SEC-02
# The wake/sleep state of each agent is server-side state, changed only by an
# authorized administrator and recorded in the audit trail.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import agent as agent_models

#: The two agents of the demonstration.
AGENT_KEYS: tuple[str, ...] = (agent_models.AGENT_INTAKE, agent_models.AGENT_ADJUDICATION)

#: The grant that wakes an agent and puts it back to sleep.
PERMISSION_TOGGLE = "agent.toggle"

#: The grant each agent needs to run.
#:
#: The ``linking`` key is the contract of the linking agent of the steward
#: automation: its grant is reserved and no persona holds it yet, and it is
#: not one of ``AGENT_KEYS``, so it can be neither woken nor run.
PERMISSION_RUN: dict[str, str] = {
    agent_models.AGENT_INTAKE: "agent.run.intake",
    agent_models.AGENT_ADJUDICATION: "agent.run.adjudication",
    "linking": "agent.run.linking",
}

#: The label of each agent, for the screen and the audit trail.
AGENT_LABELS: dict[str, str] = {
    agent_models.AGENT_INTAKE: "Intake agent",
    agent_models.AGENT_ADJUDICATION: "Adjudication agent",
}


def agent_mode(session: Session, agent_key: str) -> str:
    """Return the mode of one agent.

    An agent that has never been woken is asleep.  A missing control row is
    therefore an asleep agent, never an unknown state.
    """
    row = session.execute(
        select(agent_models.AgentControl).where(
            agent_models.AgentControl.agent_key == agent_key
        )
    ).scalar_one_or_none()
    if row is None:
        return agent_models.AGENT_ASLEEP
    return row.mode


def is_awake(session: Session, agent_key: str) -> bool:
    """Return whether one agent is awake."""
    return agent_mode(session, agent_key) == agent_models.AGENT_AWAKE


class AgentControlService:
    """Reads and changes the awake/asleep state of the agents."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    def state(self, agent_key: str) -> agent_models.AgentControl | None:
        """Return the control row of one agent, when one exists."""
        return self._session.execute(
            select(agent_models.AgentControl).where(
                agent_models.AgentControl.agent_key == agent_key
            )
        ).scalar_one_or_none()

    def ensure_defaults(self) -> None:
        """Create the control rows of both agents, asleep.

        The reset seeds these rows; this method makes sure a database that was
        created without the reset still has both agents asleep.
        """
        for agent_key in AGENT_KEYS:
            if self.state(agent_key) is not None:
                continue
            self._session.add(
                agent_models.AgentControl(
                    id=new_id("agentctl"),
                    correlation_id=new_id("corr"),
                    agent_key=agent_key,
                    mode=agent_models.AGENT_ASLEEP,
                    version=1,
                    changed_by=None,
                    changed_at=self._now,
                )
            )
        self._session.flush()

    def set_mode(
        self, agent_key: str, mode: str, actor: ActorContext
    ) -> agent_models.AgentControl:
        """Wake one agent or put it to sleep.

        The change is a governed action: it needs the ``agent.toggle`` grant,
        it is audited, and it never takes an authority from the request.
        """
        if agent_key not in AGENT_KEYS:
            raise ValidationError(f"unknown agent: {agent_key!r}")
        if mode not in (agent_models.AGENT_AWAKE, agent_models.AGENT_ASLEEP):
            raise ValidationError("an agent is either awake or asleep")
        self._permissions.authorize(
            actor,
            PERMISSION_TOGGLE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        self.ensure_defaults()
        row = self.state(agent_key)
        assert row is not None  # ensure_defaults always creates both rows
        before = row.mode
        row.mode = mode
        row.version += 1
        row.changed_by = actor.actor_id
        row.changed_at = self._now
        self._session.flush()
        label = AGENT_LABELS[agent_key]
        verb = "awakened" if mode == agent_models.AGENT_AWAKE else "put to sleep"
        self._audit.append(
            action="agent.toggle",
            actor=actor,
            target_type="agent_control",
            target_id=row.id,
            before_version=row.version - 1,
            after_version=row.version,
            reason=f"{label} {verb}",
            metadata={"agent_key": agent_key, "before": before, "after": mode},
        )
        return row

    def require_awake(self, agent_key: str) -> None:
        """Refuse to run an agent that is asleep."""
        mode = agent_mode(self._session, agent_key)
        if mode != agent_models.AGENT_AWAKE:
            label = AGENT_LABELS.get(agent_key, agent_key)
            raise ValidationError(
                f"the {label.lower()} is asleep; wake it first"
            )

    def authorize_run(self, actor: ActorContext, agent_key: str) -> None:
        """Refuse a run the acting persona may not perform."""
        permission = PERMISSION_RUN.get(agent_key) if agent_key in AGENT_KEYS else None
        if permission is None:
            raise ValidationError(f"unknown agent: {agent_key!r}")
        self._permissions.authorize(
            actor,
            permission,
            ResourceContext(domain_id="permits", record_ids=()),
        )

    def authorize_manual_run(self, actor: ActorContext, agent_key: str) -> None:
        """Refuse a manual run that may not start.

        A manual run needs the grant of the agent and an awake agent.  Both
        checks live here, so every entry point enforces them the same way.
        """
        self.authorize_run(actor, agent_key)
        self.require_awake(agent_key)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return the state of both agents, for the screens and the sidebar."""
        rows: list[dict[str, Any]] = []
        for agent_key in AGENT_KEYS:
            row = self.state(agent_key)
            rows.append(
                {
                    "agent_key": agent_key,
                    "label": AGENT_LABELS[agent_key],
                    "mode": row.mode if row is not None else agent_models.AGENT_ASLEEP,
                    "version": row.version if row is not None else 0,
                    "changed_by": row.changed_by if row is not None else None,
                    "changed_at": row.changed_at if row is not None else None,
                }
            )
        return rows


def authorize_processing(session: Session, actor: ActorContext) -> None:
    """Refuse a bulk processing request that may not start.

    Processing a selection of waiting cases runs the intake agent on them, so
    the person who may run the intake agent is the person who may process the
    selection, and the agent must be awake.  The check lives here, at the
    shared execution boundary, so every entry point enforces it the same way.
    """
    AgentControlService(session).authorize_manual_run(actor, agent_models.AGENT_INTAKE)


__all__ = [
    "AGENT_KEYS",
    "AGENT_LABELS",
    "PERMISSION_RUN",
    "PERMISSION_TOGGLE",
    "AgentControlService",
    "agent_mode",
    "authorize_processing",
    "is_awake",
]

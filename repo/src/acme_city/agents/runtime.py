"""The durable work queue of the agents.

The runtime is the one place where agent work is recorded.  The queue row is
the authority: a worker takes a piece of work by moving it from ``pending``
to ``running`` in a single statement, and only the worker that won that
statement may finish it.  There is no lease and no fencing token.  The
status column and the attempt count are the whole protocol.

The runtime does not run anything by itself.  It records what may be worked,
what is being worked and what was finished, so that the operator screens and
a later worker agree on the state of the work.
"""
# REQUIRES: PER-01, PER-04
# The queue is durable, one piece of work has one identity, and two workers
# never commit the same work.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit


def work_key(application: permit.Application, agent_key: str) -> str:
    """Return the identity of one piece of work.

    The identity names the agent, the case and the revision of the case, so
    the same case at a later revision is a different piece of work.
    """
    return f"{agent_key}:{application.id}:r{application.revision}"


class AgentRuntime:
    """The queue of the agent work."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()

    # ------------------------------------------------------------------ queue

    def enqueue(
        self, application: permit.Application, *, agent_key: str = agent_models.AGENT_INTAKE
    ) -> agent_ops.AgentWorkQueue:
        """Record one piece of work.

        The work key makes this idempotent: the same work is never queued
        twice, and the recorded row is returned.
        """
        key = work_key(application, agent_key)
        existing = self._session.execute(
            select(agent_ops.AgentWorkQueue).where(agent_ops.AgentWorkQueue.work_key == key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = agent_ops.AgentWorkQueue(
            id=new_id("queue"),
            correlation_id=application.correlation_id or new_id("corr"),
            work_key=key,
            application_id=application.id,
            agent_key=agent_key,
            status=agent_ops.WORK_PENDING,
            attempts=0,
            version=1,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def pending(self) -> list[agent_ops.AgentWorkQueue]:
        """Return the waiting work, oldest first."""
        rows = self._session.execute(
            select(agent_ops.AgentWorkQueue)
            .where(agent_ops.AgentWorkQueue.status == agent_ops.WORK_PENDING)
            .order_by(agent_ops.AgentWorkQueue.created_at, agent_ops.AgentWorkQueue.id)
        ).scalars().all()
        return list(rows)

    def claim(self, work_id: str) -> agent_ops.AgentWorkQueue | None:
        """Take one piece of work.

        The statement moves the row from ``pending`` to ``running`` and counts
        the attempt.  Two workers that ask for the same work at the same time
        cannot both win it: the second statement changes no row and the claim
        is refused.
        """
        result = self._session.execute(
            update(agent_ops.AgentWorkQueue)
            .where(
                agent_ops.AgentWorkQueue.id == work_id,
                agent_ops.AgentWorkQueue.status == agent_ops.WORK_PENDING,
            )
            .values(
                status=agent_ops.WORK_RUNNING,
                attempts=agent_ops.AgentWorkQueue.attempts + 1,
                claimed_at=self._now,
                finished_at=None,
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        if result.rowcount == 0:
            return None
        return self._session.get(agent_ops.AgentWorkQueue, work_id, populate_existing=True)

    def finish(
        self, work_id: str, status: str, *, note: str | None = None
    ) -> agent_ops.AgentWorkQueue | None:
        """Record the outcome of one piece of work.

        Only the worker that holds the work may finish it: the row has to be
        ``running``.  A second worker that tries to commit the same work
        changes no row and the finish is refused.
        """
        if status not in (
            agent_ops.WORK_COMPLETED,
            agent_ops.WORK_FAILED,
            agent_ops.WORK_HELD,
        ):
            raise ValueError(f"not a finished state: {status!r}")
        result = self._session.execute(
            update(agent_ops.AgentWorkQueue)
            .where(
                agent_ops.AgentWorkQueue.id == work_id,
                agent_ops.AgentWorkQueue.status == agent_ops.WORK_RUNNING,
            )
            .values(
                status=status,
                finished_at=self._now,
                note=note,
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        if result.rowcount == 0:
            return None
        return self._session.get(agent_ops.AgentWorkQueue, work_id, populate_existing=True)

    def counts(self) -> dict[str, int]:
        """Return how many pieces of work hold each status.

        ``retrying`` counts the waiting work that was already tried once: it
        is the work that waits for another attempt.
        """
        rows = self._session.execute(
            select(agent_ops.AgentWorkQueue.status, agent_ops.AgentWorkQueue.attempts)
        ).all()
        counts = {
            agent_ops.WORK_PENDING: 0,
            agent_ops.WORK_RUNNING: 0,
            agent_ops.WORK_COMPLETED: 0,
            agent_ops.WORK_FAILED: 0,
            agent_ops.WORK_HELD: 0,
        }
        retrying = 0
        for status, attempts in rows:
            counts[status] = counts.get(status, 0) + 1
            if status == agent_ops.WORK_PENDING and attempts > 0:
                retrying += 1
        counts["retrying"] = retrying
        return counts


def queue_counts(session: Session) -> dict[str, int]:
    """Return the queue counts of a session."""
    return AgentRuntime(session).counts()


__all__ = ["AgentRuntime", "queue_counts", "work_key"]

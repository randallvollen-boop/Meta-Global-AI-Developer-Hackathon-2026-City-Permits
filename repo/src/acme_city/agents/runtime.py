"""The durable work queue of the agents.

The runtime is the one place where agent work is recorded and where an agent
is run.  The queue row is the authority: a worker takes a piece of work by
moving it from ``pending`` to ``running`` in a single statement, and only the
worker that won that statement may finish it.  There is no lease and no
fencing token.  The status column and the attempt count are the whole
protocol, and a finish names the attempt it ends, so a late finish of an
earlier attempt is refused.

The runtime records what may be worked, what is being worked and what was
finished, so that the operator screens and a later worker agree on the state
of the work.  A manual run goes through the same queue: the work is queued,
taken, run and finished, so the queue row records the attempt and its
outcome.

A manual run is bounded twice: by the batch size of the stored processing
policy and by the runs the hour still allows.  A manual run uses the built in
deterministic logic: it never calls the model provider.  A controlled case of
the demonstration is never worked, and a run of a sleeping agent is refused
before any work is queued.
"""
# REQUIRES: PER-01, PER-04
# The queue is durable, one piece of work has one identity, two workers
# never commit the same work, and a manual run stays inside the bounds of
# the stored policy.

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from acme_city.agents.policy import current_policy
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit

#: The batch size and the hourly limit used when no policy was seeded.
DEFAULT_MAX_BATCH_SIZE = 20
DEFAULT_RUNS_PER_HOUR = 60

#: The engine of an attempt: the deterministic logic of the City.  The agents
#: read the received documents and evaluate the published rules without a
#: provider call, so every attempt names this engine.
BUILTIN_ENGINE = "builtin"

#: The label the operator screens show for the built in logic.
BUILTIN_ENGINE_LABEL = "Built in logic"

#: The outcomes of a run that finished the work of the case.
_COMPLETED_OUTCOMES = frozenset({"completed", "recommended"})


def work_key(application: permit.Application, agent_key: str) -> str:
    """Return the identity of one piece of work.

    The identity names the agent, the case and the revision of the case, so
    the same case at a later revision is a different piece of work.
    """
    return f"{agent_key}:{application.id}:r{application.revision}"


@dataclass(frozen=True)
class BatchLimit:
    """The bounds of one manual batch of agent work."""

    #: The most cases one batch may name.
    max_batch_size: int
    #: The most runs one hour may hold.
    runs_per_hour: int
    #: The runs the agents already started in this hour.
    runs_this_hour: int

    @property
    def remaining_runs(self) -> int:
        """Return how many runs the hour still allows."""
        return max(0, self.runs_per_hour - self.runs_this_hour)


@dataclass(frozen=True)
class QueuedRun:
    """One run of an agent, recorded in the work queue."""

    application_id: str
    work_id: str
    run_id: str
    outcome: str
    status: str
    attempts: int


def batch_limit(session: Session, *, now: datetime | None = None) -> BatchLimit:
    """Return the bounds of one manual batch.

    The bounds come from the stored processing policy.  The hourly limit
    counts the runs the agents started in the last hour, so an hour that is
    used up is refused instead of running without a limit.
    """
    policy = current_policy(session)
    max_batch = (
        int(policy.max_batch_size) if policy is not None else DEFAULT_MAX_BATCH_SIZE
    )
    per_hour = int(policy.runs_per_hour) if policy is not None else DEFAULT_RUNS_PER_HOUR
    since = (now or utc_now()) - timedelta(hours=1)
    runs = session.execute(
        select(func.count())
        .select_from(agent_models.AgentRun)
        .where(agent_models.AgentRun.started_at >= since)
    ).scalar_one()
    return BatchLimit(max_batch, per_hour, int(runs))


def work_status_for(outcome: str) -> str:
    """Return the queue status of a finished run.

    A run that produced a result finished the work.  A run that needs a
    person is held, and only a technical failure is failed.
    """
    if outcome == "failed":
        return agent_ops.WORK_FAILED
    if outcome in _COMPLETED_OUTCOMES:
        return agent_ops.WORK_COMPLETED
    return agent_ops.WORK_HELD


def require_hour_room(limit: BatchLimit) -> None:
    """Refuse a run in an hour that is used up.

    The limit of the City is a limit of the hour, so a run never starts when
    the hour holds no more room.
    """
    if limit.remaining_runs <= 0:
        raise ValidationError(
            f"the hourly limit of {limit.runs_per_hour} run(s) is used up; "
            "try again later"
        )


class AgentRuntime:
    """The queue of the agent work."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now

    def _clock(self) -> datetime:
        """Return the moment of this call.

        The clock is read when the work is taken and when it is finished, so
        the row carries the time of the attempt.  A test may pass its own
        moment instead.
        """
        return self._now if self._now is not None else utc_now()

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
                claimed_at=self._clock(),
                finished_at=None,
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        if result.rowcount == 0:
            return None
        return self._session.get(agent_ops.AgentWorkQueue, work_id, populate_existing=True)

    def finish(
        self, work_id: str, attempt: int, status: str, *, note: str | None = None
    ) -> agent_ops.AgentWorkQueue | None:
        """Record the outcome of one attempt of one piece of work.

        Only the worker that holds the work may finish it: the row has to be
        ``running`` and its attempt count has to be the attempt the worker
        holds.  A second worker that tries to commit the same work changes no
        row and the finish is refused, and so is the late finish of an
        attempt that already ended.
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
                agent_ops.AgentWorkQueue.attempts == attempt,
            )
            .values(
                status=status,
                finished_at=self._clock(),
                note=note,
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        if result.rowcount == 0:
            return None
        return self._session.get(agent_ops.AgentWorkQueue, work_id, populate_existing=True)

    def reopen(self, work_id: str) -> agent_ops.AgentWorkQueue | None:
        """Put a finished piece of work back to waiting.

        A person may run an agent on a case again.  The row opens for another
        attempt, and the attempt count keeps the history of the case.
        """
        result = self._session.execute(
            update(agent_ops.AgentWorkQueue)
            .where(
                agent_ops.AgentWorkQueue.id == work_id,
                agent_ops.AgentWorkQueue.status.in_(
                    [
                        agent_ops.WORK_COMPLETED,
                        agent_ops.WORK_FAILED,
                        agent_ops.WORK_HELD,
                    ]
                ),
            )
            .values(
                status=agent_ops.WORK_PENDING,
                claimed_at=None,
                finished_at=None,
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        if result.rowcount == 0:
            return None
        return self._session.get(agent_ops.AgentWorkQueue, work_id, populate_existing=True)

    def recover_running(self, before: datetime) -> int:
        """Return the work that was running before this moment to the waiting state.

        A process that ended while a case was being worked leaves its row
        running.  The next worker returns that work to the waiting state, so
        the case is worked again instead of waiting for ever.  Only the work
        that was claimed before the worker started is returned: the work of
        the worker that is running now is never touched.

        Returns:
            The number of pieces of work that were returned to the waiting
            state.
        """
        result = self._session.execute(
            update(agent_ops.AgentWorkQueue)
            .where(
                agent_ops.AgentWorkQueue.status == agent_ops.WORK_RUNNING,
                or_(
                    agent_ops.AgentWorkQueue.claimed_at.is_(None),
                    agent_ops.AgentWorkQueue.claimed_at < before,
                ),
            )
            .values(
                status=agent_ops.WORK_PENDING,
                claimed_at=None,
                finished_at=None,
                note="the attempt was interrupted; the work waits for another attempt",
                version=agent_ops.AgentWorkQueue.version + 1,
            )
        )
        return int(result.rowcount or 0)

    def execute(
        self,
        application: permit.Application,
        *,
        agent_key: str,
        runner: Callable[[str, str], agent_models.AgentRun],
    ) -> QueuedRun:
        """Run one agent on one case through the queue.

        The work is queued, taken and finished around the run, so the queue
        row records that the case was tried and how the attempt ended.  A
        case that was worked before is opened for another attempt.  A run
        that raises leaves the work failed and raises the error again.
        """
        queued = self.enqueue(application, agent_key=agent_key)
        work = self._session.get(
            agent_ops.AgentWorkQueue, queued.id, populate_existing=True
        )
        assert work is not None  # the row was just written or found
        if work.status in (
            agent_ops.WORK_COMPLETED,
            agent_ops.WORK_FAILED,
            agent_ops.WORK_HELD,
        ):
            reopened = self.reopen(work.id)
            if reopened is not None:
                work = reopened
        claimed = self.claim(work.id)
        if claimed is None:
            raise ValidationError("another run is already working this case")
        try:
            run = runner(application.id, claimed.id)
        except Exception as error:  # noqa: BLE001 - the failure is recorded
            self.finish(
                claimed.id,
                claimed.attempts,
                agent_ops.WORK_FAILED,
                note=f"the run failed: {error}",
            )
            raise
        self._record_engine(run)
        status = work_status_for(run.outcome)
        self.finish(
            claimed.id, claimed.attempts, status, note=f"the run ended: {run.outcome}"
        )
        return QueuedRun(
            application_id=application.id,
            work_id=claimed.id,
            run_id=run.id,
            outcome=run.outcome,
            status=status,
            attempts=claimed.attempts,
        )

    def _record_engine(self, run: agent_models.AgentRun) -> None:
        """Record the engine of the attempt on the run evidence.

        The run names the engine that produced it, so the operator screens
        read the engine instead of guessing it from the case.
        """
        inputs = dict(run.inputs or {})
        inputs["engine"] = BUILTIN_ENGINE
        run.inputs = inputs

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


def run_agent(
    session: Session,
    *,
    application: permit.Application,
    agent_key: str,
    triggered_by: str,
    settings: Any = None,
    now: datetime | None = None,
    require_awake: bool = True,
) -> QueuedRun:
    """Run one agent on one case through the durable work queue.

    The agent is named by its key, never by the request.  The run uses the
    built in deterministic logic, so it never calls the model provider.

    Two things are checked before any work is queued.  The case must not be a
    controlled case of the demonstration: a case that carries a scenario id is
    the fixed fixture of the demonstration, not an arrival, and it is never
    worked.  The agent must be awake: a sleeping agent waits for its cases
    instead of leaving a failed piece of work behind.

    The automatic worker passes ``require_awake=False``: the processing
    policy of the City is the authority of that run, not the manual wake
    state of the agent.
    """
    from acme_city.agents.adjudication import AdjudicationAgent
    from acme_city.agents.control import AgentControlService
    from acme_city.agents.intake import IntakeAgent

    if application.scenario_id is not None:
        raise ValidationError(
            "this is a controlled demonstration case; agents do not run on it"
        )

    if agent_key == agent_models.AGENT_INTAKE:
        agent: Any = IntakeAgent(session, settings=settings, now=now)
    elif agent_key == agent_models.AGENT_ADJUDICATION:
        agent = AdjudicationAgent(session, settings=settings, now=now)
    else:
        raise ValidationError(f"unknown agent: {agent_key!r}")

    def runner(application_id: str, work_id: str) -> agent_models.AgentRun:
        return agent.run(
            application_id,
            triggered_by=triggered_by,
            work_id=work_id,
            require_awake=require_awake,
        )

    limit = batch_limit(session, now=now)
    require_hour_room(limit)
    if require_awake:
        AgentControlService(session, now=now).require_awake(agent_key)
    return AgentRuntime(session, now=now).execute(
        application, agent_key=agent_key, runner=runner
    )


def run_batch(
    session: Session,
    *,
    cases: Sequence[permit.Application],
    agent_key: str,
    triggered_by: str,
    settings: Any = None,
    now: datetime | None = None,
) -> tuple[QueuedRun, ...]:
    """Run one agent on the cases one manual batch may name.

    The batch is bounded by the batch size of the stored policy and by the
    runs the hour still allows.  The cases are the ones that waited when the
    request arrived: a case that arrives later waits for the next batch.  A
    controlled case of the demonstration is never named by a batch.
    """
    limit = batch_limit(session, now=now)
    require_hour_room(limit)
    eligible = [case for case in cases if case.scenario_id is None]
    chosen = eligible[: min(limit.max_batch_size, limit.remaining_runs)]
    return tuple(
        run_agent(
            session,
            application=application,
            agent_key=agent_key,
            triggered_by=triggered_by,
            settings=settings,
            now=now,
        )
        for application in chosen
    )


__all__ = [
    "BUILTIN_ENGINE",
    "BUILTIN_ENGINE_LABEL",
    "DEFAULT_MAX_BATCH_SIZE",
    "DEFAULT_RUNS_PER_HOUR",
    "AgentRuntime",
    "BatchLimit",
    "QueuedRun",
    "batch_limit",
    "queue_counts",
    "require_hour_room",
    "run_agent",
    "run_batch",
    "work_key",
    "work_status_for",
]

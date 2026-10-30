"""The one background loop that processes the eligible work.

The worker is the automatic half of the agents: it looks at the work that
waits, takes it and runs the built in logic of the City on it.  There is one
loop and one thread.  The durable work queue is the authority, so the loop
keeps no state of its own beyond the case it is working on.

The worker runs only when the deployment allows it
(``ACME_AGENT_WORKER_ENABLED``) and it only works when the processing policy
of the City is automatic and the agent is awake.  It never calls the model
provider: every run uses the built in deterministic logic, so a hosted
demonstration sends no request at all.

The loop stops cleanly.  The stop event ends the wait between two cycles,
the thread joins, and the service leaves nothing behind.
"""
# REQUIRES: PER-01, PER-04
# Automatic work is bounded by the policy of the City, it never touches the
# controlled fixture of the demonstration and it never calls the provider.

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from acme_city.agents.control import is_awake
from acme_city.agents.eligibility import eligible_applications
from acme_city.agents.policy import automatic_processing
from acme_city.agents.runtime import (
    AgentRunFailed,
    AgentRuntime,
    batch_limit,
    run_agent,
    work_key,
)
from acme_city.core.errors import ValidationError
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit
from acme_city.persistence.session import SessionFactory, transaction

logger = logging.getLogger("acme_city")

#: The seconds the loop waits between two cycles.
WORKER_INTERVAL_SECONDS = 2.0

#: The name the automatic runs are recorded under.
WORKER_ACTOR_ID = "service_agent_worker"

#: The label the screens show for the automatic runs.
WORKER_ACTOR_LABEL = "Automatic processing"


class AgentWorker:
    """The background loop that processes the eligible work.

    The worker takes the waiting work from the durable queue, runs the
    intake agent on it with the built in logic of the City and records the
    outcome.  Every case is worked in its own transaction, so a case that
    fails never undoes the cases that worked.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        settings: Any = None,
        now: datetime | None = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._now = now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        """Return whether the loop is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the loop.  Starting a running worker changes nothing."""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="acme-agent-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop and wait for the thread to end."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout)

    def _loop(self) -> None:
        """Run one cycle at a time until the worker is stopped."""
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:  # noqa: BLE001 - a failed cycle must not end the loop
                logger.exception("the automatic processing cycle failed")
            self._stop.wait(WORKER_INTERVAL_SECONDS)

    # ----------------------------------------------------------------- cycle

    def run_cycle(self) -> int:
        """Process the eligible work once and return the number of runs.

        The cycle does two things: it records the eligible cases that
        arrived as work, and it works the cases the hour still allows.

        Two gates come first.  While the policy of the City is manual the
        cycle does nothing at all, so the work waits for a person.  A
        sleeping agent is not worked either: the operator wakes the agent
        when the City wants the work done on its own.
        """
        with transaction(self._factory) as session:
            if not automatic_processing(session):
                return 0
            if not is_awake(session, agent_models.AGENT_INTAKE):
                return 0
            work = self._schedule(session)
        count = 0
        for work_id in work:
            if self._stop.is_set():
                break
            count += self._work(work_id)
        return count

    def _schedule(self, session) -> list[str]:
        """Record the eligible cases as work and return the ids of the work.

        Only the work of the current revision of a case is worked.  A case
        that was answered again after its work was queued has a new piece of
        work beside the old one, and the old one waits.
        """
        runtime = AgentRuntime(session, now=self._now)
        for case in eligible_applications(session):
            runtime.enqueue(case, agent_key=agent_models.AGENT_INTAKE)
        limit = batch_limit(session, now=self._now)
        room = min(limit.max_batch_size, limit.remaining_runs)
        chosen: list[str] = []
        for row in runtime.pending():
            if len(chosen) >= room:
                break
            application = session.get(permit.Application, row.application_id)
            if application is None:
                continue
            if row.work_key != work_key(application, agent_models.AGENT_INTAKE):
                continue
            chosen.append(row.id)
        return chosen

    def _work(self, work_id: str) -> int:
        """Run the intake agent on one piece of work and return 1 when it worked.

        The work is only done when it still waits for an attempt.  A person
        may have worked the case in the meantime, and then the work is
        finished and the worker leaves it alone: a case is never worked
        twice.
        """
        try:
            with transaction(self._factory) as session:
                work = session.get(agent_ops.AgentWorkQueue, work_id)
                if work is None or work.status != agent_ops.WORK_PENDING:
                    return 0
                application = session.get(permit.Application, work.application_id)
                if application is None:
                    return 0
                try:
                    run_agent(
                        session,
                        application=application,
                        agent_key=agent_models.AGENT_INTAKE,
                        triggered_by=WORKER_ACTOR_ID,
                        settings=self._settings,
                        now=self._now,
                        work_id=work.id,
                    )
                except AgentRunFailed:
                    # The failure is recorded on the queue row of the work, so
                    # the transaction keeps it and a person sees it.
                    return 0
                except ValidationError:
                    # The work was taken by a person or by another worker, or
                    # the hour has no room left.  The work stays as it is.
                    return 0
        except Exception:  # noqa: BLE001 - the failure is recorded by the runtime
            logger.warning(
                "the automatic run failed for the work %s", work_id, exc_info=True
            )
            return 0
        return 1


def worker_enabled(settings: Any) -> bool:
    """Return whether the deployment allows the background worker to run."""
    return bool(getattr(settings, "agent_worker_enabled", False))


__all__ = [
    "WORKER_ACTOR_ID",
    "WORKER_ACTOR_LABEL",
    "WORKER_INTERVAL_SECONDS",
    "AgentWorker",
    "worker_enabled",
]

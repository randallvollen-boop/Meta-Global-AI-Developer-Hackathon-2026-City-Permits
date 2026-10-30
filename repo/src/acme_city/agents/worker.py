"""The one background loop that processes the eligible work.

The worker is the automatic half of the agents: it looks at the work that
waits, takes it and runs the built in logic of the City on it.  There is one
loop and one thread.  The durable work queue is the authority, so the loop
keeps no state of its own beyond the case it is working on.

The worker runs only when the deployment allows it
(``ACME_AGENT_WORKER_ENABLED``) and it only works when the processing policy
of the City is automatic.  It never calls the model provider: every run uses
the built in deterministic logic, so a hosted demonstration sends no request
at all.

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

from acme_city.agents.eligibility import eligible_applications
from acme_city.agents.policy import automatic_processing
from acme_city.agents.runtime import AgentRuntime, batch_limit, run_agent
from acme_city.core.clock import utc_now
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit
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
        #: The moment the worker started.  The work that was running before
        #: this moment belongs to a process that is gone.
        self.started_at = now or utc_now()

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

        The cycle does three things: it returns the work that an earlier
        process left running to the waiting state, it records the eligible
        cases that arrived as work, and it works the cases the hour still
        allows.

        The policy of the City is read first: while the policy is manual the
        cycle does nothing at all, so the work waits for a person.
        """
        with transaction(self._factory) as session:
            if not automatic_processing(session):
                return 0
            AgentRuntime(session, now=self._now).recover_running(self.started_at)
            work = self._schedule(session)
        count = 0
        for application_id in work:
            if self._stop.is_set():
                break
            count += self._work(application_id)
        return count

    def _schedule(self, session) -> list[str]:
        """Record the eligible cases as work and return the ids to work."""
        runtime = AgentRuntime(session, now=self._now)
        for case in eligible_applications(session):
            runtime.enqueue(case, agent_key=agent_models.AGENT_INTAKE)
        limit = batch_limit(session, now=self._now)
        room = min(limit.max_batch_size, limit.remaining_runs)
        return [row.application_id for row in runtime.pending()[:room]]

    def _work(self, application_id: str) -> int:
        """Run the intake agent on one case and return 1 when it worked."""
        try:
            with transaction(self._factory) as session:
                application = session.get(permit.Application, application_id)
                if application is None:
                    return 0
                run_agent(
                    session,
                    application=application,
                    agent_key=agent_models.AGENT_INTAKE,
                    triggered_by=WORKER_ACTOR_ID,
                    settings=self._settings,
                    now=self._now,
                    require_awake=False,
                )
        except Exception:  # noqa: BLE001 - the failure is recorded by the runtime
            logger.warning(
                "the automatic run failed for the case %s", application_id, exc_info=True
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

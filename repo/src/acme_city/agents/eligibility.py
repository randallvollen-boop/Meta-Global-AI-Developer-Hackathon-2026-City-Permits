"""Which cases the agents may work on their own.

The eligibility query is the one place that decides what may enter the work
queue without a person asking for it.  A case is eligible when it waits for
the intake agent, carries no controlled scenario and was never worked
before.

The controlled data of the demonstration is never eligible:

* the D01-D11 cases of the demonstration carry a scenario id, so they are
  the fixed fixture and not an arrival;
* the cases of the acceptance tests are worked by their own test, so they
  are history;
* the DF-1 and DF-2 fence scenarios are data, not cases: they are read by
  the rule evaluator and never reach the queue.

A case that was worked before is history: a person runs it again, and it is
never picked up on its own.  A person may also run an agent on any named
case.  This query only governs the work that starts on its own.
"""
# REQUIRES: PER-01, PER-04
# Automatic work never touches the controlled fixture, and only a case that
# still waits and was never worked may be picked up.

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, permit


def eligible_applications(session: Session) -> list[permit.Application]:
    """Return the cases the agents may still work.

    A case is eligible when it is submitted, carries no controlled scenario,
    has no recorded run and is not in the queue already.
    """
    worked = select(agent_models.AgentRun.application_id).where(
        agent_models.AgentRun.application_id.is_not(None)
    )
    queued = select(agent_ops.AgentWorkQueue.application_id)
    rows = session.execute(
        select(permit.Application)
        .where(
            permit.Application.status == "submitted",
            permit.Application.scenario_id.is_(None),
            permit.Application.id.not_in(worked),
            permit.Application.id.not_in(queued),
        )
        .order_by(permit.Application.source_application_number)
    ).scalars().all()
    return list(rows)


__all__ = ["eligible_applications"]

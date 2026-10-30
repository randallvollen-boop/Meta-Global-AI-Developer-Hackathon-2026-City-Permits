"""The automatic linking demonstration (a prepare mode, never a fixture).

The default reset holds no applied link: a steward decides every link.  For
the demonstration of the automatic linking this module activates a policy,
queues the accepted applicant records and runs the worker of the City once.
The queue of the Data Steward then holds one link that the linking service
applied, and a person may keep it or take it back with a reason.

The module is called only by ``scripts/load_steward_demo.py --automation``
(and by the ``steward-automation`` prepare mode), never by a reset, an
acceptance run or a D-scenario fixture.  The Cedarline demonstration is not
altered by it.
"""
# REQUIRES: MDM-02, SEC-01

from __future__ import annotations

from sqlalchemy.orm import Session

from acme_city.agents import linking
from acme_city.auth.context import ActorContext
from acme_city.registry import automation
from acme_city.registry.provenance import current_accepted_snapshot

#: The source records the demonstration queues, in the order they are queued.
AUTOMATION_RECORDS: tuple[tuple[str, str, str], ...] = (
    ("permitting", "applicant_profiles", "PER-AP-0001"),
)

#: The datasets the demonstration policy covers.
AUTOMATION_SCOPES: tuple[str, ...] = ("applicant_profiles",)

#: The reason the demonstration records for the policy.
AUTOMATION_REASON = "The demonstration shows one link the service applied."

#: The Data Steward, the person who authorizes the automation.
STEWARD = ActorContext(
    actor_id="persona_data_steward",
    role_ids=frozenset({"domain_steward"}),
)


def seed_automation(session: Session) -> list[str]:
    """Activate the policy, queue the records and apply the eligible links.

    The links are applied by the worker of the City, exactly as the service
    applies them in a running city.  A person keeps or undoes every one of
    them afterwards.

    Returns:
        The identifiers of the jobs the worker processed.
    """
    automation.activate_policy(
        session,
        STEWARD,
        mode="active",
        source_scopes=list(AUTOMATION_SCOPES),
        reason=AUTOMATION_REASON,
        expected_version=automation.newest_policy_version(session),
    )
    for system_id, dataset_key, record_id in AUTOMATION_RECORDS:
        snapshot = current_accepted_snapshot(session, system_id, dataset_key, record_id)
        if snapshot is None:
            continue
        automation.enqueue_accepted_snapshot(
            session,
            snapshot,
            dataset_key=dataset_key,
            automation_mode="active",
        )
    report = linking.run_once(session)
    return [outcome.job_id for outcome in report.processed]


__all__ = [
    "AUTOMATION_REASON",
    "AUTOMATION_RECORDS",
    "AUTOMATION_SCOPES",
    "STEWARD",
    "seed_automation",
]

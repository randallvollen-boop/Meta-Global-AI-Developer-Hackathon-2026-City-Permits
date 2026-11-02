"""The steward assistant demonstration of the fictional ACME City.

The demonstration database holds the tasks of the Data Steward's queue that
the assistant can work on, one for each certainty it can reach:

* three record matches the assistant is sure of: the source names one master
  record and no other;
* one Cedarline record match the assistant is not sure of: the source fits
  two master records almost equally well;
* one issue whose two versions disagree, which no one but a person may
  settle.

The steward presses **Prepare recommendations** and the queue then shows the
three levels side by side, with the evidence each of them rests on.

Nothing here decides anything.  The links are proposed and the issue is
open, so the steward decides every one of them.

The module is called by ``scripts/reset_demo.py`` — the script that builds
the demonstration database — and by the tests of the lane.  It is never part
of ``reset_demo`` itself: the base fixture of the City stays exactly what
the protected snapshot of the seeded rows records.
"""
# REQUIRES: MDM-02, UX-01

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.governance.schemas import EscalateIssueCommand
from acme_city.governance.service import GovernanceService

#: The Data Steward, the person who decides every one of these tasks.
STEWARD = ActorContext(
    actor_id="persona_data_steward",
    role_ids=frozenset({"domain_steward"}),
)

#: The domain the issue of the demonstration belongs to.
CONFLICT_DOMAIN = "businesses"

#: The record the issue of the demonstration is about.  The field is the
#: postal address of the organization, which the source sent and the master
#: record does not hold.
CONFLICT_SUBJECT = "party_quarry:postal_address"

#: The kind of issue: two versions of the same record disagree.
CONFLICT_ISSUE_TYPE = "source_version_payload_conflict"

#: What the City recorded about the issue.
CONFLICT_DESCRIPTION = (
    "Two versions of the same business record were delivered with different "
    "content, so the City cannot tell which one is right."
)


def seed_steward_assistant_demo(session: Session, bundle: Any = None) -> dict[str, int]:
    """Seed the tasks of the steward assistant demonstration.

    The links are proposed and the issue is open.  Nothing is decided here:
    the steward reads the evidence and decides every one of them.

    Args:
        session: The open session.
        bundle: The fixture bundle, for the moment of the demo.

    Returns:
        The counts of the rows the seed wrote.
    """
    proposed = seed_cedarline(session)
    GovernanceService(session).escalate_issue(
        EscalateIssueCommand(
            domain_id=CONFLICT_DOMAIN,
            subject_type="canonical_entity",
            subject_id=CONFLICT_SUBJECT,
            issue_type=CONFLICT_ISSUE_TYPE,
            description=CONFLICT_DESCRIPTION,
            reason="the demonstration shows a conflict only a person may settle",
        ),
        STEWARD,
    )
    return {
        "steward_demo_proposals": len(proposed),
        "steward_demo_issues": 1,
    }


__all__ = [
    "CONFLICT_DESCRIPTION",
    "CONFLICT_DOMAIN",
    "CONFLICT_ISSUE_TYPE",
    "CONFLICT_SUBJECT",
    "STEWARD",
    "seed_steward_assistant_demo",
]

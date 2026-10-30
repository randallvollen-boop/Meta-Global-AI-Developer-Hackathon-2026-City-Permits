"""The Cedarline steward demonstration.

The Cedarline source records are compared with the master records, exactly as
the steward's "Propose candidate links" form does:

* ``PER-AP-0003`` (Permitting) names "Cedar Line Coffee Roasters", an alias of
  Cedarline Coffee Roasters LLC;
* ``ERP-BL-00412`` (ERP/Finance) is that organization's business license;
* ``ERP-BL-00413`` (ERP/Finance) is the license of the similarly named
  Cedarline Coffee Works LLC, a different license number and a different unit.

Nothing is decided here; the three proposals are evidence waiting for the
steward.  The assistant reaches two levels on them: it is sure of the first
two and not of the third.

The module is called by ``scripts/reset_demo.py`` (the script that builds the
demonstration database), by ``scripts/load_steward_demo.py`` and by the
``steward-demo`` prepare mode.  It is never called by an acceptance run or a
D-scenario fixture.

The seed is idempotent: a source record that already holds a proposal is
left alone, so preparing the demonstration twice proposes nothing twice.
"""
# REQUIRES: MDM-02, UX-01

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.persistence.models import registry, source
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

#: The source records the demonstration compares, in the order the steward meets them.
CEDARLINE_RECORDS: tuple[tuple[str, str, str], ...] = (
    ("permitting", "applicant_profiles", "PER-AP-0003"),
    ("erp_finance", "business_licensing_register", "ERP-BL-00412"),
    ("erp_finance", "business_licensing_register", "ERP-BL-00413"),
)

STEWARD = ActorContext(
    actor_id="persona_data_steward",
    role_ids=frozenset({"domain_steward"}),
)


def already_proposed(
    session: Session, system_id: str, dataset_key: str, record_id: str
) -> bool:
    """Whether a source record already holds a candidate link proposal."""
    row = session.execute(
        select(registry.MatchProposal.id)
        .join(
            source.SourceSnapshot,
            registry.MatchProposal.source_snapshot_id
            == source.SourceSnapshot.source_snapshot_id,
        )
        .where(
            source.SourceSnapshot.source_system_id == system_id,
            source.SourceSnapshot.source_dataset_id == dataset_key,
            source.SourceSnapshot.source_record_id == record_id,
        )
    ).first()
    return row is not None


def seed_cedarline(session: Session) -> list[str]:
    """Propose the Cedarline candidate links and return the proposal ids.

    A source record that already holds a proposal is left alone, so the
    demonstration may be prepared more than once.
    """
    service = RegistryService(session)
    proposals = []
    for system_id, dataset_key, record_id in CEDARLINE_RECORDS:
        if already_proposed(session, system_id, dataset_key, record_id):
            continue
        view = service.propose(
            MatchProposalCommand(
                source_system_id=system_id,
                dataset_key=dataset_key,
                source_record_id=record_id,
            ),
            STEWARD,
        )
        proposals.append(view.proposal_id)
    return proposals

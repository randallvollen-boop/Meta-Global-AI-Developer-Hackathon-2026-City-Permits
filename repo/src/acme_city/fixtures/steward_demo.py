"""The Cedarline steward demonstration (a prepare mode, never a fixture).

The default reset holds no steward issue: a steward starts by comparing a
source record.  For the demonstration video this module asks the registry to
compare three Cedarline source records with the master records, exactly as the
steward's "Propose candidate links" form does:

* ``PER-AP-0003`` (Permitting) names "Cedar Line Coffee Roasters", an alias of
  Cedarline Coffee Roasters LLC;
* ``ERP-BL-00412`` (ERP/Finance) is that organization's business license;
* ``ERP-BL-00413`` (ERP/Finance) is the license of the similarly named
  Cedarline Coffee Works LLC, a different license number and a different unit.

Nothing is decided here; the three proposals are evidence waiting for the
steward.  The module is called only by ``scripts/load_steward_demo.py`` (and
the ``steward-demo`` prepare mode), never by a reset, an acceptance run or a
D-scenario fixture.
"""
# REQUIRES: MDM-02, UX-01

from __future__ import annotations

from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
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


def seed_cedarline(session: Session) -> list[str]:
    """Propose the Cedarline candidate links and return the proposal ids."""
    service = RegistryService(session)
    proposals = []
    for system_id, dataset_key, record_id in CEDARLINE_RECORDS:
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

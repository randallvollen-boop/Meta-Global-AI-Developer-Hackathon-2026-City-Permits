"""The registry-MDM domain.

The registry owns canonical identities, the source crosswalks, the match
proposals and the provenance of a displayed value.  It never owns a source
fact: the permitting, GIS and ERP/Finance sources remain authoritative for the
facts they declared.
"""
# REQUIRES: MDM-01, MDM-02, MDM-03, MDM-04, MDM-05
# Canonical identities, evidence-based proposals, steward decisions, trusted
# views and reversible link corrections are implemented in this package.

from acme_city.registry.schemas import (
    CrosswalkView,
    MatchDecisionCommand,
    MatchEvidenceView,
    MatchProposalCommand,
    MatchProposalView,
    TrustedFieldView,
    TrustedView,
)

__all__ = [
    "CrosswalkView",
    "MatchDecisionCommand",
    "MatchEvidenceView",
    "MatchProposalCommand",
    "MatchProposalView",
    "TrustedFieldView",
    "TrustedView",
]

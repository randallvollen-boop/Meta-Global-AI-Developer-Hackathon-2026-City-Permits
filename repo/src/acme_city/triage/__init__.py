"""The shared recommendation helpers (see :mod:`acme_city.triage.service`).

The two people-driven agents live in :mod:`acme_city.agents`.  This package
keeps the explanation helpers they share.
"""

from acme_city.triage.service import (
    build_rationale,
    current_recommendation,
    list_steps,
    recommendation_outcome,
)

__all__ = [
    "build_rationale",
    "current_recommendation",
    "list_steps",
    "recommendation_outcome",
]

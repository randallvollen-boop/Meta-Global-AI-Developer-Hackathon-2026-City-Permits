"""The navigation grouping of the Data Steward.  Owned by the steward lane.

Parity phase 3b added the intake queue and the early-resolution board after
the existing entries, both behind a grant only this persona holds.

Steward restyle (changed deliberately): the Data Steward holds Master records,
where People & organizations is a tab, so "applicants" is not listed.  Source
records and Activity follow Data issues; both are read-only screens behind the
steward's own read grants.

The agent screens are listed in ``agent_grants.py``, never here.
"""

from __future__ import annotations

ACTOR_ID = "persona_data_steward"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = (
    "queue",
    "masters",
    "permit",
    "steward",
    "source_records",
    "activity",
    "rules",
    "intake_queue",
    "early_resolution",
)

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()

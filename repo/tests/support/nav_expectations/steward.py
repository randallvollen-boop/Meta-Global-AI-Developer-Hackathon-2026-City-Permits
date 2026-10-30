"""The navigation grouping of the Data Steward.  Owned by the steward lane.

The Data Steward works in four places, and those four are the primary
navigation: its own work queue (``steward``), the master records, the source
records and the activity.  Every other screen it may open stays reachable
under More tools.

The agent screens are listed in ``agent_grants.py``, never here.
"""

from __future__ import annotations

ACTOR_ID = "persona_data_steward"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = (
    "steward",
    "masters",
    "source_records",
    "activity",
)

#: The screens under More tools.
SECONDARY: tuple[str, ...] = (
    "queue",
    "permit",
    "rules",
    "intake_queue",
    "early_resolution",
    # STW-19 grants the Data Steward the preview of the automation, so the
    # settings of the automatic linking are reachable under More tools.
    "steward_automation",
)

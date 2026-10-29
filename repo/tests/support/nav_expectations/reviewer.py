"""The navigation grouping of the Permit Reviewer.

Frozen: no slice changes the Permit Reviewer.  Parity phase 3b added the
review queue after the existing entries.  The agent screens are listed in
``agent_grants.py``, never here.
"""

from __future__ import annotations

ACTOR_ID = "persona_permit_reviewer"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = ("queue", "applicants", "permit", "review_queue")

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()

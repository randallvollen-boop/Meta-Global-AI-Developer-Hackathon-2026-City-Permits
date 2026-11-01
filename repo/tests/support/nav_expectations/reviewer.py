"""The navigation grouping of the Permit Reviewer.

The Permit Reviewer works in three places: the work queue, the permit
workspace and the review queue.  People & organizations and the Intake queue
stay open to the reviewer, but no reviewer task uses them, so they are not
listed.

The agent screens are listed in ``agent_grants.py``, never here.
"""

from __future__ import annotations

ACTOR_ID = "persona_permit_reviewer"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = ("queue", "permit", "review_queue")

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()

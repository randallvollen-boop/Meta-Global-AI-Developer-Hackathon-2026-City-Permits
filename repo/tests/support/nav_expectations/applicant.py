"""The navigation grouping of the Applicant.

Frozen: no slice changes the Applicant.  The agent screens of every persona
are listed in ``agent_grants.py``, never here.
"""

from __future__ import annotations

ACTOR_ID = "persona_applicant"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = ("queue", "applicants", "permit")

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()

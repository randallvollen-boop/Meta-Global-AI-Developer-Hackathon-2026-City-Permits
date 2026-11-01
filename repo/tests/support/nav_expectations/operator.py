"""The navigation grouping of the Agent Operator.  Owned by the operator lane.

The operator holds the agent operations bundle (``agents/bundle.py``).  Its
own screens are the four agent screens, listed in ``agent_grants.py``.  The
intake queue is its fifth screen: it holds the grant that runs a selected
batch, so the queue that lists the cases is under More tools.
"""

from __future__ import annotations

ACTOR_ID = "persona_agent_operator"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = ()

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ("intake_queue",)

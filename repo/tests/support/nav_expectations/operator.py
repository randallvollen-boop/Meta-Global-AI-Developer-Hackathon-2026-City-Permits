"""The navigation grouping of the Agent Operator.  Owned by the operator lane.

The operator holds the agent operations bundle (``agents/bundle.py``).  Its
only screen outside the agent screens is the intake queue, opened by
permit.intake.process_selected.  The agent screens it may open are listed in
``agent_grants.py``.
"""

from __future__ import annotations

ACTOR_ID = "persona_agent_operator"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = ()

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()

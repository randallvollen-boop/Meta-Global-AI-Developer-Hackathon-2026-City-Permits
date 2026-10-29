"""The agent screens each persona may open.  Owned by the agent operator lane.

All agent-screen authorization of every persona lives here, so the operator
lane changes who opens an agent screen without editing another persona's
module.  An agent screen is placed in a persona's group at its canonical
``SCREENS`` position (see ``__init__.py``).

The intake queue is not an agent screen: it is the Data Steward's own screen
and stays in ``steward.py``.  The Agent Operator opens it with the execution
grant that lets it process the selected cases, and that grant is not a menu
entry of its own.
"""

from __future__ import annotations

#: The screens that count as agent screens.  A persona module never lists one.
AGENT_SCREENS: frozenset[str] = frozenset(
    {"agent_intake", "agent_adjudication", "agents_home", "agent_runs", "agent_case"}
)

#: The agent screens of the side navigation, by actor id.
#:
#: The wake and run grants belong to the Agent Operator alone, so only the
#: Agent Operator opens the agent screens.
PRIMARY: dict[str, tuple[str, ...]] = {
    "persona_applicant": (),
    "persona_data_steward": (),
    "persona_permit_reviewer": (),
    "persona_city_administrator": (),
    "persona_agent_operator": ("agents_home", "agent_intake", "agent_adjudication", "agent_runs"),
}

#: The agent screens under More tools, by actor id.
SECONDARY: dict[str, tuple[str, ...]] = {}

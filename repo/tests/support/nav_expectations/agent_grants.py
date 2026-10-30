"""The agent screens each persona may open.  Owned by the agent operator lane.

All agent-screen authorization of every persona lives here, so the operator
lane changes who opens an agent screen without editing another persona's
module.  An agent screen is placed in a persona's group at its canonical
``SCREENS`` position; a persona whose module lists no screen of its own
takes the order given here (see ``__init__.py``).

The intake queue is not an agent screen: it is the Data Steward's own screen
and stays in ``steward.py``.  The Agent Operator opens it with the execution
grant that lets it process the selected cases, and that grant is not a menu
entry of its own: the queue is reached from the "Process selected cases" link
on the Agents home.
"""

from __future__ import annotations

#: The screens that count as agent screens.  A persona module never lists one.
AGENT_SCREENS: frozenset[str] = frozenset(
    {"agent_intake", "agent_adjudication", "agents_home", "agent_runs", "agent_case"}
)

#: The cross-persona grant-driven navigation entries, by actor id.
#:
#: The wake and run grants belong to the Agent Operator alone.  OPR-3 grants
#: the intake-queue read permission to the Permit Reviewer and City
#: Administrator, so their rendered navigation also includes that queue.
#: The order of the Agent Operator's list is the order of its four
#: destinations, with the operational summary as its home (OPR-16).
PRIMARY: dict[str, tuple[str, ...]] = {
    "persona_applicant": (),
    "persona_data_steward": (),
    "persona_permit_reviewer": ("intake_queue",),
    "persona_city_administrator": ("intake_queue",),
    "persona_agent_operator": ("agents_home", "agent_intake", "agent_adjudication", "agent_runs"),
}

#: The agent screens under More tools, by actor id.
SECONDARY: dict[str, tuple[str, ...]] = {}

#: Screens a persona may open for an authorized action but which are not menu
#: destinations.  The intake queue is one of them: the Agent Operator holds
#: the execution grant and opens the queue from the "Process selected cases"
#: link on the Agents home, not from the four-destination navigation.
UNLISTED_OPEN_SCREENS: dict[str, frozenset[str]] = {
    "persona_agent_operator": frozenset({"intake_queue"}),
}

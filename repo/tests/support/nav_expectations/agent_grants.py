"""The agent screens each persona may open.  Owned by the agent operator lane.

All agent-screen authorization of every persona lives here, so the operator
lane changes who opens an agent screen without editing another persona's
module.  An agent screen is placed in a persona's group at its canonical
``SCREENS`` position; a persona whose module lists no screen of its own
takes the order given here (see ``__init__.py``).

The intake queue is not an agent screen: it is the Data Steward's own screen
and stays in ``steward.py``.  The Agent Operator opens it with the execution
grant that lets it process the selected cases, and it is the one screen of
its own under More tools.
"""

from __future__ import annotations

#: The screens that count as agent screens.  A persona module never lists one.
AGENT_SCREENS: frozenset[str] = frozenset(
    {
        "agent_intake",
        "agent_adjudication",
        "agent_steward_assist",
        "agents_home",
        "agent_runs",
        "agent_case",
    }
)

#: The cross-persona grant-driven navigation entries, by actor id.
#:
#: The wake and run grants belong to the Agent Operator alone.  OPR-3 grants
#: the intake-queue read permission to the Permit Reviewer and City
#: Administrator.  The City Administrator lists the queue under More tools;
#: the Permit Reviewer may open it but does not list it.
#: The order of the Agent Operator's list is the order of its five
#: destinations, with the operational summary as its home (OPR-16).  The
#: steward assistant sits next to the other two agents: the operator wakes it
#: and asks it to prepare the work of the queue.
PRIMARY: dict[str, tuple[str, ...]] = {
    "persona_applicant": (),
    "persona_data_steward": (),
    "persona_permit_reviewer": (),
    "persona_city_administrator": (),
    "persona_agent_operator": (
        "agents_home",
        "agent_intake",
        "agent_adjudication",
        "agent_steward_assist",
        "agent_runs",
    ),
}

#: The agent screens under More tools, by actor id.
#:
#: None: OPR-3 moved the wake and run grants to the Agent Operator alone, so
#: no other persona opens an agent screen any more.
SECONDARY: dict[str, tuple[str, ...]] = {
    "persona_data_steward": (),
    "persona_city_administrator": ("intake_queue",),
}

#: Screens a persona may open for an authorized action but which are not menu
#: destinations.  The Permit Reviewer may open People & organizations and the
#: Intake queue, but no reviewer task uses them.
UNLISTED_OPEN_SCREENS: dict[str, frozenset[str]] = {
    "persona_permit_reviewer": frozenset({"applicants", "intake_queue"}),
}

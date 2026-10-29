"""The agent screens each persona may open.  Owned by the agent operator lane.

All agent-screen authorization of every persona lives here, so the operator
lane changes who opens an agent screen without editing another persona's
module.  An agent screen is placed in a persona's group at its canonical
``SCREENS`` position (see ``__init__.py``).
"""

from __future__ import annotations

#: The screens that count as agent screens.  A persona module never lists one.
AGENT_SCREENS: frozenset[str] = frozenset(
    {"agent_intake", "agent_adjudication", "agents_home", "agent_runs", "agent_case"}
)

#: The agent screens of the side navigation, by actor id.
PRIMARY: dict[str, tuple[str, ...]] = {
    "persona_applicant": (),
    "persona_data_steward": ("agent_intake",),
    "persona_permit_reviewer": ("agent_adjudication",),
    "persona_city_administrator": ("agent_intake", "agent_adjudication"),
}

#: The agent screens under More tools, by actor id.
SECONDARY: dict[str, tuple[str, ...]] = {}

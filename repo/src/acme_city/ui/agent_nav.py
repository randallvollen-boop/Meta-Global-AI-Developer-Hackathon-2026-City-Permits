"""The navigation of the Agent Operator lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES``,
``view_models.HOME_OVERRIDES`` or ``view_models.register_screen`` here.
"""

from __future__ import annotations

from acme_city.ui import view_models

#: The actor id of the Agent Operator.
OPERATOR_ACTOR_ID = "persona_agent_operator"

#: The temporary home of the Agent Operator: the intake agent screen, which
#: its ``agent.run.intake`` and ``agent.toggle`` grants open.  OPR-16 replaces
#: it with the agents home at ``/agents``.
OPERATOR_HOME = "/agent/intake"


def register() -> None:
    """Register the home of the Agent Operator."""
    view_models.HOME_OVERRIDES[OPERATOR_ACTOR_ID] = OPERATOR_HOME


__all__ = ["OPERATOR_ACTOR_ID", "OPERATOR_HOME", "register"]

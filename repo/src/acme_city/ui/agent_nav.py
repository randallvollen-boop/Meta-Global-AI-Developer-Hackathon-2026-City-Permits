"""The navigation of the Agent Operator lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES``,
``view_models.HOME_OVERRIDES`` or ``view_models.register_screen`` here.
"""

from __future__ import annotations

from acme_city.ui import view_models

#: The actor id of the Agent Operator.
OPERATOR_ACTOR_ID = "persona_agent_operator"

#: The operational home of the Agent Operator.
OPERATOR_HOME = "/agents"

_OPERATOR_SCREENS: tuple[str, ...] = (
    "agents_home", "agent_intake", "agent_adjudication", "agent_runs",
)

#: The intake queue, where the operator processes a selected batch of waiting
#: cases.  It sits under More tools: the operator opens it for one action.
_OPERATOR_SECONDARY_SCREENS: tuple[str, ...] = ("intake_queue",)

#: The screen of the steward assistant.  The Agent Operator wakes and sleeps
#: the assistant there; the Data Steward never opens it.
STEWARD_ASSIST_SCREEN = "agent_steward_assist"


def _operator_navigation(items: list[dict]) -> list[dict]:
    """Limit the operator to the four operational destinations.

    The intake queue is the fifth: the operator holds the grant that runs a
    selected batch, so the queue that lists the cases is under More tools.
    """
    by_key = {item["key"]: item for item in items}
    navigation = [by_key[key] for key in _OPERATOR_SCREENS if key in by_key]
    for key in _OPERATOR_SECONDARY_SCREENS:
        item = by_key.get(key)
        if item is None:
            continue
        entry = dict(item)
        entry["group"] = "secondary"
        navigation.append(entry)
    return navigation


def register() -> None:
    """Register the home and four-destination navigation of the operator."""
    view_models.HOME_OVERRIDES[OPERATOR_ACTOR_ID] = OPERATOR_HOME
    view_models.NAV_PROFILES[OPERATOR_ACTOR_ID] = _operator_navigation
    if not any(
        screen["key"] == STEWARD_ASSIST_SCREEN for screen in view_models.SCREENS
    ):
        view_models.register_screen(
            STEWARD_ASSIST_SCREEN,
            "Steward assistant",
            "/agent/steward_assist",
            (("agent.toggle", None),),
            "records",
        )


__all__ = ["OPERATOR_ACTOR_ID", "OPERATOR_HOME", "STEWARD_ASSIST_SCREEN", "register"]

"""The navigation of the Data Steward lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES``,
``view_models.HOME_OVERRIDES`` or ``view_models.register_screen`` here.

The Data Steward works in four places: its own work queue, the master
records, the source records and the activity.  Those four are the primary
navigation.  Every other screen the steward may open stays reachable under
More tools, so the bar of a phone holds four entries and the rest.
"""

from __future__ import annotations

from typing import Any

from acme_city.ui import view_models

#: The actor id of the Data Steward.
STEWARD_ACTOR_ID = "persona_data_steward"

#: The home of the Data Steward: its own work queue.
STEWARD_HOME = "/steward"

#: The four screens the steward works in, in the order they are listed.
PRIMARY_SCREENS: tuple[str, ...] = (
    "steward",
    "masters",
    "source_records",
    "activity",
)

#: The screens under More tools, in the order they are listed.
SECONDARY_SCREENS: tuple[str, ...] = (
    "queue",
    "permit",
    "rules",
    "intake_queue",
    "early_resolution",
)


def steward_profile(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the navigation of the Data Steward.

    The four work screens come first and keep their own labels.  Every other
    screen the steward may open becomes a secondary item, so the shared
    navigation shows it under More tools in the canonical order of the
    screens.
    """
    order = {screen["key"]: index for index, screen in enumerate(view_models.SCREENS)}
    by_key = {item["key"]: item for item in items}
    ordered: list[dict[str, Any]] = []
    for key in PRIMARY_SCREENS:
        item = by_key.pop(key, None)
        if item is not None:
            ordered.append(dict(item))
    rest = sorted(by_key.values(), key=lambda item: order.get(item["key"], len(order)))
    for item in rest:
        entry = dict(item)
        entry["group"] = "secondary"
        ordered.append(entry)
    return ordered


def register() -> None:
    """Register the navigation and the home of the Data Steward."""
    view_models.NAV_PROFILES[STEWARD_ACTOR_ID] = steward_profile
    view_models.HOME_OVERRIDES[STEWARD_ACTOR_ID] = STEWARD_HOME


__all__ = [
    "PRIMARY_SCREENS",
    "SECONDARY_SCREENS",
    "STEWARD_ACTOR_ID",
    "STEWARD_HOME",
    "register",
    "steward_profile",
]

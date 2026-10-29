"""The navigation each persona sees, aggregated from one module per persona.

Each persona module (``applicant``, ``steward``, ``reviewer``, ``admin`` and,
once its lane adds it, ``operator``) holds ``ACTOR_ID`` and the ``PRIMARY`` and
``SECONDARY`` groups of that persona without its agent screens.
``agent_grants`` holds the agent screens each persona may open.  A persona
module that does not exist yet is skipped, so a lane adds its module without
editing this file.

- ``GROUPING`` maps an actor id to its two groups with the agent screens
  placed at their canonical ``SCREENS`` position.
- ``EXPECTED_NAVIGATION`` maps an actor id to the rendered order: the primary
  group, then More tools.
- ``EXPECTED_SCREENS`` maps an actor id to the set of screens it may open.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from acme_city.ui import view_models

from . import agent_grants

#: The persona modules, in the order the personas are listed.
PERSONA_MODULES: tuple[str, ...] = ("applicant", "steward", "reviewer", "admin", "operator")


def _load(name: str) -> ModuleType | None:
    qualified = f"{__name__}.{name}"
    try:
        return importlib.import_module(qualified)
    except ModuleNotFoundError as error:
        # Only the absence of the persona module itself is skipped.
        if error.name != qualified:
            raise
        return None


def _place(group: tuple[str, ...], agent_keys: tuple[str, ...]) -> list[str]:
    """Insert each agent screen before the first entry that follows it in ``SCREENS``."""
    order = {screen["key"]: index for index, screen in enumerate(view_models.SCREENS)}
    placed = list(group)
    for key in agent_keys:
        rank = order[key]
        position = next(
            (index for index, other in enumerate(placed) if order.get(other, rank + 1) > rank),
            len(placed),
        )
        placed.insert(position, key)
    return placed


def _aggregate() -> dict[str, dict[str, list[str]]]:
    grouping: dict[str, dict[str, list[str]]] = {}
    for name in PERSONA_MODULES:
        module = _load(name)
        if module is None:
            continue
        actor_id = module.ACTOR_ID
        listed = set(module.PRIMARY) | set(module.SECONDARY)
        stray = sorted(listed & agent_grants.AGENT_SCREENS)
        if stray:
            raise ValueError(f"{name}.py lists agent screens {stray}; they go in agent_grants.py")
        grouping[actor_id] = {
            "primary": _place(module.PRIMARY, agent_grants.PRIMARY.get(actor_id, ())),
            "secondary": _place(module.SECONDARY, agent_grants.SECONDARY.get(actor_id, ())),
        }
    unknown = sorted((set(agent_grants.PRIMARY) | set(agent_grants.SECONDARY)) - set(grouping))
    if unknown:
        raise ValueError(f"agent_grants.py names personas without a module: {unknown}")
    return grouping


GROUPING: dict[str, dict[str, list[str]]] = _aggregate()

EXPECTED_NAVIGATION: dict[str, list[str]] = {
    actor_id: groups["primary"] + groups["secondary"] for actor_id, groups in GROUPING.items()
}

EXPECTED_SCREENS: dict[str, frozenset[str]] = {
    actor_id: frozenset(keys) for actor_id, keys in EXPECTED_NAVIGATION.items()
}

__all__ = ["EXPECTED_NAVIGATION", "EXPECTED_SCREENS", "GROUPING", "PERSONA_MODULES"]

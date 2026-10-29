"""The navigation plugins of the lanes.

Each lane registers its navigation profile, its home override and its added
screens from its own module, so no lane edits the navigation of another.
``load_plugins`` imports those modules by name and calls their ``register``.
A module that does not exist yet is skipped; any other error is raised.
"""
# REQUIRES: UX-01

from __future__ import annotations

import importlib

#: The lane modules, in the order they are loaded.
PLUGIN_MODULES: tuple[str, ...] = (
    "acme_city.ui.steward_nav",
    "acme_city.ui.admin_nav",
    "acme_city.ui.agent_nav",
    "acme_city.ui.agent_admin_views",
)


def load_plugins() -> list[str]:
    """Import every lane module that exists and return the names that loaded."""
    loaded: list[str] = []
    for name in PLUGIN_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as error:
            # Only the absence of the lane module itself is skipped.  A missing
            # import inside a lane module is a real error.
            if error.name != name:
                raise
            continue
        register = getattr(module, "register", None)
        if callable(register):
            register()
        loaded.append(name)
    return loaded


__all__ = ["PLUGIN_MODULES", "load_plugins"]

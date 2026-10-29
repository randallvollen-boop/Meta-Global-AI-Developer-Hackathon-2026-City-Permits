"""The navigation of the City Administrator lanes.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES``,
``view_models.HOME_OVERRIDES`` or ``view_models.register_screen`` here.
"""

from __future__ import annotations


def register() -> None:
    """Register the navigation of the lane.  Nothing is registered yet."""


__all__ = ["register"]

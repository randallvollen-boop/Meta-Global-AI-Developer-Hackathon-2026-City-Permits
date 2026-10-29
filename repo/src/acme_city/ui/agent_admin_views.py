"""The administration tabs and Users-tab parts of the Agent Operator lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its tabs with ``admin_tabs.register_admin_tab`` and its parts
of the Users tab with ``admin_tabs.register_users_extra`` here, and never by
editing ``admin_tabs.py``.
"""

from __future__ import annotations


def register() -> None:
    """Register the administration tabs of the lane.  Nothing is registered yet."""


__all__ = ["register"]

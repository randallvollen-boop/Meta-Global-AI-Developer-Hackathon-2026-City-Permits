"""The routes and interface actions of the Agent Operator lane.

``ui/router.py`` includes ``router`` and merges ``ACTIONS`` into
``ACTION_HANDLERS``, so the lane adds its screens and its governed actions
here and never in the router body.  Nothing is registered yet.
"""
# REQUIRES: UX-01

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from acme_city.ui.router import ActionContext, Outcome

router = APIRouter(tags=["agents"])

#: The interface actions of the lane, keyed by their stable identifier.
ACTIONS: dict[str, Callable[[ActionContext], Outcome]] = {}

__all__ = ["ACTIONS", "router"]

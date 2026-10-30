"""Operator-lane settings, mixed into :class:`acme_city.core.config.Settings`.

Operator fields are added here, never in ``config.py``.  Every default is the
safe one: the agent worker is off and live Muse calls are not allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

ENV_AGENT_WORKER_ENABLED = "ACME_AGENT_WORKER_ENABLED"
ENV_MUSE_LIVE_CALLS_ALLOWED = "ACME_MUSE_LIVE_CALLS_ALLOWED"

_TRUE = {"1", "true", "yes", "on"}


def _flag(raw: str) -> bool:
    return raw.strip().lower() in _TRUE


class OperatorSettings(BaseModel):
    """Settings owned by the operator lane."""

    agent_worker_enabled: bool = False
    muse_live_calls_allowed: bool = False


def operator_env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Return the operator settings that ``environ`` sets explicitly."""
    overrides: dict[str, Any] = {}
    if ENV_AGENT_WORKER_ENABLED in environ:
        overrides["agent_worker_enabled"] = _flag(environ[ENV_AGENT_WORKER_ENABLED])
    if ENV_MUSE_LIVE_CALLS_ALLOWED in environ:
        overrides["muse_live_calls_allowed"] = _flag(environ[ENV_MUSE_LIVE_CALLS_ALLOWED])
    return overrides


__all__ = [
    "ENV_AGENT_WORKER_ENABLED",
    "ENV_MUSE_LIVE_CALLS_ALLOWED",
    "OperatorSettings",
    "operator_env_overrides",
]

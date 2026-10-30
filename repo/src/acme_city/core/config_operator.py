"""Operator-lane settings, mixed into :class:`acme_city.core.config.Settings`.

Operator fields are added here, never in ``config.py``.  Every default is the
safe one: the agent worker is off and live Muse calls are not allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, field_validator

ENV_AGENT_WORKER_ENABLED = "ACME_AGENT_WORKER_ENABLED"
ENV_MUSE_LIVE_CALLS_ALLOWED = "ACME_MUSE_LIVE_CALLS_ALLOWED"
ENV_MUSE_DAILY_CALL_CAP = "ACME_MUSE_DAILY_CALL_CAP"

#: The number of provider calls the day allows when nothing says otherwise.
#: The hosted deployment refuses every live call before this number is read,
#: so the number is the bound of an open deployment and not a permission.
DEFAULT_MUSE_DAILY_CALL_CAP: Final = 10

_TRUE = {"1", "true", "yes", "on"}


def _flag(raw: str) -> bool:
    return raw.strip().lower() in _TRUE


def _whole_number(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"the daily Muse call cap must be a whole number: {raw!r}"
        ) from exc


class OperatorSettings(BaseModel):
    """Settings owned by the operator lane."""

    agent_worker_enabled: bool = False
    muse_live_calls_allowed: bool = False
    #: The provider calls one UTC day allows.  Zero means that the deployment
    #: sends no provider call at all.
    muse_daily_call_cap: int = DEFAULT_MUSE_DAILY_CALL_CAP

    @field_validator("muse_daily_call_cap")
    @classmethod
    def _cap_is_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("muse_daily_call_cap must not be negative")
        return value


def operator_env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Return the operator settings that ``environ`` sets explicitly."""
    overrides: dict[str, Any] = {}
    if ENV_AGENT_WORKER_ENABLED in environ:
        overrides["agent_worker_enabled"] = _flag(environ[ENV_AGENT_WORKER_ENABLED])
    if ENV_MUSE_LIVE_CALLS_ALLOWED in environ:
        overrides["muse_live_calls_allowed"] = _flag(environ[ENV_MUSE_LIVE_CALLS_ALLOWED])
    if ENV_MUSE_DAILY_CALL_CAP in environ:
        overrides["muse_daily_call_cap"] = _whole_number(environ[ENV_MUSE_DAILY_CALL_CAP])
    return overrides


__all__ = [
    "DEFAULT_MUSE_DAILY_CALL_CAP",
    "ENV_AGENT_WORKER_ENABLED",
    "ENV_MUSE_DAILY_CALL_CAP",
    "ENV_MUSE_LIVE_CALLS_ALLOWED",
    "OperatorSettings",
    "operator_env_overrides",
]

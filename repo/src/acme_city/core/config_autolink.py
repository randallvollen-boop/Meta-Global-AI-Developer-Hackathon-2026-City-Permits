"""Auto-link-lane settings, mixed into :class:`acme_city.core.config.Settings`.

Auto-link fields are added here, never in ``config.py``.  Registry automation
defaults to ``paused``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, field_validator

ENV_REGISTRY_AUTOMATION_MODE = "ACME_REGISTRY_AUTOMATION_MODE"


class AutolinkSettings(BaseModel):
    """Settings owned by the auto-link lane."""

    registry_automation_mode: str = "paused"

    @field_validator("registry_automation_mode")
    @classmethod
    def validate_registry_automation_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paused", "suggestions", "active"}:
            raise ValueError("registry automation mode must be paused, suggestions, or active")
        return normalized


def autolink_env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Return the auto-link settings that ``environ`` sets explicitly."""
    overrides: dict[str, Any] = {}
    mode = environ.get(ENV_REGISTRY_AUTOMATION_MODE, "").strip().lower()
    if mode:
        overrides["registry_automation_mode"] = mode
    return overrides


__all__ = [
    "ENV_REGISTRY_AUTOMATION_MODE",
    "AutolinkSettings",
    "autolink_env_overrides",
]

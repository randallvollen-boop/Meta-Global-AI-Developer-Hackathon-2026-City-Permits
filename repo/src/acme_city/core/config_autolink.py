"""Auto-link-lane settings, mixed into :class:`acme_city.core.config.Settings`.

Auto-link fields are added here, never in ``config.py``.  Registry automation
defaults to ``paused``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

ENV_REGISTRY_AUTOMATION_MODE = "ACME_REGISTRY_AUTOMATION_MODE"


class AutolinkSettings(BaseModel):
    """Settings owned by the auto-link lane."""

    registry_automation_mode: str = "paused"


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

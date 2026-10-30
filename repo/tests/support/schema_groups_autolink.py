"""Schema objects owned by the steward autolink lane."""

from __future__ import annotations

SCHEMA_GROUPS: dict[str, tuple[str, ...]] = {
    "registry_automation": (
        "registry_automation_policies",
        "registry_automation_jobs",
        "registry_automation_evaluations",
        "registry_automation_applications",
    ),
}

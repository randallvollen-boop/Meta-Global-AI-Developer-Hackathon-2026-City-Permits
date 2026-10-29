"""Readable presentation labels for the admin-b governance screens."""

from __future__ import annotations

PERMISSION_LABELS: dict[str, str] = {
    "governance.read": "View governance records",
    "governance.manage": "Manage governance records",
    "rules.read": "View rules and fee schedules",
    "rules.manage": "Manage rule and fee versions",
    "policy.scenario.manage": "Build policy scenarios",
}


def identifier_label(value: str | None, *, missing: str = "Not recorded") -> str:
    """Return a sentence-case fallback while preserving the exact id elsewhere."""
    if not value:
        return missing
    label = value.replace("_", " ").replace("-", " ").strip()
    return label[:1].upper() + label[1:]


def permission_label(permission_id: str) -> str:
    """Return a readable permission description."""
    return PERMISSION_LABELS.get(permission_id, identifier_label(permission_id))


def register_label(tab: str, view: str) -> str:
    return f"{identifier_label(tab)} register, {identifier_label(view)} versions"


def comparison_label(baseline: str) -> str:
    return f"Compared with {baseline}"


__all__ = ["PERMISSION_LABELS", "identifier_label", "permission_label", "register_label", "comparison_label"]

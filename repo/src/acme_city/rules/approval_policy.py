"""The approval policy of rule and fee schedule versions.

Two values exist.  ``single`` lets one City Administrator take a version from
draft to published, including the administrator who authored it; the approval
then needs an explicit confirmation and a reason, and the recorded event says
the author approved it under the single-administrator policy.  ``independent``
keeps the author from approving or publishing their own version.

The one source of truth is ``config/approval_policy.json`` (versioned with the
other city configuration).  The environment variable ``ACME_APPROVAL_POLICY``
overrides it for one process.  An unknown value falls back to ``independent``,
the stricter policy.
"""
# REQUIRES: REF-02, CHG-01
# The policy decides whether an author may approve or publish their own version.

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

ENV_APPROVAL_POLICY: Final = "ACME_APPROVAL_POLICY"
POLICY_SINGLE: Final = "single"
POLICY_INDEPENDENT: Final = "independent"
POLICIES: Final = (POLICY_SINGLE, POLICY_INDEPENDENT)
DEFAULT_POLICY: Final = POLICY_SINGLE

CONFIG_PATH: Final = Path(__file__).resolve().parents[3] / "config" / "approval_policy.json"

#: The label recorded with an approval by the author under the single policy.
BASIS_APPROVAL_LABEL: Final = "Approved by the author (single-administrator policy)"
BASIS_PUBLICATION_LABEL: Final = "Published by the author (single-administrator policy)"
BASIS_KEY: Final = "approval_basis_label"
BASIS_VALUE: Final = "author_single_administrator"

POLICY_LABELS: Final = {
    POLICY_SINGLE: "single administrator",
    POLICY_INDEPENDENT: "independent approval",
}


def _configured() -> str:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        value = str(data.get("approval_policy", DEFAULT_POLICY)).strip().lower()
    except (OSError, ValueError, AttributeError):
        value = DEFAULT_POLICY
    return value


def active_policy() -> str:
    """Return ``single`` or ``independent``: the environment first, then the config."""
    override = os.environ.get(ENV_APPROVAL_POLICY, "").strip().lower()
    value = override or _configured()
    return value if value in POLICIES else POLICY_INDEPENDENT


def is_single() -> bool:
    """Return whether one administrator may approve and publish their own version."""
    return active_policy() == POLICY_SINGLE


def policy_label() -> str:
    """Return the plain name of the active policy."""
    return POLICY_LABELS[active_policy()]


__all__ = [
    "BASIS_APPROVAL_LABEL",
    "BASIS_KEY",
    "BASIS_PUBLICATION_LABEL",
    "BASIS_VALUE",
    "DEFAULT_POLICY",
    "ENV_APPROVAL_POLICY",
    "POLICIES",
    "POLICY_INDEPENDENT",
    "POLICY_LABELS",
    "POLICY_SINGLE",
    "active_policy",
    "is_single",
    "policy_label",
]

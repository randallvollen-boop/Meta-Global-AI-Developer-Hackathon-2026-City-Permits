"""Schema objects owned by the steward assistant lane.

``tests/unit/test_schema.py`` merges this dict into its required groups, so the
lane never edits that file.
"""

from __future__ import annotations

SCHEMA_GROUPS: dict[str, tuple[str, ...]] = {
    "steward_assist": (
        "steward_recommendations",
    ),
}

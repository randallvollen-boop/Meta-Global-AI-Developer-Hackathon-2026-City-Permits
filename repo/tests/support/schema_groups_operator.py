"""Object groups the agent operator lane adds to the schema.

``tests/unit/test_schema.py`` merges this dict into its required groups, so the
lane never edits that file.  Empty until the lane adds tables.
"""

from __future__ import annotations

SCHEMA_GROUPS: dict[str, tuple[str, ...]] = {}

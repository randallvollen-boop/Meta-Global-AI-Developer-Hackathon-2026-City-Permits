"""The head revision of the migration scripts, so no test pins a literal head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO = Path(__file__).resolve().parents[2]


def migration_head() -> str:
    """Return the single head of ``migrations/``; lane migrations need no test edit."""
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("script_location", str(REPO / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head

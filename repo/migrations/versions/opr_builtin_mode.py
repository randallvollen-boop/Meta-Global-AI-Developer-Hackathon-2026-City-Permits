"""Let a model run record the built in logic of the City.

Revision ID: opr_builtin_mode
Revises: opr_work_queue
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "opr_builtin_mode"
down_revision: str | None = "opr_work_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The modes a model run may record, before and after this revision.
MODES = ("live", "replay", "cached")
MODES_WITH_BUILTIN = ("live", "replay", "cached", "builtin")


def _mode_clause(modes: tuple[str, ...]) -> str:
    """Return the check clause of the recorded modes."""
    allowed = ", ".join(f"'{mode}'" for mode in modes)
    return f"mode IN ({allowed})"


def upgrade() -> None:
    """Widen the mode of a model run so the built in logic may be recorded."""
    with op.batch_alter_table("model_runs", schema=None) as batch_op:
        batch_op.drop_constraint("mode_allowed", type_="check")
        batch_op.create_check_constraint("mode_allowed", _mode_clause(MODES_WITH_BUILTIN))


def downgrade() -> None:
    """Narrow the mode of a model run back to the provider paths."""
    with op.batch_alter_table("model_runs", schema=None) as batch_op:
        batch_op.drop_constraint("mode_allowed", type_="check")
        batch_op.create_check_constraint("mode_allowed", _mode_clause(MODES))

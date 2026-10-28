"""Parity phase 3 chat 2: the outcome of an assistant turn.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28

Widens the outcome check of ``help_turns``.  A turn may now record that the
assistant wrote the answer and that the validation passed it
(``answered``), that the validation refused the answer (``rejected``), that
the assistant could not answer (``unanswerable``) or that the run itself
failed (``failed``).

The constraint is the only thing that changes: no row is rewritten and no
turn that exists changes its outcome.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The outcomes a turn may hold after this migration.
OUTCOMES: str = (
    "outcome IN ('matched', 'answered', 'no_match', 'rejected', "
    "'unanswerable', 'failed')"
)

#: The outcomes a turn held before this migration.
PREVIOUS_OUTCOMES: str = "outcome IN ('matched', 'no_match')"


def upgrade() -> None:
    with op.batch_alter_table('help_turns', schema=None) as batch_op:
        batch_op.drop_constraint('outcome_allowed', type_='check')
        batch_op.create_check_constraint('outcome_allowed', OUTCOMES)


def downgrade() -> None:
    with op.batch_alter_table('help_turns', schema=None) as batch_op:
        batch_op.drop_constraint('outcome_allowed', type_='check')
        batch_op.create_check_constraint('outcome_allowed', PREVIOUS_OUTCOMES)

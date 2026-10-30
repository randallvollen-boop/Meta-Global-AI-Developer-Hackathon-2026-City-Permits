"""Let a recommendation carry the plain words Muse wrote.

Revision ID: stw_steward_explanation
Revises: stw_steward_assist_agent
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "stw_steward_explanation"
down_revision: str | None = "stw_steward_assist_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The deterministic reason of the assistant stays the reason of the
    # recommendation.  The plain words Muse wrote are kept beside it, with the
    # run that wrote them, so the steward can read one and accept the other.
    with op.batch_alter_table("steward_recommendations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("muse_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("muse_run_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("steward_recommendations", schema=None) as batch_op:
        batch_op.drop_column("muse_run_id")
        batch_op.drop_column("muse_reason")

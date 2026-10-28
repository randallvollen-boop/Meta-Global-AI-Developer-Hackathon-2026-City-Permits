"""Parity phase 3b: the per-type service target.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27

Adds ``permit_types.service_target_days``: the fictional number of days the
City aims to review a case of a type in.  The intake queue compares the age
of a case with this figure when it colours the age chip.

The column is added with the neutral default ``0``.  The demonstration's own
catalogue carries the fictional targets, and the reset writes them; the
migration itself creates no figure of its own and fabricates none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'service_target_days',
                sa.Integer(),
                nullable=False,
                server_default=sa.text('0'),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.drop_column('service_target_days')

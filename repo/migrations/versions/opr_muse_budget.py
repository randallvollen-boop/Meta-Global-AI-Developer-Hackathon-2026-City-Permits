"""Persist the daily allowance of provider calls.

Revision ID: opr_muse_budget
Revises: opr_builtin_mode
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = "opr_muse_budget"
down_revision: str | None = "opr_builtin_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "muse_daily_budget",
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("calls_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            acme_city.persistence.types.UTCDateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.CheckConstraint(
            "calls_used >= 0",
            name=op.f("ck_muse_daily_budget_calls_used_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_muse_daily_budget")),
    )
    with op.batch_alter_table("muse_daily_budget", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_muse_daily_budget_day"), ["day"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("muse_daily_budget", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_muse_daily_budget_day"))

    op.drop_table("muse_daily_budget")

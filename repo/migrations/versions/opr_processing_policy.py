"""Persist the Agent Operator processing policy.

Revision ID: opr_processing_policy
Revises: opr_entitlement
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = "opr_processing_policy"
down_revision: str | None = "opr_entitlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_processing_policies",
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("runs_per_hour", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_batch_size", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", acme_city.persistence.types.UTCDateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.CheckConstraint("mode IN ('manual', 'automatic')", name=op.f("ck_agent_processing_policies_mode_allowed")),
        sa.CheckConstraint("runs_per_hour BETWEEN 1 AND 120", name=op.f("ck_agent_processing_policies_runs_per_hour_range")),
        sa.CheckConstraint("max_batch_size BETWEEN 1 AND 20", name=op.f("ck_agent_processing_policies_max_batch_size_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_processing_policies")),
    )
    with op.batch_alter_table("agent_processing_policies", schema=None) as batch_op:
        batch_op.create_index(
            op.f("ix_agent_processing_policies_correlation_id"), ["correlation_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_processing_policies", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_agent_processing_policies_correlation_id"))
    op.drop_table("agent_processing_policies")

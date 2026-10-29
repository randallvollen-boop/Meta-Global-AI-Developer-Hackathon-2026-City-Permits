"""The entitlement of a role to wake and run the agents.

Revision ID: opr_entitlement
Revises: 0013
Create Date: 2026-10-29

Adds the table of role entitlements of the agent operator lane.  The migration
creates the empty table and no row of its own: the reset seeds the default
entitlement of the demonstration through the seed hook of the lane.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = "opr_entitlement"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_role_entitlements",
        sa.Column("role_id", sa.String(length=64), nullable=False),
        sa.Column("can_run_agents", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("changed_by", sa.String(length=64), nullable=True),
        sa.Column("changed_at", acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", acme_city.persistence.types.UTCDateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_role_entitlements")),
        sa.UniqueConstraint("role_id", name=op.f("uq_agent_role_entitlements_role_id")),
    )
    with op.batch_alter_table("agent_role_entitlements", schema=None) as batch_op:
        batch_op.create_index(
            op.f("ix_agent_role_entitlements_role_id"), ["role_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_role_entitlements", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_agent_role_entitlements_role_id"))
    op.drop_table("agent_role_entitlements")

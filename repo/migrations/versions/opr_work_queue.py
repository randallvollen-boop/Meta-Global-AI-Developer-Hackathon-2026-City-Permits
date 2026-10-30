"""Persist the durable work queue of the agents.

Revision ID: opr_work_queue
Revises: opr_processing_policy
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = "opr_work_queue"
down_revision: str | None = "opr_processing_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_work_queue",
        sa.Column("work_key", sa.String(length=160), nullable=False),
        sa.Column("application_id", sa.String(length=64), nullable=False),
        sa.Column("agent_key", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column("finished_at", acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            acme_city.persistence.types.UTCDateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "agent_key IN ('intake', 'adjudication')",
            name=op.f("ck_agent_work_queue_agent_key_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'held')",
            name=op.f("ck_agent_work_queue_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_agent_work_queue_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_work_queue")),
    )
    with op.batch_alter_table("agent_work_queue", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agent_work_queue_application_id"), ["application_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_agent_work_queue_correlation_id"), ["correlation_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_agent_work_queue_work_key"), ["work_key"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_work_queue", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_work_queue_work_key"))
        batch_op.drop_index(batch_op.f("ix_agent_work_queue_correlation_id"))
        batch_op.drop_index(batch_op.f("ix_agent_work_queue_application_id"))

    op.drop_table("agent_work_queue")

"""Agent steps for the intake triage pipeline.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27

Adds the ``agent_steps`` table (one auditable row per named triage step) and
the advisory columns on ``recommendations`` (deterministic rationale, optional
Muse summary, reviewer stance).  A migration creates no rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'agent_steps',
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('step_name', sa.String(length=64), nullable=False),
        sa.Column('service_identity_id', sa.String(length=64), nullable=False),
        sa.Column(
            'started_at',
            acme_city.persistence.types.UTCDateTime(),
            nullable=False,
        ),
        sa.Column(
            'ended_at',
            acme_city.persistence.types.UTCDateTime(),
            nullable=True,
        ),
        sa.Column('inputs', sa.JSON(), nullable=True),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('outcome_detail', sa.Text(), nullable=True),
        sa.Column('model_run_id', sa.String(length=64), nullable=True),
        sa.Column('evaluation_id', sa.String(length=64), nullable=True),
        sa.Column('recommendation_id', sa.String(length=64), nullable=True),
        sa.Column('proposal_ids', sa.JSON(), nullable=True),
        sa.Column('triggered_by', sa.String(length=64), nullable=True),
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('completed', 'needs_information', 'failed', 'skipped', 'recorded')",
            name='ck_agent_steps_outcome_allowed',
        ),
        sa.ForeignKeyConstraint(
            ['application_id'], ['applications.id'],
            name='fk_agent_steps_application_id_applications', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_agent_steps'),
    )
    op.create_index('ix_agent_steps_application_id', 'agent_steps', ['application_id'], unique=False)
    op.create_index('ix_agent_steps_correlation_id', 'agent_steps', ['correlation_id'], unique=False)
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rationale', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('muse_summary', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('muse_run_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reviewer_stance', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('reviewer_stance_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewer_stance_actor_id', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_column('reviewer_stance_actor_id')
        batch_op.drop_column('reviewer_stance_reason')
        batch_op.drop_column('reviewer_stance')
        batch_op.drop_column('muse_run_id')
        batch_op.drop_column('muse_summary')
        batch_op.drop_column('rationale')
    op.drop_index('ix_agent_steps_correlation_id', table_name='agent_steps')
    op.drop_index('ix_agent_steps_application_id', table_name='agent_steps')
    op.drop_table('agent_steps')

"""Parity phase 3 policy 4: draft conversions of what-if runs.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28

Adds one table and no row: ``policy_draft_conversions`` links a run to the
draft rule and fee versions made from it (one conversion per run).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('policy_draft_conversions',
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('scenario_id', sa.String(length=64), nullable=False),
    sa.Column('run_content_hash', sa.String(length=64), nullable=False),
    sa.Column('converted_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('drafts', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['policy_runs.id'], name=op.f('fk_policy_draft_conversions_run_id_policy_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_draft_conversions')),
    sa.UniqueConstraint('run_id', name=op.f('uq_policy_draft_conversions_run_id'))
    )
    with op.batch_alter_table('policy_draft_conversions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_draft_conversions_correlation_id'), ['correlation_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('policy_draft_conversions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_draft_conversions_correlation_id'))

    op.drop_table('policy_draft_conversions')

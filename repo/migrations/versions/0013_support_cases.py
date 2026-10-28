"""Parity phase 3c: support cases.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28

Adds the table of support cases the City Administrator records on the
support screen.  The migration creates the empty table and no row of its own.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('support_cases',
    sa.Column('application_id', sa.String(length=64), nullable=True),
    sa.Column('reference', sa.String(length=96), nullable=True),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('recorded_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("channel IN ('phone', 'email', 'counter', 'mail', 'other')", name=op.f('ck_support_cases_channel_allowed')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_support_cases_application_id_applications'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_support_cases'))
    )
    with op.batch_alter_table('support_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_support_cases_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_support_cases_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_support_cases_recorded_by_actor_id'), ['recorded_by_actor_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('support_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_support_cases_recorded_by_actor_id'))
        batch_op.drop_index(batch_op.f('ix_support_cases_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_support_cases_application_id'))
    op.drop_table('support_cases')

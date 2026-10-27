"""Permit type icons.

Adds the ``permit_type_icons`` table (seeded assets and saved Muse Image
generations, bytes in the database) and the nullable ``permit_types.icon_id``
pointer at a type's current icon.  Seeding of the bundled WebP assets happens
in application code, not in the migration: a migration creates no rows.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'permit_type_icons',
        sa.Column('permit_type_id', sa.String(length=64), nullable=False),
        sa.Column('image_data', sa.LargeBinary(), nullable=False),
        sa.Column('media_type', sa.String(length=64), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('seed', 'generated')", name='ck_permit_type_icons_source_allowed'),
        sa.ForeignKeyConstraint(
            ['permit_type_id'], ['permit_types.id'], name='fk_permit_type_icons_permit_type_id_permit_types', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_permit_type_icons'),
    )
    op.create_index('ix_permit_type_icons_permit_type_id', 'permit_type_icons', ['permit_type_id'], unique=False)
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('icon_id', sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            'fk_permit_types_icon_id_permit_type_icons', 'permit_type_icons', ['icon_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.drop_constraint('fk_permit_types_icon_id_permit_type_icons', type_='foreignkey')
        batch_op.drop_column('icon_id')
    op.drop_index('ix_permit_type_icons_permit_type_id', table_name='permit_type_icons')
    op.drop_table('permit_type_icons')

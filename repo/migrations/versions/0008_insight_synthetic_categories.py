"""Parity phase 3 insight: synthetic flags and business categories.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28

Adds a ``synthetic`` flag (default false) to the rows the seeded synthetic
permit history writes, a ``synthetic_population`` id on applications, and
``credentials.business_category``.

The category backfill is explicit and reported: every existing business
licence is given a category from the words in the holder's name, anything
without a match is ``other``, and the number of rows touched per category is
logged.  A contractor registration keeps a blank category.  Nothing else is
rewritten.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGGER = logging.getLogger("alembic.runtime.migration")

SYNTHETIC_TABLES: tuple[str, ...] = (
    'applications',
    'application_revisions',
    'application_parties',
    'application_sites',
    'decisions',
    'permits',
    'canonical_entities',
    'parties',
    'credentials',
)

#: The words that place a business in a category, in the order they are tried.
CATEGORY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('bar', ('tavern', 'pub', 'brewery', 'taproom', 'lounge', ' bar')),
    ('restaurant', ('coffee', 'cafe', 'bakery', 'grill', 'kitchen', 'diner', 'bistro', 'restaurant')),
    ('retail', ('imports', 'market', 'shop', 'goods', 'store', 'boutique')),
    ('office', ('property', 'realty', 'consulting', 'partners', 'office', 'law')),
)


def _category_for(name: str) -> str:
    lowered = f' {name.lower()}'
    for category, words in CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return category
    return 'other'


def upgrade() -> None:
    for table in SYNTHETIC_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('synthetic', sa.Boolean(), nullable=False, server_default=sa.text('0'))
            )
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('synthetic_population', sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_applications_synthetic_population'), ['synthetic_population'], unique=False
        )
    with op.batch_alter_table('credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('business_category', sa.String(length=24), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            'SELECT c.id, p.display_name FROM credentials c '
            'JOIN parties p ON p.id = c.holder_party_id '
            "WHERE c.credential_type = 'business_license'"
        )
    ).fetchall()
    counts: dict[str, int] = {}
    for credential_id, name in rows:
        category = _category_for(str(name or ''))
        counts[category] = counts.get(category, 0) + 1
        connection.execute(
            sa.text('UPDATE credentials SET business_category = :category WHERE id = :id'),
            {'category': category, 'id': credential_id},
        )
    LOGGER.info('business category backfill: %s licences, by category %s', len(rows), counts)


def downgrade() -> None:
    with op.batch_alter_table('credentials', schema=None) as batch_op:
        batch_op.drop_column('business_category')
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_synthetic_population'))
        batch_op.drop_column('synthetic_population')
    for table in reversed(SYNTHETIC_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('synthetic')

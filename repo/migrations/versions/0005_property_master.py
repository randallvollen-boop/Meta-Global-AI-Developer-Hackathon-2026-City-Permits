"""Property master: parcel attributes, address points, streets, zoning, parcel matches.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27

Extends the registry ``parcels`` and ``addresses`` tables with the synthetic
attributes the simulated ArcGIS services serve, and adds the street, zoning,
parcel-match, dataset-subscriber and application-draft tables.  A migration
creates no rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('application_drafts',
    sa.Column('reference', sa.String(length=64), nullable=False),
    sa.Column('permit_type_key', sa.String(length=64), nullable=False),
    sa.Column('owner_actor_id', sa.String(length=64), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=True),
    sa.Column('updated_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'submitted')", name=op.f('ck_application_drafts_status_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_drafts')),
    sa.UniqueConstraint('reference', name=op.f('uq_application_drafts_reference'))
    )
    with op.batch_alter_table('application_drafts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_drafts_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_application_drafts_owner_actor_id'), ['owner_actor_id'], unique=False)

    op.create_table('dataset_subscribers',
    sa.Column('dataset_key', sa.String(length=96), nullable=False),
    sa.Column('department_key', sa.String(length=64), nullable=False),
    sa.Column('department_label', sa.String(length=160), nullable=False),
    sa.Column('consumed_fields', sa.JSON(), nullable=False),
    sa.Column('contract_text', sa.Text(), nullable=False),
    sa.Column('signal_key', sa.String(length=64), nullable=False),
    sa.Column('signal_label', sa.String(length=160), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_subscribers'))
    )
    with op.batch_alter_table('dataset_subscribers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_subscribers_dataset_key'), ['dataset_key'], unique=False)

    op.create_table('gis_streets',
    sa.Column('street_key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('road_type', sa.String(length=48), nullable=True),
    sa.Column('path', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gis_streets')),
    sa.UniqueConstraint('street_key', name=op.f('uq_gis_streets_street_key'))
    )
    op.create_table('zoning_districts',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_zoning_districts')),
    sa.UniqueConstraint('code', name=op.f('uq_zoning_districts_code'))
    )
    op.create_table('draft_documents',
    sa.Column('draft_id', sa.String(length=64), nullable=False),
    sa.Column('document_type', sa.String(length=64), nullable=False),
    sa.Column('filename', sa.String(length=120), nullable=False),
    sa.Column('media_type', sa.String(length=64), nullable=False),
    sa.Column('file_ref', sa.String(length=240), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('byte_length', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['application_drafts.id'], name=op.f('fk_draft_documents_draft_id_application_drafts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_draft_documents'))
    )
    with op.batch_alter_table('draft_documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_draft_documents_draft_id'), ['draft_id'], unique=False)

    op.create_table('application_parcel_matches',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('submitted_text', sa.String(length=320), nullable=False),
    sa.Column('matched_address', sa.String(length=320), nullable=True),
    sa.Column('address_id', sa.String(length=64), nullable=True),
    sa.Column('parcel_id', sa.String(length=64), nullable=True),
    sa.Column('parcel_number', sa.String(length=96), nullable=True),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('locator_status', sa.String(length=2), nullable=False),
    sa.Column('x', sa.Float(), nullable=True),
    sa.Column('y', sa.Float(), nullable=True),
    sa.Column('candidates', sa.JSON(), nullable=True),
    sa.Column('method', sa.String(length=64), nullable=False),
    sa.Column('link_state', sa.String(length=24), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('proposed_by', sa.String(length=64), nullable=True),
    sa.Column('decided_by', sa.String(length=64), nullable=True),
    sa.Column('decided_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('decision_reason', sa.Text(), nullable=True),
    sa.Column('confirmed_by', sa.String(length=64), nullable=True),
    sa.Column('confirmed_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("link_state IN ('proposed', 'needs_choice', 'not_found', 'approved', 'rejected')", name=op.f('ck_application_parcel_matches_link_state_allowed')),
    sa.CheckConstraint("locator_status IN ('M', 'T', 'U')", name=op.f('ck_application_parcel_matches_locator_status_allowed')),
    sa.ForeignKeyConstraint(['address_id'], ['addresses.id'], name=op.f('fk_application_parcel_matches_address_id_addresses'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_parcel_matches_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcels.id'], name=op.f('fk_application_parcel_matches_parcel_id_parcels'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_parcel_matches')),
    sa.UniqueConstraint('application_id', name=op.f('uq_application_parcel_matches_application_id'))
    )
    with op.batch_alter_table('application_parcel_matches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_parcel_matches_correlation_id'), ['correlation_id'], unique=False)

    with op.batch_alter_table('addresses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('x', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('y', sa.Float(), nullable=True))

    with op.batch_alter_table('parcels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_name', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('use_code', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('use_description', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('zoning_code', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('subdivision', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('area_acres', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('land_value_cents', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('improvement_value_cents', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tax_district', sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column('school_district', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('flood_zone', sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column('geometry', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('department_signals', sa.JSON(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('parcels', schema=None) as batch_op:
        batch_op.drop_column('department_signals')
        batch_op.drop_column('geometry')
        batch_op.drop_column('flood_zone')
        batch_op.drop_column('school_district')
        batch_op.drop_column('tax_district')
        batch_op.drop_column('improvement_value_cents')
        batch_op.drop_column('land_value_cents')
        batch_op.drop_column('area_acres')
        batch_op.drop_column('subdivision')
        batch_op.drop_column('zoning_code')
        batch_op.drop_column('use_description')
        batch_op.drop_column('use_code')
        batch_op.drop_column('owner_name')

    with op.batch_alter_table('addresses', schema=None) as batch_op:
        batch_op.drop_column('y')
        batch_op.drop_column('x')

    with op.batch_alter_table('application_parcel_matches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_parcel_matches_correlation_id'))

    op.drop_table('application_parcel_matches')
    with op.batch_alter_table('draft_documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_draft_documents_draft_id'))

    op.drop_table('draft_documents')
    op.drop_table('zoning_districts')
    op.drop_table('gis_streets')
    with op.batch_alter_table('dataset_subscribers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_subscribers_dataset_key'))

    op.drop_table('dataset_subscribers')
    with op.batch_alter_table('application_drafts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_drafts_owner_actor_id'))
        batch_op.drop_index(batch_op.f('ix_application_drafts_correlation_id'))

    op.drop_table('application_drafts')

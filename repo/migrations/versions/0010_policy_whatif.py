"""Parity phase 3 policy 2: what-if scenarios, revisions and immutable runs.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28

Adds three tables and no row:

* ``policy_scenarios``: a saved what-if, soft-deleted with ``deleted_at``;
* ``policy_scenario_revisions``: every saved revision of a scenario;
* ``policy_runs``: an immutable evaluation snapshot (scenario revision, full
  baseline and proposed configuration, ordered case inputs, population
  definition, ``analysis_at``, engine and generator versions, result and a
  canonical content hash).

Nothing in a live table (rules, fees, types, applications) is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('policy_scenarios',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('current_revision', sa.Integer(), nullable=False),
    sa.Column('suggestion_key', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('deleted_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_scenarios'))
    )
    with op.batch_alter_table('policy_scenarios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_scenarios_correlation_id'), ['correlation_id'], unique=False)

    op.create_table('policy_scenario_revisions',
    sa.Column('scenario_id', sa.String(length=64), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('starting_population', sa.JSON(), nullable=True),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['scenario_id'], ['policy_scenarios.id'], name=op.f('fk_policy_scenario_revisions_scenario_id_policy_scenarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_scenario_revisions')),
    sa.UniqueConstraint('scenario_id', 'revision_number', name='scenario_revision')
    )
    with op.batch_alter_table('policy_scenario_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_scenario_revisions_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('policy_runs',
    sa.Column('scenario_id', sa.String(length=64), nullable=False),
    sa.Column('scenario_revision_id', sa.String(length=64), nullable=False),
    sa.Column('scenario_revision_number', sa.Integer(), nullable=False),
    sa.Column('scenario_name', sa.String(length=200), nullable=False),
    sa.Column('created_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('analysis_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('engine_version', sa.String(length=64), nullable=False),
    sa.Column('generator_version', sa.String(length=64), nullable=True),
    sa.Column('population_kind', sa.String(length=32), nullable=False),
    sa.Column('population_label', sa.String(length=200), nullable=False),
    sa.Column('population_synthetic', sa.Boolean(), nullable=False),
    sa.Column('population_size', sa.Integer(), nullable=False),
    sa.Column('population_spec', sa.JSON(), nullable=False),
    sa.Column('population_definition', sa.JSON(), nullable=False),
    sa.Column('baseline_config', sa.JSON(), nullable=False),
    sa.Column('proposed_config', sa.JSON(), nullable=False),
    sa.Column('case_inputs', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('baseline_hash', sa.String(length=64), nullable=False),
    sa.Column('proposed_hash', sa.String(length=64), nullable=False),
    sa.Column('population_hash', sa.String(length=64), nullable=False),
    sa.Column('result_hash', sa.String(length=64), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['scenario_id'], ['policy_scenarios.id'], name=op.f('fk_policy_runs_scenario_id_policy_scenarios')),
    sa.ForeignKeyConstraint(['scenario_revision_id'], ['policy_scenario_revisions.id'], name=op.f('fk_policy_runs_scenario_revision_id_policy_scenario_revisions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_runs'))
    )
    with op.batch_alter_table('policy_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_runs_content_hash'), ['content_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_policy_runs_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_policy_runs_scenario_id'), ['scenario_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('policy_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_runs_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_policy_runs_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_policy_runs_content_hash'))

    op.drop_table('policy_runs')
    with op.batch_alter_table('policy_scenario_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_scenario_revisions_scenario_id'))

    op.drop_table('policy_scenario_revisions')
    with op.batch_alter_table('policy_scenarios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_scenarios_correlation_id'))

    op.drop_table('policy_scenarios')

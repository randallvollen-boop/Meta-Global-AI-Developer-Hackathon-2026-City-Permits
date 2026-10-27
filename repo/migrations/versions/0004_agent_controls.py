"""Agent controls and agent runs for the two people-driven agents.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27

Adds the ``agent_controls`` table (the awake/asleep state of each agent),
the ``agent_runs`` table (one row per run of an agent on an application) and
the ``agent_run_nodes`` table (the per-node trace of a run).  The advisory
``recommendations`` table gains its recommendation status, its conditions of
approval and its confirmation/reversion record.  A migration creates no rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'agent_controls',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('agent_key', sa.String(length=32), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('changed_by', sa.String(length=64), nullable=True),
        sa.Column('changed_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "mode IN ('asleep', 'awake')",
            name='mode_allowed',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_agent_controls'),
        sa.UniqueConstraint('agent_key', name='uq_agent_controls_agent_key'),
    )
    op.create_index(
        'ix_agent_controls_correlation_id', 'agent_controls', ['correlation_id'], unique=False
    )
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('agent_key', sa.String(length=32), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=True),
        sa.Column('service_identity_id', sa.String(length=64), nullable=False),
        sa.Column('triggered_by', sa.String(length=64), nullable=True),
        sa.Column('started_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
        sa.Column('finished_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('outcome_detail', sa.Text(), nullable=True),
        sa.Column('inputs', sa.JSON(), nullable=True),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "agent_key IN ('intake', 'adjudication')",
            name='agent_key_allowed',
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'needs_information', 'recommended', 'held', "
            "'failed', 'skipped', 'recorded')",
            name='outcome_allowed',
        ),
        sa.ForeignKeyConstraint(
            ['application_id'], ['applications.id'],
            name='fk_agent_runs_application_id_applications', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_agent_runs'),
    )
    op.create_index('ix_agent_runs_application_id', 'agent_runs', ['application_id'], unique=False)
    op.create_index('ix_agent_runs_agent_key', 'agent_runs', ['agent_key'], unique=False)
    op.create_index('ix_agent_runs_correlation_id', 'agent_runs', ['correlation_id'], unique=False)
    op.create_table(
        'agent_run_nodes',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('agent_run_id', sa.String(length=64), nullable=False),
        sa.Column('node_id', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=160), nullable=False),
        sa.Column('dependency_level', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'warn', 'block')",
            name='status_allowed',
        ),
        sa.ForeignKeyConstraint(
            ['agent_run_id'], ['agent_runs.id'],
            name='fk_agent_run_nodes_agent_run_id_agent_runs', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_agent_run_nodes'),
    )
    op.create_index(
        'ix_agent_run_nodes_agent_run_id', 'agent_run_nodes', ['agent_run_id'], unique=False
    )
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conditions', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('confirmed_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('confirmed_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('reverted_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reverted_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('revert_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('decision_id', sa.String(length=64), nullable=True))
        # The agree/disagree stance of build 2 is replaced by confirm and
        # revert; its columns go with it.
        batch_op.drop_column('reviewer_stance_actor_id')
        batch_op.drop_column('reviewer_stance_reason')
        batch_op.drop_column('reviewer_stance')
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conditions', sa.JSON(), nullable=True))
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_area', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('process_category', sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column('discretionary', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('fee_schedule_key', sa.String(length=96), nullable=True))
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quality', sa.JSON(), nullable=True))
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_area', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('requirements_snapshot', sa.JSON(), nullable=True))
    op.create_table(
        'application_findings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('finding_type', sa.String(length=48), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('rule', sa.String(length=160), nullable=True),
        sa.Column('applicant_must', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('source_node', sa.String(length=64), nullable=True),
        sa.Column('related_application_id', sa.String(length=64), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "finding_type IN ('missing_field', 'missing_document', 'unreadable', "
            "'duplicate', 'conflict', 'low_confidence_extraction', 'judgment')",
            name='finding_type_allowed',
        ),
        sa.CheckConstraint(
            "severity IN ('block', 'review')",
            name='severity_allowed',
        ),
        sa.ForeignKeyConstraint(
            ['application_id'], ['applications.id'],
            name='fk_application_findings_application_id_applications', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_application_findings'),
    )
    op.create_index(
        'ix_application_findings_application_id',
        'application_findings',
        ['application_id'],
        unique=False,
    )
    op.create_index(
        'ix_application_findings_correlation_id',
        'application_findings',
        ['correlation_id'],
        unique=False,
    )
    with op.batch_alter_table('actors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('department', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('persona_role', sa.String(length=48), nullable=True))
    op.create_table(
        'reason_codes',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('code', sa.String(length=48), nullable=False),
        sa.Column('label', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('changed_by', sa.String(length=64), nullable=True),
        sa.Column('changed_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
        sa.Column(
            'created_at',
            acme_city.persistence.types.UTCDateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_reason_codes'),
        sa.UniqueConstraint('code', name='uq_reason_codes_code'),
    )
    op.create_index(
        'ix_reason_codes_correlation_id', 'reason_codes', ['correlation_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_reason_codes_correlation_id', table_name='reason_codes')
    op.drop_index('ix_agent_controls_correlation_id', table_name='agent_controls')
    with op.batch_alter_table('actors', schema=None) as batch_op:
        batch_op.drop_column('persona_role')
        batch_op.drop_column('department')
    op.drop_index('ix_application_findings_correlation_id', table_name='application_findings')
    op.drop_index('ix_application_findings_application_id', table_name='application_findings')
    op.drop_table('application_findings')
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_column('requirements_snapshot')
        batch_op.drop_column('review_area')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('quality')
    op.drop_table('reason_codes')
    with op.batch_alter_table('permit_types', schema=None) as batch_op:
        batch_op.drop_column('fee_schedule_key')
        batch_op.drop_column('description')
        batch_op.drop_column('discretionary')
        batch_op.drop_column('process_category')
        batch_op.drop_column('review_area')
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.drop_column('conditions')
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewer_stance', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('reviewer_stance_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewer_stance_actor_id', sa.String(length=64), nullable=True))
        batch_op.drop_column('decision_id')
        batch_op.drop_column('revert_reason')
        batch_op.drop_column('reverted_at')
        batch_op.drop_column('reverted_by')
        batch_op.drop_column('confirmed_at')
        batch_op.drop_column('confirmed_by')
        batch_op.drop_column('conditions')
    op.drop_index('ix_agent_run_nodes_agent_run_id', table_name='agent_run_nodes')
    op.drop_table('agent_run_nodes')
    op.drop_index('ix_agent_runs_correlation_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_agent_key', table_name='agent_runs')
    op.drop_index('ix_agent_runs_application_id', table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_table('agent_controls')

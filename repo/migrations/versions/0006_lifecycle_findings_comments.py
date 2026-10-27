"""Parity phase 3a: lifecycle statuses, typed reason codes, findings, comments.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27

Adds the three new application statuses (``revisions_requested``, ``returned``
and ``archived``) with the archive bookkeeping, the priority and the routing
owner, the ``code_type`` of a reason code, the state and the waiver of a
finding, the denial reason code and the waiver snapshot of a decision, the
staleness of a recommendation, and the two new tables: ``application_comments``
and ``application_actions``.

The five reason codes the demonstration shipped with are backfilled
explicitly, one statement per code.  The backfill updates rows; it creates
none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The explicit backfill of the reason codes the demonstration shipped with.
#: Each code is assigned the one use it may serve.
REASON_CODE_BACKFILL: tuple[tuple[str, str], ...] = (
    ('INCOMPLETE_APPLICATION', 'return'),
    ('WITHDRAWN_BY_APPLICANT', 'return'),
    ('DUPLICATE_SUBMISSION', 'return'),
    ('DOES_NOT_MEET_CODE', 'denial'),
    ('OUTSIDE_JURISDICTION', 'denial'),
)

_APPLICATION_STATUSES = (
    "'draft', 'submitted', 'needs_information', 'revisions_requested', "
    "'ready_for_review', 'under_review', 'approved', 'denied', 'withdrawn', "
    "'issued', 'returned', 'archived'"
)

_FINDING_TYPES = (
    "'missing_field', 'missing_document', 'unreadable', 'wrong_type', "
    "'duplicate', 'conflict', 'fee', 'low_confidence_extraction', 'judgment'"
)


def upgrade() -> None:
    op.create_table('application_comments',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('author_actor_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("visibility IN ('applicant', 'internal')", name=op.f('ck_application_comments_visibility_allowed')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_comments_application_id_applications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_comments'))
    )
    with op.batch_alter_table('application_comments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_comments_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_application_comments_correlation_id'), ['correlation_id'], unique=False)

    op.create_table('application_actions',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('occurred_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('reason_code_id', sa.String(length=64), nullable=True),
    sa.Column('reason_code', sa.String(length=48), nullable=True),
    sa.Column('reason_code_label', sa.String(length=160), nullable=True),
    sa.Column('reason_code_version', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('comment_id', sa.String(length=64), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_actions_application_id_applications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_actions'))
    )
    with op.batch_alter_table('application_actions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_actions_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_application_actions_correlation_id'), ['correlation_id'], unique=False)

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_constraint('status_allowed', type_='check')
        batch_op.create_check_constraint(
            'status_allowed', f"status IN ({_APPLICATION_STATUSES})"
        )
        batch_op.create_check_constraint(
            'priority_allowed', "priority IN ('normal', 'high')"
        )
        batch_op.add_column(sa.Column('priority', sa.String(length=16), nullable=False, server_default=sa.text("'normal'")))
        batch_op.add_column(sa.Column('owner_actor_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('status_before_archive', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('archived_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('archived_by_actor_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('archive_reason_code_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('archive_reason', sa.Text(), nullable=True))

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_applications_owner_actor_id'), ['owner_actor_id'], unique=False)

    with op.batch_alter_table('application_findings', schema=None) as batch_op:
        batch_op.drop_constraint('finding_type_allowed', type_='check')
        batch_op.create_check_constraint(
            'finding_type_allowed',
            f"finding_type IN ({_FINDING_TYPES})",
        )
        batch_op.create_check_constraint(
            'state_allowed',
            "state IN ('current', 'resolved', 'superseded')",
        )
        batch_op.add_column(sa.Column('state', sa.String(length=16), nullable=False, server_default=sa.text("'current'")))
        batch_op.add_column(sa.Column('revision_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('agent_run_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('superseded_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('waived_at', acme_city.persistence.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('waived_by_actor_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('waiver_reason_code_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('waiver_reason_code', sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column('waiver_reason_code_label', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('waiver_reason_code_version', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('waiver_reason', sa.Text(), nullable=True))

    with op.batch_alter_table('application_findings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_findings_agent_run_id'), ['agent_run_id'], unique=False)

    with op.batch_alter_table('reason_codes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code_type', sa.String(length=16), nullable=False, server_default=sa.text("'return'")))
        batch_op.create_check_constraint(
            'code_type_allowed',
            "code_type IN ('return', 'denial', 'waiver', 'revision', 'archive')",
        )

    # The explicit backfill: one statement per code the demonstration shipped
    # with.  It updates rows; it creates none.
    for code, code_type in REASON_CODE_BACKFILL:
        op.execute(
            "UPDATE reason_codes SET code_type = "
            f"'{code_type}' WHERE code = '{code}'"
        )

    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reason_code_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reason_code', sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column('reason_code_label', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('reason_code_version', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('waivers', sa.JSON(), nullable=True))

    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stale', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_column('stale')

    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.drop_column('waivers')
        batch_op.drop_column('reason_code_version')
        batch_op.drop_column('reason_code_label')
        batch_op.drop_column('reason_code')
        batch_op.drop_column('reason_code_id')

    with op.batch_alter_table('reason_codes', schema=None) as batch_op:
        batch_op.drop_constraint('code_type_allowed', type_='check')
        batch_op.drop_column('code_type')

    with op.batch_alter_table('application_findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_findings_agent_run_id'))

    with op.batch_alter_table('application_findings', schema=None) as batch_op:
        batch_op.drop_column('waiver_reason')
        batch_op.drop_column('waiver_reason_code_version')
        batch_op.drop_column('waiver_reason_code_label')
        batch_op.drop_column('waiver_reason_code')
        batch_op.drop_column('waiver_reason_code_id')
        batch_op.drop_column('waived_by_actor_id')
        batch_op.drop_column('waived_at')
        batch_op.drop_column('superseded_at')
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('agent_run_id')
        batch_op.drop_column('revision_number')
        batch_op.drop_column('state')
        batch_op.drop_constraint('state_allowed', type_='check')
        batch_op.drop_constraint('finding_type_allowed', type_='check')
        batch_op.create_check_constraint(
            'finding_type_allowed',
            "finding_type IN ('missing_field', 'missing_document', 'unreadable', "
            "'duplicate', 'conflict', 'low_confidence_extraction', 'judgment')",
        )

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_owner_actor_id'))

    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_column('archive_reason')
        batch_op.drop_column('archive_reason_code_id')
        batch_op.drop_column('archived_by_actor_id')
        batch_op.drop_column('archived_at')
        batch_op.drop_column('status_before_archive')
        batch_op.drop_column('owner_actor_id')
        batch_op.drop_column('priority')
        batch_op.drop_constraint('priority_allowed', type_='check')
        batch_op.drop_constraint('status_allowed', type_='check')
        batch_op.create_check_constraint(
            'status_allowed',
            "status IN ('draft', 'submitted', 'needs_information', 'ready_for_review', "
            "'under_review', 'approved', 'denied', 'withdrawn', 'issued')",
        )

    with op.batch_alter_table('application_actions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_actions_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_application_actions_application_id'))

    op.drop_table('application_actions')
    with op.batch_alter_table('application_comments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_comments_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_application_comments_application_id'))

    op.drop_table('application_comments')

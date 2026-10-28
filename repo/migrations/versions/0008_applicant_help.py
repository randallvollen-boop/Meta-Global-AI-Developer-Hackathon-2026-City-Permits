"""Parity phase 3 chat 1: the applicant help conversation.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28

Adds the three record groups the applicant help assistant needs:

* ``help_conversations``: one conversation per applicant and browser session,
  with the application or the permit type it is about;
* ``help_turns``: one question and the answer the server gave, with the
  sources the answer was drawn from and the hash of the source bundle;
* ``help_requests``: a question the applicant asked a person at the City to
  answer.

The migration creates the empty tables and no row of its own: the
conversation, the turn and the help request are written by the applicant who
makes them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('help_conversations',
    sa.Column('owner_actor_id', sa.String(length=64), nullable=False),
    sa.Column('owner_session_hash', sa.String(length=64), nullable=False, server_default=''),
    sa.Column('application_id', sa.String(length=64), nullable=True),
    sa.Column('permit_type_key', sa.String(length=64), nullable=True),
    sa.Column('placement', sa.String(length=16), nullable=False, server_default='chooser'),
    sa.Column('turn_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("placement IN ('chooser', 'form', 'track')", name=op.f('ck_help_conversations_placement_allowed')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_help_conversations_application_id_applications'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_help_conversations'))
    )
    with op.batch_alter_table('help_conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_help_conversations_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_conversations_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_conversations_owner_actor_id'), ['owner_actor_id'], unique=False)

    op.create_table('help_turns',
    sa.Column('conversation_id', sa.String(length=64), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False, server_default='no_match'),
    sa.Column('answer', sa.JSON(), nullable=True),
    sa.Column('sources', sa.JSON(), nullable=True),
    sa.Column('bundle_hash', sa.String(length=64), nullable=True),
    sa.Column('mode', sa.String(length=16), nullable=False, server_default='fallback'),
    sa.Column('turn_number', sa.Integer(), nullable=False, server_default='1'),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("outcome IN ('matched', 'no_match')", name=op.f('ck_help_turns_outcome_allowed')),
    sa.CheckConstraint("mode IN ('fallback', 'replay', 'live')", name=op.f('ck_help_turns_mode_allowed')),
    sa.ForeignKeyConstraint(['conversation_id'], ['help_conversations.id'], name=op.f('fk_help_turns_conversation_id_help_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_help_turns'))
    )
    with op.batch_alter_table('help_turns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_help_turns_conversation_id'), ['conversation_id'], unique=False)

    op.create_table('help_requests',
    sa.Column('conversation_id', sa.String(length=64), nullable=False),
    sa.Column('applicant_actor_id', sa.String(length=64), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
    sa.Column('reply', sa.Text(), nullable=True),
    sa.Column('answered_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('answered_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'answered')", name=op.f('ck_help_requests_status_allowed')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_help_requests_application_id_applications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['help_conversations.id'], name=op.f('fk_help_requests_conversation_id_help_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_help_requests'))
    )
    with op.batch_alter_table('help_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_help_requests_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_requests_applicant_actor_id'), ['applicant_actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_requests_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_help_requests_conversation_id'), ['conversation_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('help_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_help_requests_conversation_id'))
        batch_op.drop_index(batch_op.f('ix_help_requests_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_help_requests_applicant_actor_id'))
        batch_op.drop_index(batch_op.f('ix_help_requests_application_id'))
    op.drop_table('help_requests')

    with op.batch_alter_table('help_turns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_help_turns_conversation_id'))
    op.drop_table('help_turns')

    with op.batch_alter_table('help_conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_help_conversations_owner_actor_id'))
        batch_op.drop_index(batch_op.f('ix_help_conversations_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_help_conversations_application_id'))
    op.drop_table('help_conversations')

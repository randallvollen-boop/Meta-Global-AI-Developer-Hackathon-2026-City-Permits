"""Initial governed-foundation schema.

Creates every P0 object group: governance, assignment and session tables,
source intake tables, registry MDM tables, change and outbox tables, permit
workflow tables, rule and finance tables, model run traces and the append-only
audit trail.

Design rules that the DDL below encodes:

* every mutable aggregate carries an integer ``version`` that starts at one;
* every immutable event or snapshot carries a stable identifier, a correlation
  identifier and a creation timestamp;
* money is stored as integer cents with an explicit three letter currency;
* source update time, effective time and receipt time are separate nullable
  columns, so an unknown business time stays unknown;
* foreign keys reference validated records and are enforced by SQLite because
  the application turns ``PRAGMA foreign_keys`` on for every connection.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import acme_city.persistence.types

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('actors',
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('fictional', sa.Boolean(), nullable=False),
    sa.Column('selectable', sa.Boolean(), nullable=False),
    sa.Column('deactivated_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('deactivated_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_actors')),
    sa.UniqueConstraint('actor_id', name=op.f('uq_actors_actor_id'))
    )
    op.create_table('addresses',
    sa.Column('address_id', sa.String(length=64), nullable=False),
    sa.Column('street_number', sa.String(length=32), nullable=True),
    sa.Column('street_name', sa.String(length=160), nullable=True),
    sa.Column('street_type', sa.String(length=48), nullable=True),
    sa.Column('unit_type', sa.String(length=32), nullable=True),
    sa.Column('unit_number', sa.String(length=32), nullable=True),
    sa.Column('municipality', sa.String(length=96), nullable=True),
    sa.Column('region', sa.String(length=48), nullable=True),
    sa.Column('postcode', sa.String(length=24), nullable=True),
    sa.Column('source_string', sa.String(length=320), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_addresses')),
    sa.UniqueConstraint('address_id', name=op.f('uq_addresses_address_id'))
    )
    op.create_table('assignments',
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('responsibility', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('queue_id', sa.String(length=64), nullable=True),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('supersedes_assignment_id', sa.String(length=64), nullable=True),
    sa.Column('superseded_by_assignment_id', sa.String(length=64), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("responsibility IN ('owner', 'steward', 'delegate', 'custodian', 'escalation')", name=op.f('ck_assignments_responsibility_allowed')),
    sa.CheckConstraint("subject_type IN ('domain', 'dataset')", name=op.f('ck_assignments_subject_type_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assignments'))
    )
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assignments_subject_id'), ['subject_id'], unique=False)

    op.create_table('audit_events',
    sa.Column('occurred_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('actor_role_ids', sa.JSON(), nullable=True),
    sa.Column('action', sa.String(length=120), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=True),
    sa.Column('target_id', sa.String(length=96), nullable=True),
    sa.Column('before_version', sa.Integer(), nullable=True),
    sa.Column('after_version', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('references', sa.JSON(), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('denial_reason', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("outcome IN ('accepted', 'denied')", name=op.f('ck_audit_events_outcome_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_occurred_at'), ['occurred_at'], unique=False)

    op.create_table('authority_policies',
    sa.Column('policy_id', sa.String(length=96), nullable=False),
    sa.Column('field_group', sa.String(length=200), nullable=False),
    sa.Column('domain_id', sa.String(length=64), nullable=True),
    sa.Column('authoritative_source_system_id', sa.String(length=64), nullable=True),
    sa.Column('authoritative_component_id', sa.String(length=64), nullable=True),
    sa.Column('authoritative_dataset_key', sa.String(length=96), nullable=True),
    sa.Column('change_destination', sa.String(length=240), nullable=False),
    sa.Column('user_action', sa.String(length=240), nullable=False),
    sa.Column('requires_source_ack', sa.Boolean(), nullable=False),
    sa.Column('decision_relevant', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('approver_actor_id', sa.String(length=64), nullable=True),
    sa.Column('authoritative_action_roles', sa.JSON(), nullable=True),
    sa.Column('published_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_authority_policies')),
    sa.UniqueConstraint('policy_id', name=op.f('uq_authority_policies_policy_id'))
    )
    with op.batch_alter_table('authority_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_authority_policies_domain_id'), ['domain_id'], unique=False)

    op.create_table('canonical_entities',
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=48), nullable=False),
    sa.Column('label', sa.String(length=240), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_canonical_entities')),
    sa.UniqueConstraint('entity_id', name=op.f('uq_canonical_entities_entity_id'))
    )
    op.create_table('change_cases',
    sa.Column('target_type', sa.String(length=48), nullable=False),
    sa.Column('target_id', sa.String(length=96), nullable=False),
    sa.Column('change_kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('proposed_value', sa.JSON(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('requester_actor_id', sa.String(length=64), nullable=True),
    sa.Column('assignee_actor_id', sa.String(length=64), nullable=True),
    sa.Column('approver_actor_id', sa.String(length=64), nullable=True),
    sa.Column('destination', sa.String(length=240), nullable=True),
    sa.Column('expected_version', sa.Integer(), nullable=True),
    sa.Column('due_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("change_kind IN ('factual', 'identity')", name=op.f('ck_change_cases_change_kind_allowed')),
    sa.CheckConstraint("status IN ('requested', 'in_review', 'awaiting_approval', 'approved', 'sent_to_source', 'source_acknowledged', 'registry_committed', 'published', 'closed', 'rejected', 'synchronization_failed')", name=op.f('ck_change_cases_status_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_cases'))
    )
    with op.batch_alter_table('change_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_change_cases_assignee_actor_id'), ['assignee_actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_change_cases_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_change_cases_scenario_id'), ['scenario_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_change_cases_target_id'), ['target_id'], unique=False)

    op.create_table('demo_environment',
    sa.Column('environment_id', sa.String(length=64), nullable=False),
    sa.Column('fictional_demo', sa.Boolean(), nullable=False),
    sa.Column('fixture_version', sa.String(length=64), nullable=True),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('updated_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_demo_environment')),
    sa.UniqueConstraint('environment_id', name=op.f('uq_demo_environment_environment_id'))
    )
    op.create_table('domains',
    sa.Column('domain_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('accountable_owner_actor_id', sa.String(length=64), nullable=True),
    sa.Column('steward_queue_id', sa.String(length=64), nullable=True),
    sa.Column('system_custodian_actor_id', sa.String(length=64), nullable=True),
    sa.Column('default_source_system_id', sa.String(length=64), nullable=True),
    sa.Column('default_dataset_key', sa.String(length=96), nullable=True),
    sa.Column('owner_strategy', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.CheckConstraint('steward_queue_id IS NULL OR accountable_owner_actor_id IS NOT NULL', name=op.f('ck_domains_owner_present_when_queue_bound')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_domains')),
    sa.UniqueConstraint('domain_id', name=op.f('uq_domains_domain_id'))
    )
    with op.batch_alter_table('domains', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_domains_steward_queue_id'), ['steward_queue_id'], unique=False)

    op.create_table('fee_schedule_versions',
    sa.Column('fee_schedule_id', sa.String(length=64), nullable=False),
    sa.Column('version_label', sa.String(length=64), nullable=False),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('definition', sa.JSON(), nullable=True),
    sa.Column('approver_actor_id', sa.String(length=64), nullable=True),
    sa.Column('author_actor_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_fee_schedule_versions_currency_is_iso')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fee_schedule_versions')),
    sa.UniqueConstraint('fee_schedule_id', 'version_label', name=op.f('uq_fee_schedule_versions_fee_schedule_id'))
    )
    op.create_table('governance_issues',
    sa.Column('subject_type', sa.String(length=48), nullable=False),
    sa.Column('subject_id', sa.String(length=96), nullable=False),
    sa.Column('issue_type', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('responsible_queue_id', sa.String(length=64), nullable=True),
    sa.Column('assigned_actor_id', sa.String(length=64), nullable=True),
    sa.Column('blocking', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_governance_issues'))
    )
    with op.batch_alter_table('governance_issues', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_governance_issues_scenario_id'), ['scenario_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_governance_issues_subject_id'), ['subject_id'], unique=False)

    op.create_table('impact_reviews',
    sa.Column('target_type', sa.String(length=48), nullable=False),
    sa.Column('target_id', sa.String(length=96), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('assigned_actor_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_impact_reviews'))
    )
    with op.batch_alter_table('impact_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_impact_reviews_scenario_id'), ['scenario_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_impact_reviews_target_id'), ['target_id'], unique=False)

    op.create_table('model_runs',
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=96), nullable=False),
    sa.Column('prompt_version', sa.String(length=64), nullable=False),
    sa.Column('schema_version', sa.String(length=64), nullable=False),
    sa.Column('input_refs', sa.JSON(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('validation_result', sa.JSON(), nullable=True),
    sa.Column('usage', sa.JSON(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('completed_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('fixture_version', sa.String(length=64), nullable=True),
    sa.Column('replay_of_run_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("mode IN ('live', 'replay', 'cached')", name=op.f('ck_model_runs_mode_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_runs'))
    )
    with op.batch_alter_table('model_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_runs_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_runs_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('parcels',
    sa.Column('parcel_id', sa.String(length=64), nullable=False),
    sa.Column('jurisdiction_id', sa.String(length=64), nullable=False),
    sa.Column('source_parcel_number', sa.String(length=96), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('valid_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('valid_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parcels')),
    sa.UniqueConstraint('parcel_id', name=op.f('uq_parcels_parcel_id'))
    )
    op.create_table('permissions',
    sa.Column('permission_id', sa.String(length=96), nullable=False),
    sa.Column('action', sa.String(length=96), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('sensitive', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions')),
    sa.UniqueConstraint('action', name=op.f('uq_permissions_action')),
    sa.UniqueConstraint('permission_id', name=op.f('uq_permissions_permission_id'))
    )
    op.create_table('permit_types',
    sa.Column('permit_type_id', sa.String(length=64), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('review_route', sa.String(length=160), nullable=False),
    sa.Column('required_fields', sa.JSON(), nullable=True),
    sa.Column('required_documents', sa.JSON(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permit_types')),
    sa.UniqueConstraint('key', name=op.f('uq_permit_types_key')),
    sa.UniqueConstraint('permit_type_id', name=op.f('uq_permit_types_permit_type_id'))
    )
    op.create_table('roles',
    sa.Column('role_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=128), nullable=False),
    sa.Column('boundary', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('role_id', name=op.f('uq_roles_role_id'))
    )
    op.create_table('source_contracts',
    sa.Column('contract_id', sa.String(length=96), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_key', sa.String(length=96), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('domain_id', sa.String(length=64), nullable=True),
    sa.Column('accountable_owner_actor_id', sa.String(length=64), nullable=True),
    sa.Column('steward_queue_id', sa.String(length=64), nullable=True),
    sa.Column('system_custodian_actor_id', sa.String(length=64), nullable=True),
    sa.Column('authority_policy_id', sa.String(length=96), nullable=True),
    sa.Column('correction_route', sa.Text(), nullable=True),
    sa.Column('business_key_fields', sa.JSON(), nullable=True),
    sa.Column('schema_version', sa.String(length=32), nullable=True),
    sa.Column('required_fields', sa.JSON(), nullable=True),
    sa.Column('allowed_values', sa.JSON(), nullable=True),
    sa.Column('date_meanings', sa.JSON(), nullable=True),
    sa.Column('field_classes', sa.JSON(), nullable=True),
    sa.Column('registration_state', sa.String(length=32), nullable=False),
    sa.Column('registered_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("registration_state IN ('complete', 'incomplete')", name=op.f('ck_source_contracts_registration_state_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_contracts')),
    sa.UniqueConstraint('contract_id', name=op.f('uq_source_contracts_contract_id')),
    sa.UniqueConstraint('source_system_id', 'dataset_key', name=op.f('uq_source_contracts_source_system_id'))
    )
    with op.batch_alter_table('source_contracts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_source_contracts_source_system_id'), ['source_system_id'], unique=False)

    op.create_table('source_systems',
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('simulated', sa.Boolean(), nullable=False),
    sa.Column('incoming', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_systems')),
    sa.UniqueConstraint('source_system_id', name=op.f('uq_source_systems_source_system_id'))
    )
    op.create_table('actor_grants',
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('permission_id', sa.String(length=96), nullable=False),
    sa.Column('domain_id', sa.String(length=64), nullable=True),
    sa.Column('record_scope', sa.JSON(), nullable=True),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('granted_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['actors.actor_id'], name=op.f('fk_actor_grants_actor_id_actors'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.permission_id'], name=op.f('fk_actor_grants_permission_id_permissions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_actor_grants'))
    )
    with op.batch_alter_table('actor_grants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_actor_grants_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_actor_grants_domain_id'), ['domain_id'], unique=False)

    op.create_table('actor_roles',
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('role_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['actors.actor_id'], name=op.f('fk_actor_roles_actor_id_actors'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.role_id'], name=op.f('fk_actor_roles_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_actor_roles')),
    sa.UniqueConstraint('actor_id', 'role_id', name=op.f('uq_actor_roles_actor_id'))
    )
    op.create_table('audit_references',
    sa.Column('event_id', sa.String(length=64), nullable=False),
    sa.Column('reference_type', sa.String(length=48), nullable=False),
    sa.Column('reference_id', sa.String(length=96), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['audit_events.id'], name=op.f('fk_audit_references_event_id_audit_events'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_references'))
    )
    with op.batch_alter_table('audit_references', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_references_event_id'), ['event_id'], unique=False)

    op.create_table('change_dependencies',
    sa.Column('change_case_id', sa.String(length=64), nullable=False),
    sa.Column('consumer_type', sa.String(length=48), nullable=False),
    sa.Column('consumer_id', sa.String(length=96), nullable=False),
    sa.Column('event_id', sa.String(length=96), nullable=True),
    sa.Column('invalidation_state', sa.String(length=32), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['change_case_id'], ['change_cases.id'], name=op.f('fk_change_dependencies_change_case_id_change_cases'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_dependencies'))
    )
    with op.batch_alter_table('change_dependencies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_change_dependencies_change_case_id'), ['change_case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_change_dependencies_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('crosswalks',
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=48), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('source_dataset_key', sa.String(length=96), nullable=True),
    sa.Column('source_record_id', sa.String(length=128), nullable=False),
    sa.Column('link_status', sa.String(length=32), nullable=False),
    sa.Column('decision', sa.Text(), nullable=True),
    sa.Column('decision_actor_id', sa.String(length=64), nullable=True),
    sa.Column('decided_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('expected_version', sa.Integer(), nullable=True),
    sa.Column('valid_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('valid_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('superseded_by_crosswalk_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("link_status IN ('proposed', 'approved', 'rejected', 'superseded', 'removed', 'no_match')", name=op.f('ck_crosswalks_link_status_allowed')),
    sa.ForeignKeyConstraint(['entity_id'], ['canonical_entities.entity_id'], name=op.f('fk_crosswalks_entity_id_canonical_entities'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crosswalks'))
    )
    with op.batch_alter_table('crosswalks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_crosswalks_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('evidence_references',
    sa.Column('run_id', sa.String(length=64), nullable=True),
    sa.Column('evidence_kind', sa.String(length=48), nullable=False),
    sa.Column('entity_type', sa.String(length=48), nullable=False),
    sa.Column('entity_id', sa.String(length=96), nullable=False),
    sa.Column('path', sa.String(length=240), nullable=False),
    sa.Column('label', sa.String(length=240), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('fictional_demo', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['model_runs.id'], name=op.f('fk_evidence_references_run_id_model_runs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_references'))
    )
    with op.batch_alter_table('evidence_references', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evidence_references_run_id'), ['run_id'], unique=False)

    op.create_table('ingestion_runs',
    sa.Column('ingestion_run_id', sa.String(length=64), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_key', sa.String(length=96), nullable=False),
    sa.Column('contract_id', sa.String(length=96), nullable=True),
    sa.Column('started_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('completed_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('received', sa.Integer(), nullable=False),
    sa.Column('accepted', sa.Integer(), nullable=False),
    sa.Column('unchanged', sa.Integer(), nullable=False),
    sa.Column('quarantined', sa.Integer(), nullable=False),
    sa.Column('unresolved', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['contract_id'], ['source_contracts.contract_id'], name=op.f('fk_ingestion_runs_contract_id_source_contracts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_system_id'], ['source_systems.source_system_id'], name=op.f('fk_ingestion_runs_source_system_id_source_systems'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('ingestion_run_id', name=op.f('pk_ingestion_runs'))
    )
    with op.batch_alter_table('ingestion_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ingestion_runs_correlation_id'), ['correlation_id'], unique=False)

    op.create_table('model_inputs',
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('input_type', sa.String(length=48), nullable=False),
    sa.Column('input_ref', sa.String(length=240), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['model_runs.id'], name=op.f('fk_model_inputs_run_id_model_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_inputs'))
    )
    with op.batch_alter_table('model_inputs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_inputs_run_id'), ['run_id'], unique=False)

    op.create_table('model_outputs',
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('validation_errors', sa.JSON(), nullable=True),
    sa.Column('validation_state', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['model_runs.id'], name=op.f('fk_model_outputs_run_id_model_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_outputs'))
    )
    with op.batch_alter_table('model_outputs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_outputs_run_id'), ['run_id'], unique=False)

    op.create_table('outbox_deliveries',
    sa.Column('change_case_id', sa.String(length=64), nullable=True),
    sa.Column('destination', sa.String(length=160), nullable=False),
    sa.Column('payload_version', sa.Integer(), nullable=False),
    sa.Column('retry_key', sa.String(length=160), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('dispatched_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('acknowledged_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'dispatched', 'acknowledged', 'failed')", name=op.f('ck_outbox_deliveries_status_allowed')),
    sa.ForeignKeyConstraint(['change_case_id'], ['change_cases.id'], name=op.f('fk_outbox_deliveries_change_case_id_change_cases'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_deliveries')),
    sa.UniqueConstraint('retry_key', name=op.f('uq_outbox_deliveries_retry_key'))
    )
    with op.batch_alter_table('outbox_deliveries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_outbox_deliveries_change_case_id'), ['change_case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_outbox_deliveries_correlation_id'), ['correlation_id'], unique=False)

    op.create_table('parcel_addresses',
    sa.Column('parcel_id', sa.String(length=64), nullable=False),
    sa.Column('address_id', sa.String(length=64), nullable=False),
    sa.Column('relationship_type', sa.String(length=48), nullable=False),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('evidence_ref', sa.String(length=240), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['address_id'], ['addresses.id'], name=op.f('fk_parcel_addresses_address_id_addresses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcels.id'], name=op.f('fk_parcel_addresses_parcel_id_parcels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parcel_addresses'))
    )
    with op.batch_alter_table('parcel_addresses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_parcel_addresses_address_id'), ['address_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_parcel_addresses_parcel_id'), ['parcel_id'], unique=False)

    op.create_table('parties',
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('party_type', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=240), nullable=False),
    sa.Column('legal_name', sa.String(length=240), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=True),
    sa.Column('source_record_id', sa.String(length=96), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("party_type IN ('person', 'organization')", name=op.f('ck_parties_party_type_allowed')),
    sa.ForeignKeyConstraint(['entity_id'], ['canonical_entities.entity_id'], name=op.f('fk_parties_entity_id_canonical_entities'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parties'))
    )
    op.create_table('provenance',
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('attribute_path', sa.String(length=200), nullable=False),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('source_field', sa.String(length=160), nullable=True),
    sa.Column('authority_policy_id', sa.String(length=96), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('valid_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('valid_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['canonical_entities.entity_id'], name=op.f('fk_provenance_entity_id_canonical_entities'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provenance'))
    )
    op.create_table('review_tasks',
    sa.Column('change_case_id', sa.String(length=64), nullable=True),
    sa.Column('assignee_actor_id', sa.String(length=64), nullable=True),
    sa.Column('task_type', sa.String(length=48), nullable=False),
    sa.Column('target_type', sa.String(length=48), nullable=True),
    sa.Column('target_id', sa.String(length=96), nullable=True),
    sa.Column('deduplication_key', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('due_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['change_case_id'], ['change_cases.id'], name=op.f('fk_review_tasks_change_case_id_change_cases'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_tasks')),
    sa.UniqueConstraint('deduplication_key', name=op.f('uq_review_tasks_deduplication_key'))
    )
    with op.batch_alter_table('review_tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_tasks_assignee_actor_id'), ['assignee_actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_review_tasks_change_case_id'), ['change_case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_review_tasks_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('role_permissions',
    sa.Column('role_id', sa.String(length=64), nullable=False),
    sa.Column('permission_id', sa.String(length=96), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.permission_id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.role_id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_permissions')),
    sa.UniqueConstraint('role_id', 'permission_id', name=op.f('uq_role_permissions_role_id'))
    )
    op.create_table('rule_versions',
    sa.Column('rule_id', sa.String(length=64), nullable=False),
    sa.Column('permit_type_id', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('citation', sa.String(length=120), nullable=False),
    sa.Column('field_path', sa.String(length=160), nullable=True),
    sa.Column('operator', sa.String(length=32), nullable=True),
    sa.Column('limit_value', sa.String(length=64), nullable=True),
    sa.Column('on_violate', sa.String(length=32), nullable=True),
    sa.Column('condition', sa.JSON(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('condition_note', sa.Text(), nullable=True),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('approver_actor_id', sa.String(length=64), nullable=True),
    sa.Column('author_actor_id', sa.String(length=64), nullable=True),
    sa.Column('source_mapping', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'published', 'retired')", name=op.f('ck_rule_versions_status_allowed')),
    sa.ForeignKeyConstraint(['permit_type_id'], ['permit_types.id'], name=op.f('fk_rule_versions_permit_type_id_permit_types'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rule_versions')),
    sa.UniqueConstraint('rule_id', 'effective_from', name=op.f('uq_rule_versions_rule_id'))
    )
    op.create_table('sessions',
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('issued_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('expires_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('last_seen_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('revoked_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('user_agent_hint', sa.String(length=240), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['actors.actor_id'], name=op.f('fk_sessions_actor_id_actors'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('session_id', name=op.f('uq_sessions_session_id'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_expires_at'), ['expires_at'], unique=False)

    op.create_table('source_commands',
    sa.Column('change_case_id', sa.String(length=64), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('expected_source_version', sa.String(length=64), nullable=True),
    sa.Column('operation', sa.String(length=96), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('retry_key', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('response', sa.JSON(), nullable=True),
    sa.Column('accepted_source_version', sa.String(length=64), nullable=True),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'timeout', 'conflict')", name=op.f('ck_source_commands_status_allowed')),
    sa.ForeignKeyConstraint(['change_case_id'], ['change_cases.id'], name=op.f('fk_source_commands_change_case_id_change_cases'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_commands')),
    sa.UniqueConstraint('retry_key', name=op.f('uq_source_commands_retry_key'))
    )
    with op.batch_alter_table('source_commands', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_source_commands_change_case_id'), ['change_case_id'], unique=False)

    op.create_table('steward_queues',
    sa.Column('queue_id', sa.String(length=64), nullable=False),
    sa.Column('domain_id', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('primary_actor_id', sa.String(length=64), nullable=True),
    sa.Column('delegate_actor_id', sa.String(length=64), nullable=True),
    sa.Column('escalation_actor_id', sa.String(length=64), nullable=True),
    sa.Column('cross_domain_escalation_actor_id', sa.String(length=64), nullable=True),
    sa.Column('first_review_target_quantity', sa.Integer(), nullable=False),
    sa.Column('first_review_target_unit', sa.String(length=32), nullable=False),
    sa.Column('first_review_target_calendar_basis', sa.String(length=64), nullable=False),
    sa.Column('configurable', sa.Boolean(), nullable=False),
    sa.Column('service_promise', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.domain_id'], name=op.f('fk_steward_queues_domain_id_domains'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_steward_queues')),
    sa.UniqueConstraint('queue_id', name=op.f('uq_steward_queues_queue_id'))
    )
    with op.batch_alter_table('steward_queues', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_steward_queues_domain_id'), ['domain_id'], unique=False)

    op.create_table('applications',
    sa.Column('source_application_number', sa.String(length=96), nullable=False),
    sa.Column('permit_type_id', sa.String(length=64), nullable=False),
    sa.Column('initial_submitted_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('revision_submitted_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('submitted_facts', sa.JSON(), nullable=True),
    sa.Column('applicant_party_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'submitted', 'needs_information', 'ready_for_review', 'under_review', 'approved', 'denied', 'withdrawn', 'issued')", name=op.f('ck_applications_status_allowed')),
    sa.ForeignKeyConstraint(['applicant_party_id'], ['parties.id'], name=op.f('fk_applications_applicant_party_id_parties'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['permit_type_id'], ['permit_types.id'], name=op.f('fk_applications_permit_type_id_permit_types'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications')),
    sa.UniqueConstraint('source_application_number', name=op.f('uq_applications_source_application_number'))
    )
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_applications_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('consumer_acknowledgements',
    sa.Column('delivery_id', sa.String(length=64), nullable=False),
    sa.Column('consumer_id', sa.String(length=96), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('acknowledged_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['delivery_id'], ['outbox_deliveries.id'], name=op.f('fk_consumer_acknowledgements_delivery_id_outbox_deliveries'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consumer_acknowledgements'))
    )
    with op.batch_alter_table('consumer_acknowledgements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_consumer_acknowledgements_delivery_id'), ['delivery_id'], unique=False)

    op.create_table('credentials',
    sa.Column('credential_id', sa.String(length=64), nullable=False),
    sa.Column('holder_party_id', sa.String(length=64), nullable=False),
    sa.Column('credential_type', sa.String(length=48), nullable=False),
    sa.Column('issuing_authority_id', sa.String(length=96), nullable=False),
    sa.Column('number', sa.String(length=96), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('valid_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('valid_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('verified_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('source_system_id', sa.String(length=64), nullable=True),
    sa.Column('source_record_id', sa.String(length=96), nullable=True),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['holder_party_id'], ['parties.id'], name=op.f('fk_credentials_holder_party_id_parties'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credentials')),
    sa.UniqueConstraint('credential_id', name=op.f('uq_credentials_credential_id'))
    )
    with op.batch_alter_table('credentials', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_credentials_holder_party_id'), ['holder_party_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_credentials_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('finance_accounts',
    sa.Column('account_id', sa.String(length=64), nullable=False),
    sa.Column('source_account_id', sa.String(length=96), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('party_id', sa.String(length=64), nullable=True),
    sa.Column('account_role', sa.String(length=48), nullable=False),
    sa.Column('source_version', sa.String(length=64), nullable=True),
    sa.Column('link_status', sa.String(length=32), nullable=False),
    sa.Column('link_decision', sa.Text(), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_finance_accounts_party_id_parties'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_finance_accounts')),
    sa.UniqueConstraint('account_id', name=op.f('uq_finance_accounts_account_id'))
    )
    with op.batch_alter_table('finance_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_finance_accounts_party_id'), ['party_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_finance_accounts_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('party_aliases',
    sa.Column('party_id', sa.String(length=64), nullable=False),
    sa.Column('alias_value', sa.String(length=240), nullable=False),
    sa.Column('alias_type', sa.String(length=48), nullable=False),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('recorded_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_party_aliases_party_id_parties'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_party_aliases'))
    )
    with op.batch_alter_table('party_aliases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_party_aliases_party_id'), ['party_id'], unique=False)

    op.create_table('party_contacts',
    sa.Column('party_id', sa.String(length=64), nullable=False),
    sa.Column('contact_type', sa.String(length=48), nullable=False),
    sa.Column('value', sa.String(length=320), nullable=False),
    sa.Column('verification_state', sa.String(length=32), nullable=False),
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('valid_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('valid_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_party_contacts_party_id_parties'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_party_contacts'))
    )
    with op.batch_alter_table('party_contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_party_contacts_party_id'), ['party_id'], unique=False)

    op.create_table('source_observations',
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_key', sa.String(length=96), nullable=False),
    sa.Column('ingestion_run_id', sa.String(length=64), nullable=True),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('numerator', sa.Integer(), nullable=False),
    sa.Column('denominator', sa.Integer(), nullable=False),
    sa.Column('observed_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('source_updated_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('received_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['ingestion_run_id'], ['ingestion_runs.ingestion_run_id'], name=op.f('fk_source_observations_ingestion_run_id_ingestion_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_system_id'], ['source_systems.source_system_id'], name=op.f('fk_source_observations_source_system_id_source_systems'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_observations'))
    )
    op.create_table('source_snapshots',
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('ingestion_run_id', sa.String(length=64), nullable=True),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('source_dataset_id', sa.String(length=96), nullable=False),
    sa.Column('source_record_id', sa.String(length=128), nullable=False),
    sa.Column('source_record_version', sa.String(length=64), nullable=True),
    sa.Column('source_updated_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('effective_from', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('effective_to', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('ingested_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('raw_payload_ref', sa.String(length=240), nullable=True),
    sa.Column('raw_payload', sa.JSON(), nullable=True),
    sa.Column('record_status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("record_status IN ('accepted', 'unchanged', 'quarantined', 'unresolved', 'staged')", name=op.f('ck_source_snapshots_record_status_allowed')),
    sa.ForeignKeyConstraint(['ingestion_run_id'], ['ingestion_runs.ingestion_run_id'], name=op.f('fk_source_snapshots_ingestion_run_id_ingestion_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_system_id'], ['source_systems.source_system_id'], name=op.f('fk_source_snapshots_source_system_id_source_systems'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('source_snapshot_id', name=op.f('pk_source_snapshots')),
    sa.UniqueConstraint('source_system_id', 'source_dataset_id', 'source_record_id', 'source_record_version', 'payload_hash', name='uq_source_snapshot_identity')
    )
    with op.batch_alter_table('source_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_source_snapshots_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_source_snapshots_scenario_id'), ['scenario_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_source_snapshots_source_dataset_id'), ['source_dataset_id'], unique=False)

    op.create_table('application_parties',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('party_id', sa.String(length=64), nullable=False),
    sa.Column('party_role', sa.String(length=48), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('authority_evidence_ref', sa.String(length=240), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_parties_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_application_parties_party_id_parties'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_parties'))
    )
    with op.batch_alter_table('application_parties', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_parties_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_application_parties_party_id'), ['party_id'], unique=False)

    op.create_table('application_revisions',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('submitted_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('submitted_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('date_basis', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_revisions_application_id_applications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_revisions'))
    )
    with op.batch_alter_table('application_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_revisions_application_id'), ['application_id'], unique=False)

    op.create_table('application_sites',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('parcel_id', sa.String(length=64), nullable=True),
    sa.Column('address_id', sa.String(length=64), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('resolution_status', sa.String(length=32), nullable=False),
    sa.Column('submitted_address_text', sa.String(length=320), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['address_id'], ['addresses.id'], name=op.f('fk_application_sites_address_id_addresses'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_sites_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcels.id'], name=op.f('fk_application_sites_parcel_id_parcels'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_sites'))
    )
    with op.batch_alter_table('application_sites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_sites_application_id'), ['application_id'], unique=False)

    op.create_table('assessments',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('billed_party_id', sa.String(length=64), nullable=True),
    sa.Column('fee_schedule_version_id', sa.String(length=64), nullable=False),
    sa.Column('input_versions', sa.JSON(), nullable=True),
    sa.Column('assessed_total_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_assessments_currency_is_iso')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_assessments_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['billed_party_id'], ['parties.id'], name=op.f('fk_assessments_billed_party_id_parties'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['fee_schedule_version_id'], ['fee_schedule_versions.id'], name=op.f('fk_assessments_fee_schedule_version_id_fee_schedule_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assessments'))
    )
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assessments_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assessments_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assessments_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('documents',
    sa.Column('application_id', sa.String(length=64), nullable=True),
    sa.Column('document_type', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('file_ref', sa.String(length=240), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('received_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('uploaded_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('fictional_demo', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_documents_application_id_applications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_application_id'), ['application_id'], unique=False)

    op.create_table('finance_account_links',
    sa.Column('account_id', sa.String(length=64), nullable=False),
    sa.Column('party_id', sa.String(length=64), nullable=False),
    sa.Column('link_status', sa.String(length=32), nullable=False),
    sa.Column('decided_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('decided_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('source_version', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("link_status IN ('proposed', 'approved', 'rejected', 'superseded')", name=op.f('ck_finance_account_links_link_status_allowed')),
    sa.ForeignKeyConstraint(['account_id'], ['finance_accounts.id'], name=op.f('fk_finance_account_links_account_id_finance_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_finance_account_links_party_id_parties'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_finance_account_links'))
    )
    with op.batch_alter_table('finance_account_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_finance_account_links_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_finance_account_links_party_id'), ['party_id'], unique=False)

    op.create_table('match_proposals',
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('candidate_ids', sa.JSON(), nullable=True),
    sa.Column('compared_fields', sa.JSON(), nullable=True),
    sa.Column('supporting_evidence', sa.JSON(), nullable=True),
    sa.Column('conflicting_evidence', sa.JSON(), nullable=True),
    sa.Column('method', sa.String(length=48), nullable=False),
    sa.Column('model_run_id', sa.String(length=64), nullable=True),
    sa.Column('proposal_score', sa.Float(), nullable=True),
    sa.Column('score_is_calibrated', sa.Boolean(), nullable=False),
    sa.Column('disposition', sa.String(length=32), nullable=False),
    sa.Column('created_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['source_snapshot_id'], ['source_snapshots.source_snapshot_id'], name=op.f('fk_match_proposals_source_snapshot_id_source_snapshots'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_match_proposals'))
    )
    with op.batch_alter_table('match_proposals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_match_proposals_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_proposals_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('payments',
    sa.Column('source_transaction_id', sa.String(length=96), nullable=False),
    sa.Column('source_system_id', sa.String(length=64), nullable=False),
    sa.Column('source_event_id', sa.String(length=96), nullable=True),
    sa.Column('source_event_version', sa.String(length=64), nullable=True),
    sa.Column('payer_account_id', sa.String(length=64), nullable=True),
    sa.Column('party_id', sa.String(length=64), nullable=True),
    sa.Column('paid_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('settlement_status', sa.String(length=32), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("settlement_status IN ('unsettled', 'settled', 'reversed', 'failed')", name=op.f('ck_payments_settlement_status_allowed')),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_payments_currency_is_iso')),
    sa.ForeignKeyConstraint(['party_id'], ['parties.id'], name=op.f('fk_payments_party_id_parties'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['payer_account_id'], ['finance_accounts.id'], name=op.f('fk_payments_payer_account_id_finance_accounts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('source_transaction_id', name=op.f('uq_payments_source_transaction_id'))
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_payer_account_id'), ['payer_account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('quarantine_errors',
    sa.Column('source_snapshot_id', sa.String(length=64), nullable=False),
    sa.Column('field_path', sa.String(length=160), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('responsible_queue_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['source_snapshot_id'], ['source_snapshots.source_snapshot_id'], name=op.f('fk_quarantine_errors_source_snapshot_id_source_snapshots'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quarantine_errors'))
    )
    op.create_table('assessment_lines',
    sa.Column('assessment_id', sa.String(length=64), nullable=False),
    sa.Column('fee_code', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=240), nullable=False),
    sa.Column('quantity', sa.String(length=64), nullable=False),
    sa.Column('rate_cents', sa.Integer(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('rule_version_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], name=op.f('fk_assessment_lines_assessment_id_assessments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.id'], name=op.f('fk_assessment_lines_rule_version_id_rule_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assessment_lines'))
    )
    with op.batch_alter_table('assessment_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assessment_lines_assessment_id'), ['assessment_id'], unique=False)

    op.create_table('evaluations',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('revision_id', sa.String(length=64), nullable=True),
    sa.Column('source_versions', sa.JSON(), nullable=True),
    sa.Column('registry_versions', sa.JSON(), nullable=True),
    sa.Column('rule_versions', sa.JSON(), nullable=True),
    sa.Column('date_basis', sa.String(length=64), nullable=True),
    sa.Column('results', sa.JSON(), nullable=True),
    sa.Column('performed_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('performed_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('stale', sa.Boolean(), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_evaluations_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['application_revisions.id'], name=op.f('fk_evaluations_revision_id_application_revisions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluations'))
    )
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evaluations_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_evaluations_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_evaluations_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('extraction_observations',
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('document_version', sa.Integer(), nullable=False),
    sa.Column('field_path', sa.String(length=160), nullable=False),
    sa.Column('proposed_value', sa.String(length=320), nullable=True),
    sa.Column('page_region', sa.String(length=120), nullable=True),
    sa.Column('evidence_excerpt', sa.Text(), nullable=True),
    sa.Column('model_run_id', sa.String(length=64), nullable=True),
    sa.Column('validation_state', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_extraction_observations_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extraction_observations'))
    )
    with op.batch_alter_table('extraction_observations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_extraction_observations_document_id'), ['document_id'], unique=False)

    op.create_table('payment_events',
    sa.Column('payment_id', sa.String(length=64), nullable=False),
    sa.Column('source_event_id', sa.String(length=96), nullable=False),
    sa.Column('source_event_version', sa.String(length=64), nullable=True),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('occurred_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_payment_events_payment_id_payments'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_events')),
    sa.UniqueConstraint('source_event_id', name=op.f('uq_payment_events_source_event_id'))
    )
    with op.batch_alter_table('payment_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payment_events_payment_id'), ['payment_id'], unique=False)

    op.create_table('reconciliation_results',
    sa.Column('assessment_id', sa.String(length=64), nullable=False),
    sa.Column('assessed_total_cents', sa.Integer(), nullable=False),
    sa.Column('settled_allocated_cents', sa.Integer(), nullable=False),
    sa.Column('balance_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('exception', sa.String(length=64), nullable=True),
    sa.Column('computed_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('evidence_refs', sa.JSON(), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_reconciliation_results_currency_is_iso')),
    sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], name=op.f('fk_reconciliation_results_assessment_id_assessments'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_results'))
    )
    with op.batch_alter_table('reconciliation_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reconciliation_results_assessment_id'), ['assessment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reconciliation_results_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('allocations',
    sa.Column('payment_id', sa.String(length=64), nullable=False),
    sa.Column('assessment_id', sa.String(length=64), nullable=False),
    sa.Column('assessment_line_id', sa.String(length=64), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('supersedes_allocation_id', sa.String(length=64), nullable=True),
    sa.Column('idempotency_key', sa.String(length=160), nullable=True),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'released', 'superseded', 'reversed')", name=op.f('ck_allocations_status_allowed')),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_allocations_currency_is_iso')),
    sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], name=op.f('fk_allocations_assessment_id_assessments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['assessment_line_id'], ['assessment_lines.id'], name=op.f('fk_allocations_assessment_line_id_assessment_lines'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_allocations_payment_id_payments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_allocations')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_allocations_idempotency_key'))
    )
    with op.batch_alter_table('allocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_allocations_assessment_id'), ['assessment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_allocations_payment_id'), ['payment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_allocations_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('decisions',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('evaluation_id', sa.String(length=64), nullable=True),
    sa.Column('decision_type', sa.String(length=48), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('decided_by_actor_id', sa.String(length=64), nullable=False),
    sa.Column('decided_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('input_versions', sa.JSON(), nullable=True),
    sa.Column('rule_versions', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('stale', sa.Boolean(), nullable=False),
    sa.Column('scenario_id', sa.String(length=16), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("outcome IN ('approved', 'denied', 'modified', 'information_requested')", name=op.f('ck_decisions_outcome_allowed')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_decisions_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evaluation_id'], ['evaluations.id'], name=op.f('fk_decisions_evaluation_id_evaluations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decisions'))
    )
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_decisions_application_id'), ['application_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_decisions_scenario_id'), ['scenario_id'], unique=False)

    op.create_table('recommendations',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('evaluation_id', sa.String(length=64), nullable=True),
    sa.Column('proposed_outcome', sa.String(length=32), nullable=False),
    sa.Column('evidence_refs', sa.JSON(), nullable=True),
    sa.Column('run_ref', sa.String(length=96), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_recommendations_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evaluation_id'], ['evaluations.id'], name=op.f('fk_recommendations_evaluation_id_evaluations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recommendations'))
    )
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recommendations_application_id'), ['application_id'], unique=False)

    op.create_table('permits',
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('decision_id', sa.String(length=64), nullable=False),
    sa.Column('permit_number', sa.String(length=96), nullable=False),
    sa.Column('issued_at', acme_city.persistence.types.UTCDateTime(), nullable=False),
    sa.Column('expires_at', acme_city.persistence.types.UTCDateTime(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('artifact_hash', sa.String(length=64), nullable=False),
    sa.Column('issuance_command_key', sa.String(length=160), nullable=False),
    sa.Column('issued_by_actor_id', sa.String(length=64), nullable=True),
    sa.Column('fictional_demo', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', acme_city.persistence.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_permits_application_id_applications'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], name=op.f('fk_permits_decision_id_decisions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permits')),
    sa.UniqueConstraint('issuance_command_key', name=op.f('uq_permits_issuance_command_key')),
    sa.UniqueConstraint('permit_number', name=op.f('uq_permits_permit_number'))
    )
    with op.batch_alter_table('permits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_permits_application_id'), ['application_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    with op.batch_alter_table('permits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permits_application_id'))

    op.drop_table('permits')
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recommendations_application_id'))

    op.drop_table('recommendations')
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_decisions_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_decisions_application_id'))

    op.drop_table('decisions')
    with op.batch_alter_table('allocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_allocations_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_allocations_payment_id'))
        batch_op.drop_index(batch_op.f('ix_allocations_assessment_id'))

    op.drop_table('allocations')
    with op.batch_alter_table('reconciliation_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reconciliation_results_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_reconciliation_results_assessment_id'))

    op.drop_table('reconciliation_results')
    with op.batch_alter_table('payment_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_events_payment_id'))

    op.drop_table('payment_events')
    with op.batch_alter_table('extraction_observations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_extraction_observations_document_id'))

    op.drop_table('extraction_observations')
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evaluations_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_evaluations_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_evaluations_application_id'))

    op.drop_table('evaluations')
    with op.batch_alter_table('assessment_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assessment_lines_assessment_id'))

    op.drop_table('assessment_lines')
    op.drop_table('quarantine_errors')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_payments_payer_account_id'))

    op.drop_table('payments')
    with op.batch_alter_table('match_proposals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_match_proposals_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_match_proposals_correlation_id'))

    op.drop_table('match_proposals')
    with op.batch_alter_table('finance_account_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_finance_account_links_party_id'))
        batch_op.drop_index(batch_op.f('ix_finance_account_links_account_id'))

    op.drop_table('finance_account_links')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_application_id'))

    op.drop_table('documents')
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assessments_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_assessments_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_assessments_application_id'))

    op.drop_table('assessments')
    with op.batch_alter_table('application_sites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_sites_application_id'))

    op.drop_table('application_sites')
    with op.batch_alter_table('application_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_revisions_application_id'))

    op.drop_table('application_revisions')
    with op.batch_alter_table('application_parties', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_application_parties_party_id'))
        batch_op.drop_index(batch_op.f('ix_application_parties_application_id'))

    op.drop_table('application_parties')
    with op.batch_alter_table('source_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_source_snapshots_source_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_source_snapshots_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_source_snapshots_correlation_id'))

    op.drop_table('source_snapshots')
    op.drop_table('source_observations')
    with op.batch_alter_table('party_contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_party_contacts_party_id'))

    op.drop_table('party_contacts')
    with op.batch_alter_table('party_aliases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_party_aliases_party_id'))

    op.drop_table('party_aliases')
    with op.batch_alter_table('finance_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_finance_accounts_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_finance_accounts_party_id'))

    op.drop_table('finance_accounts')
    with op.batch_alter_table('credentials', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_credentials_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_credentials_holder_party_id'))

    op.drop_table('credentials')
    with op.batch_alter_table('consumer_acknowledgements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_consumer_acknowledgements_delivery_id'))

    op.drop_table('consumer_acknowledgements')
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_applications_correlation_id'))

    op.drop_table('applications')
    with op.batch_alter_table('steward_queues', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_steward_queues_domain_id'))

    op.drop_table('steward_queues')
    with op.batch_alter_table('source_commands', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_source_commands_change_case_id'))

    op.drop_table('source_commands')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_expires_at'))
        batch_op.drop_index(batch_op.f('ix_sessions_actor_id'))

    op.drop_table('sessions')
    op.drop_table('rule_versions')
    op.drop_table('role_permissions')
    with op.batch_alter_table('review_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_review_tasks_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_review_tasks_change_case_id'))
        batch_op.drop_index(batch_op.f('ix_review_tasks_assignee_actor_id'))

    op.drop_table('review_tasks')
    op.drop_table('provenance')
    op.drop_table('parties')
    with op.batch_alter_table('parcel_addresses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_parcel_addresses_parcel_id'))
        batch_op.drop_index(batch_op.f('ix_parcel_addresses_address_id'))

    op.drop_table('parcel_addresses')
    with op.batch_alter_table('outbox_deliveries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_outbox_deliveries_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_outbox_deliveries_change_case_id'))

    op.drop_table('outbox_deliveries')
    with op.batch_alter_table('model_outputs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_outputs_run_id'))

    op.drop_table('model_outputs')
    with op.batch_alter_table('model_inputs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_inputs_run_id'))

    op.drop_table('model_inputs')
    with op.batch_alter_table('ingestion_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ingestion_runs_correlation_id'))

    op.drop_table('ingestion_runs')
    with op.batch_alter_table('evidence_references', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evidence_references_run_id'))

    op.drop_table('evidence_references')
    with op.batch_alter_table('crosswalks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_crosswalks_scenario_id'))

    op.drop_table('crosswalks')
    with op.batch_alter_table('change_dependencies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_change_dependencies_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_change_dependencies_change_case_id'))

    op.drop_table('change_dependencies')
    with op.batch_alter_table('audit_references', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_references_event_id'))

    op.drop_table('audit_references')
    op.drop_table('actor_roles')
    with op.batch_alter_table('actor_grants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_actor_grants_domain_id'))
        batch_op.drop_index(batch_op.f('ix_actor_grants_actor_id'))

    op.drop_table('actor_grants')
    op.drop_table('source_systems')
    with op.batch_alter_table('source_contracts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_source_contracts_source_system_id'))

    op.drop_table('source_contracts')
    op.drop_table('roles')
    op.drop_table('permit_types')
    op.drop_table('permissions')
    op.drop_table('parcels')
    with op.batch_alter_table('model_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_runs_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_model_runs_correlation_id'))

    op.drop_table('model_runs')
    with op.batch_alter_table('impact_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_impact_reviews_target_id'))
        batch_op.drop_index(batch_op.f('ix_impact_reviews_scenario_id'))

    op.drop_table('impact_reviews')
    with op.batch_alter_table('governance_issues', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_governance_issues_subject_id'))
        batch_op.drop_index(batch_op.f('ix_governance_issues_scenario_id'))

    op.drop_table('governance_issues')
    op.drop_table('fee_schedule_versions')
    with op.batch_alter_table('domains', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_domains_steward_queue_id'))

    op.drop_table('domains')
    op.drop_table('demo_environment')
    with op.batch_alter_table('change_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_change_cases_target_id'))
        batch_op.drop_index(batch_op.f('ix_change_cases_scenario_id'))
        batch_op.drop_index(batch_op.f('ix_change_cases_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_change_cases_assignee_actor_id'))

    op.drop_table('change_cases')
    op.drop_table('canonical_entities')
    with op.batch_alter_table('authority_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_authority_policies_domain_id'))

    op.drop_table('authority_policies')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_occurred_at'))
        batch_op.drop_index(batch_op.f('ix_audit_events_correlation_id'))
        batch_op.drop_index(batch_op.f('ix_audit_events_actor_id'))
        batch_op.drop_index(batch_op.f('ix_audit_events_action'))

    op.drop_table('audit_events')
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assignments_subject_id'))

    op.drop_table('assignments')
    op.drop_table('addresses')
    op.drop_table('actors')
    # ### end Alembic commands ###

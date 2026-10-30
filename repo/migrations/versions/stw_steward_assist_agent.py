"""Let the recorded agent runs name the steward assistant.

Revision ID: stw_steward_assist_agent
Revises: stw_steward_recommendation
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "stw_steward_assist_agent"
down_revision: str | None = "stw_steward_recommendation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The constraint that names the agents whose runs may be recorded.  The name
#: is the logical one; the naming convention of the City adds the prefix.
CONSTRAINT = "agent_key_allowed"


def upgrade() -> None:
    # The steward assistant is a third agent of the City: its runs are
    # recorded in the same table as the runs of the other two, so the run
    # history of the operator shows them all.
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            CONSTRAINT,
            "agent_key IN ('intake', 'adjudication', 'steward_assist')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            CONSTRAINT,
            "agent_key IN ('intake', 'adjudication')",
        )

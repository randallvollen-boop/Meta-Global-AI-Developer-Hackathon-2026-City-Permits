"""Record an applicant's choice to submit with known issues.

Revision ID: psb_presubmit_override
Revises: stw_steward_explanation
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "psb_presubmit_override"
down_revision: str | None = "stw_steward_explanation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The column is empty unless the applicant chose Submit anyway and gave a
    # reason.  A case without one is unchanged.
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("presubmit_override", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_column("presubmit_override")

"""Persist canonical Agent audit trace payloads in the existing audit store."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_agent_audit"
down_revision = "20260912_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_entries", sa.Column("payload", sa.JSON()))


def downgrade() -> None:
    op.drop_column("audit_entries", "payload")

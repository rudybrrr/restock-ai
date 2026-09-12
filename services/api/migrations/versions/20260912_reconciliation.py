"""Preserve batch comparison evidence with each authoritative closing revision."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_reconciliation"
down_revision = "20260912_promotions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_revisions", sa.Column("reconciliation", sa.JSON()))


def downgrade() -> None:
    op.drop_column("daily_revisions", "reconciliation")

"""Retain an explicitly reported expiry for the unreceived delivery remainder."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_delivery_expiry"
down_revision = "20260923_case_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deliveries", sa.Column("expected_expiry_date", sa.Date()))


def downgrade() -> None:
    op.drop_column("deliveries", "expected_expiry_date")

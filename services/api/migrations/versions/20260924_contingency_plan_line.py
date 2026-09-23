"""Keep emergency placement and expiry facts on approved plan lines."""

import sqlalchemy as sa
from alembic import op

revision = "20260924_contingency_plan_line"
down_revision = "20260923_delivery_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_plan_lines", sa.Column("ordered_at", sa.DateTime(timezone=True)))
    op.add_column("purchase_plan_lines", sa.Column("expiry_date", sa.Date()))
    op.add_column("purchase_plan_lines", sa.Column("kind", sa.String()))


def downgrade() -> None:
    op.drop_column("purchase_plan_lines", "kind")
    op.drop_column("purchase_plan_lines", "expiry_date")
    op.drop_column("purchase_plan_lines", "ordered_at")

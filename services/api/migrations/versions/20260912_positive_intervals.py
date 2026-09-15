"""Reject unsafe ordering intervals without silently rewriting existing schedules."""

from alembic import op

revision = "20260912_positive_intervals"
down_revision = "20260912_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ingredients_positive_interval", "ingredients", "interval_days > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ingredients_positive_interval", "ingredients", type_="check")

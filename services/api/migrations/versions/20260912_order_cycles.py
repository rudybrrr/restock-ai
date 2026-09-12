"""Record decisions on anchored ingredient ordering occasions."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_cycles"
down_revision = "20260912_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_cycles",
        sa.Column(
            "ingredient_id",
            sa.String(),
            sa.ForeignKey("ingredients.id"),
            primary_key=True,
        ),
        sa.Column("scheduled_date", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("note", sa.String()),
        sa.CheckConstraint("status IN ('ORDERED', 'SKIPPED')"),
    )


def downgrade() -> None:
    op.drop_table("order_cycles")

"""External deliveries and idempotent receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_deliveries"
down_revision = "20260911_daily"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "supplier_id", sa.String(), sa.ForeignKey("suppliers.id"), nullable=False
        ),
        sa.Column(
            "ingredient_id",
            sa.String(),
            sa.ForeignKey("ingredients.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "cancelled_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"
        ),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expected_quantity > 0 AND cancelled_quantity >= 0"),
        sa.CheckConstraint("kind IN ('NORMAL', 'EMERGENCY')"),
    )
    op.create_table(
        "delivery_receipts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "delivery_id", sa.String(), sa.ForeignKey("deliveries.id"), nullable=False
        ),
        sa.Column(
            "lot_id",
            sa.String(),
            sa.ForeignKey("inventory_lots.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("remainder", sa.String(), nullable=False),
        sa.Column("closing_counts", sa.JSON(), nullable=False),
        sa.UniqueConstraint("delivery_id", "request_id"),
        sa.CheckConstraint("quantity > 0"),
        sa.CheckConstraint("remainder IN ('EXPECTED', 'CANCELLED')"),
    )


def downgrade() -> None:
    op.drop_table("delivery_receipts")
    op.drop_table("deliveries")

"""Sales batches, lot expiry state, and ingredient ordering anchors."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_sales"
down_revision = "20260911_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingredients", sa.Column("interval_days", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("ingredients", sa.Column("starting_date", sa.Date(), nullable=False, server_default="2026-02-15"))
    op.add_column("inventory_lots", sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"))
    op.create_check_constraint("inventory_lots_status_check", "inventory_lots", "status IN ('ACTIVE', 'EXPIRED')")
    op.create_table(
        "sales_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sales", sa.JSON(), nullable=False),
        sa.Column("replaces_id", sa.String(), sa.ForeignKey("sales_batches.id")),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("source", "batch_id", "revision"),
        sa.CheckConstraint("period_end > period_start"),
    )


def downgrade() -> None:
    op.drop_table("sales_batches")
    op.drop_constraint("inventory_lots_status_check", "inventory_lots", type_="check")
    op.drop_column("inventory_lots", "status")
    op.drop_column("ingredients", "starting_date")
    op.drop_column("ingredients", "interval_days")

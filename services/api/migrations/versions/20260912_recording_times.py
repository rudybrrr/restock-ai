"""Separate real recording cutoffs from the operational demo clock.

Legacy rows first become reproducible at this migration, not at invented past
recording times. Existing immutable events still supply delivery/promotion history.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_recording_times"
down_revision = "20260912_offer_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("stock_counts", "sales_batches", "delivery_receipts"):
        op.add_column(
            table,
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.clock_timestamp(),
            ),
        )
    op.add_column("order_cycles", sa.Column("effective_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE order_cycles SET effective_at = decided_at")
    op.alter_column("order_cycles", "effective_at", nullable=False)


def downgrade() -> None:
    op.drop_column("order_cycles", "effective_at")
    for table in ("stock_counts", "sales_batches", "delivery_receipts"):
        op.drop_column(table, "recorded_at")

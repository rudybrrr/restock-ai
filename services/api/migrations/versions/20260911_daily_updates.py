"""Daily drafts, immutable corrections, events and audit."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_daily"
down_revision = "357269117e91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_counts",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint(
        "stock_counts_lot_id_counted_at_key", "stock_counts", type_="unique"
    )
    op.create_unique_constraint(
        "stock_counts_observation_key",
        "stock_counts",
        ["lot_id", "counted_at", "sequence"],
    )
    op.create_table(
        "daily_drafts",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "daily_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("day", "revision"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ["audit_entries", "events", "daily_revisions", "daily_drafts"]:
        op.drop_table(table)
    # Downgrade cannot represent corrected observations without losing history.
    op.drop_constraint("stock_counts_observation_key", "stock_counts", type_="unique")
    op.create_unique_constraint(
        "stock_counts_lot_id_counted_at_key", "stock_counts", ["lot_id", "counted_at"]
    )
    op.drop_column("stock_counts", "sequence")

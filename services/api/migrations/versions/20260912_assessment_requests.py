"""Link coalesced operational triggers to their durable assessment."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_requests"
down_revision = "20260912_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "planning_runs",
        sa.Column("trigger_event_id", sa.String(), sa.ForeignKey("events.id")),
    )
    op.create_table(
        "assessment_requests",
        sa.Column(
            "event_id", sa.String(), sa.ForeignKey("events.id"), primary_key=True
        ),
        sa.Column(
            "run_id", sa.String(), sa.ForeignKey("planning_runs.id"), nullable=False
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("assessment_requests")
    op.drop_column("planning_runs", "trigger_event_id")

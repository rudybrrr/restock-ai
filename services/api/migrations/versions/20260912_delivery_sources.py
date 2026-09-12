"""Keep optional recommendation and ordering-occasion provenance on actual purchases."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_sources"
down_revision = "20260912_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column(
            "source_plan_line_id", sa.String(), sa.ForeignKey("purchase_plan_lines.id")
        ),
    )
    op.add_column("deliveries", sa.Column("cycle_date", sa.Date()))


def downgrade() -> None:
    op.drop_column("deliveries", "cycle_date")
    op.drop_column("deliveries", "source_plan_line_id")

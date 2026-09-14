"""Distinguish validated allocations from legacy reference-only links."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_source_validation"
down_revision = "20260912_one_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column(
            "source_validation", sa.String(), nullable=False, server_default="MANUAL"
        ),
    )
    op.execute(
        "UPDATE deliveries SET source_validation = 'LEGACY_REFERENCE' WHERE source_plan_line_id IS NOT NULL"
    )
    op.create_check_constraint(
        "delivery_source_validation",
        "deliveries",
        "source_validation IN ('MANUAL', 'APPROVED_ALLOCATION', 'LEGACY_REFERENCE')",
    )


def downgrade() -> None:
    op.drop_constraint("delivery_source_validation", "deliveries", type_="check")
    op.drop_column("deliveries", "source_validation")

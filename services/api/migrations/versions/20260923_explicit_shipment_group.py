"""Retain explicit new-shipment identity on approved opportunities."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_explicit_shipment_group"
down_revision = "20260918_merge_sales_agent_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "procurement_domain_opportunities",
        sa.Column("shipment_group_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("procurement_domain_opportunities", "shipment_group_id")

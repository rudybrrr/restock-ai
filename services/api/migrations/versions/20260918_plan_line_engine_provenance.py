"""Retain immutable Decision Engine line provenance on published plans."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_plan_line_provenance"
down_revision = "20260918_merge_forecast_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_plan_lines", sa.Column("offer_id", sa.String()))
    op.add_column("purchase_plan_lines", sa.Column("opportunity_id", sa.String()))
    op.add_column("purchase_plan_lines", sa.Column("shipment_group_id", sa.String()))


def downgrade() -> None:
    op.drop_column("purchase_plan_lines", "shipment_group_id")
    op.drop_column("purchase_plan_lines", "opportunity_id")
    op.drop_column("purchase_plan_lines", "offer_id")

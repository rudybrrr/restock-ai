"""Frozen planning-run snapshots and immutable purchase-plan versions."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_plans"
down_revision = "20260912_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_runs",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False), sa.Column("as_of", sa.DateTime(timezone=True), nullable=False), sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("outcome", sa.String()),
        sa.Column("plan_version_id", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)), sa.Column("deadline_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')"),
    )
    op.create_table("purchase_plans", sa.Column("id", sa.String(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table(
        "plan_versions", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("plan_id", sa.String(), sa.ForeignKey("purchase_plans.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_id", "version"), sa.CheckConstraint("status = 'PENDING_APPROVAL'"),
    )
    op.create_table(
        "purchase_plan_lines", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("plan_version_id", sa.String(), sa.ForeignKey("plan_versions.id"), nullable=False),
        sa.Column("ingredient_id", sa.String(), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("supplier_id", sa.String(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False), sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("quantity > 0 AND unit_price >= 0"),
    )
    op.create_index("one_active_planning_run", "planning_runs", ["status"], unique=True, postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"))


def downgrade() -> None:
    op.drop_index("one_active_planning_run", table_name="planning_runs")
    op.drop_table("purchase_plan_lines")
    op.drop_table("plan_versions")
    op.drop_table("purchase_plans")
    op.drop_table("planning_runs")

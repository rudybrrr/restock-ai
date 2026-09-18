"""Persist approved sales-threshold policy and immutable assessment artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_sales_materiality"
down_revision = "20260917_forecast_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_threshold_policy_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False, unique=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("expires_at >= effective_at"),
    )
    op.create_table(
        "sales_materiality_assessments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("planning_runs.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "policy_version_id",
            sa.String(),
            sa.ForeignKey("sales_threshold_policy_versions.id"),
            nullable=False,
        ),
        sa.Column("captured_state_revision", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_reference", sa.String(), nullable=False, unique=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_reference", sa.String(), unique=True),
        sa.Column("result_sha256", sa.String(length=64)),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(result_reference IS NULL AND result_sha256 IS NULL AND result_payload IS NULL AND completed_at IS NULL) "
            "OR (result_reference IS NOT NULL AND result_sha256 IS NOT NULL AND result_payload IS NOT NULL AND completed_at IS NOT NULL)",
            name="sales_materiality_result_all_or_none",
        ),
    )


def downgrade() -> None:
    op.drop_table("sales_materiality_assessments")
    op.drop_table("sales_threshold_policy_versions")

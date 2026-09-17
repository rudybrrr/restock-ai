"""Persist versioned first-slice forecast inputs."""

import sqlalchemy as sa
from alembic import op

revision = "20260917_forecast_input"
down_revision = "20260916_policy_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "procurement_forecast_inputs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.String(),
            sa.ForeignKey("procurement_policy_versions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("artifact_id", "version"),
        sa.CheckConstraint("version > 0"),
    )


def downgrade() -> None:
    op.drop_table("procurement_forecast_inputs")

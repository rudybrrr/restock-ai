"""Store the explicit synthetic contingency case as one versioned artifact."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_case_inputs"
down_revision = "20260923_contingency_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contingency_case_inputs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.String(),
            sa.ForeignKey("contingency_policy_versions.id"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("artifact_id", "version"),
        sa.UniqueConstraint("source_revision"),
    )


def downgrade() -> None:
    op.drop_table("contingency_case_inputs")

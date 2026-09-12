"""Versioned manager promotion facts; event history retains previous revisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_promotions"
down_revision = "20260912_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("revision > 0"),
    )


def downgrade() -> None:
    op.drop_table("promotions")

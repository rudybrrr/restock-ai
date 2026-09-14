"""Preserve full supplier observations for historical planning inputs."""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260912_offer_history"
down_revision = "20260912_source_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    versions = op.create_table(
        "supplier_offer_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "offer_id", sa.String(), sa.ForeignKey("supplier_offers.id"), nullable=False
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT * FROM supplier_offers")).mappings():
        connection.execute(
            versions.insert().values(
                id="baseline:" + row["id"],
                offer_id=row["id"],
                effective_at=row["observed_at"],
                recorded_at=datetime.now(UTC),
                payload=json.loads(json.dumps(dict(row), default=str)),
            )
        )


def downgrade() -> None:
    op.drop_table("supplier_offer_versions")

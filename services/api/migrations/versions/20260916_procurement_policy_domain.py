"""Persist immutable policy versions and approved procurement domains."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_policy_domain"
down_revision = "20260912_recording_times"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "procurement_policy_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("policy_id", "version"),
    )
    op.create_table(
        "procurement_policy_domains",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.String(),
            sa.ForeignKey("procurement_policy_versions.id"),
            nullable=False,
        ),
        sa.Column("domain_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("domain_id", "version"),
    )
    op.create_table(
        "procurement_domain_offer_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "domain_version_id",
            sa.String(),
            sa.ForeignKey("procurement_policy_domains.id"),
            nullable=False,
        ),
        sa.Column("offer_id", sa.String(), nullable=False),
        sa.Column("supplier_id", sa.String(), nullable=False),
        sa.Column("ingredient_id", sa.String(), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("domain_version_id", "offer_id"),
        sa.UniqueConstraint("domain_version_id", "source_revision"),
    )
    op.create_table(
        "procurement_domain_opportunities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "domain_version_id",
            sa.String(),
            sa.ForeignKey("procurement_policy_domains.id"),
            nullable=False,
        ),
        sa.Column("opportunity_id", sa.String(), nullable=False),
        sa.Column("offer_id", sa.String(), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.UniqueConstraint("domain_version_id", "opportunity_id"),
        sa.CheckConstraint("kind IN ('NORMAL', 'EMERGENCY')"),
    )


def downgrade() -> None:
    op.drop_table("procurement_domain_opportunities")
    op.drop_table("procurement_domain_offer_revisions")
    op.drop_table("procurement_policy_domains")
    op.drop_table("procurement_policy_versions")

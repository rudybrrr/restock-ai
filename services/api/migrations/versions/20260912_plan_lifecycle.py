"""Allow exact-version manager decisions and retain run failure details."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_lifecycle"
down_revision = "20260912_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The original migration used an unnamed PostgreSQL check.
    op.drop_constraint("plan_versions_status_check", "plan_versions", type_="check")
    op.create_check_constraint(
        "plan_version_status",
        "plan_versions",
        "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'INVALIDATED', 'SUPERSEDED')",
    )
    op.add_column("planning_runs", sa.Column("escalation_reason", sa.String()))
    op.add_column("planning_runs", sa.Column("failure_reason", sa.String()))


def downgrade() -> None:
    op.drop_column("planning_runs", "failure_reason")
    op.drop_column("planning_runs", "escalation_reason")
    op.drop_constraint("plan_version_status", "plan_versions", type_="check")
    op.create_check_constraint(
        "plan_versions_status_check", "plan_versions", "status = 'PENDING_APPROVAL'"
    )

"""Merge the sales-materiality and Agent audit migration heads."""


revision = "20260918_merge_sales_agent_audit"
down_revision = ("20260918_sales_materiality", "20260918_agent_audit_append_only")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reconcile migration graph branches without schema changes."""


def downgrade() -> None:
    """Reopen the migration graph branches without schema changes."""

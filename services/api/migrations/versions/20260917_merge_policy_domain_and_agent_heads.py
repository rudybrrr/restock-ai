"""Merge the policy/domain and Agent audit migration branches."""


revision = "20260917_merge_policy_agent"
down_revision = ("20260915_merge_agent_backend", "20260916_policy_domain")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reconcile migration graph branches without schema changes."""


def downgrade() -> None:
    """Reopen the migration graph branches without schema changes."""

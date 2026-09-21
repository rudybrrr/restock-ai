"""Merge the first-slice forecast-input and Agent migration branches."""


revision = "20260918_merge_forecast_agent"
down_revision = ("20260917_merge_policy_agent", "20260917_forecast_input")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reconcile migration graph branches without schema changes."""


def downgrade() -> None:
    """Reopen the migration graph branches without schema changes."""

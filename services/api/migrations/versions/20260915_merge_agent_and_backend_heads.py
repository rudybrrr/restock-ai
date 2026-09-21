"""Merge the independently landed Backend and Agent migration heads.

This revision intentionally changes no schema.  It makes the merged repository
upgradeable through one Alembic ``head`` while retaining both parent histories.
"""

revision = "20260915_merge_agent_backend"
down_revision = ("20260912_recording_times", "20260913_agent_audit")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

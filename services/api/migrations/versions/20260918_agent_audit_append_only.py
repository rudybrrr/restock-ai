"""Prevent rewrites of persisted business-audit facts."""

from alembic import op

revision = "20260918_agent_audit_append_only"
down_revision = "20260918_plan_line_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_audit_entry_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_entries are append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_entries_append_only
        BEFORE UPDATE OR DELETE ON audit_entries
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_entry_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_entries_append_only ON audit_entries")
    op.execute("DROP FUNCTION prevent_audit_entry_mutation()")

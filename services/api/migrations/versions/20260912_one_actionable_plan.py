"""Keep one actionable restaurant recommendation, retaining an audit of legacy overlaps."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260912_one_plan"
down_revision = "20260912_positive_intervals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    plans = sa.table(
        "plan_versions",
        sa.column("id"),
        sa.column("plan_id"),
        sa.column("version"),
        sa.column("status"),
        sa.column("created_at"),
    )
    events = sa.table(
        "events",
        sa.column("id"),
        sa.column("type"),
        sa.column("source"),
        sa.column("timestamp"),
        sa.column("payload", sa.JSON()),
    )
    audit = sa.table(
        "audit_entries",
        sa.column("id"),
        sa.column("event_id"),
        sa.column("actor"),
        sa.column("action"),
        sa.column("timestamp"),
    )
    active = (
        connection.execute(
            sa.select(plans)
            .where(plans.c.status.in_(("PENDING_APPROVAL", "APPROVED")))
            .order_by(plans.c.created_at.desc(), plans.c.id.desc())
        )
        .mappings()
        .all()
    )
    for previous in active[1:]:
        event_id = str(uuid4())
        now = datetime.now(UTC)
        connection.execute(
            plans.update()
            .where(plans.c.id == previous["id"])
            .values(status="SUPERSEDED")
        )
        connection.execute(
            events.insert().values(
                id=event_id,
                type="PLAN_SUPERSEDED",
                source="migration",
                timestamp=now,
                payload={
                    "plan_id": previous["plan_id"],
                    "version_id": previous["id"],
                    "version": previous["version"],
                    "previous_status": previous["status"],
                    "replacement_version_id": active[0]["id"],
                    "reason": "CY-005 migration retains the newest actionable recommendation and supersedes legacy overlaps",
                },
            )
        )
        connection.execute(
            audit.insert().values(
                id=str(uuid4()),
                event_id=event_id,
                actor="migration",
                action="PLAN_SUPERSEDED",
                timestamp=now,
            )
        )
    op.create_index(
        "one_actionable_plan",
        "plan_versions",
        [sa.text("(status IN ('PENDING_APPROVAL', 'APPROVED'))")],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING_APPROVAL', 'APPROVED')"),
    )


def downgrade() -> None:
    op.drop_index("one_actionable_plan", table_name="plan_versions")
    # Historical supersessions are deliberately not reversed.

"""Durable coalescing for explicit operational triggers, inside the caller's transaction."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session

from src import database as db

EXPLICIT_TRIGGERS = {
    "DAILY_UPDATE_SUBMITTED",
    "PROMOTION_CREATED",
    "PROMOTION_CHANGED",
    "SUPPLIER_AVAILABILITY_CHANGED",
    "SUPPLIER_PRICE_CHANGED",
    "SUPPLIER_STATUS_CHANGED",
    "SUPPLIER_RELIABILITY_UPDATED",
    "DELIVERY_DELAYED",
    "DELIVERY_SHORT",
    "DELIVERY_CANCELLED",
}


def enqueue_event(
    session: Session, event_id: str, event_type: str, effective_at: datetime
) -> str:
    session.execute(text("SELECT pg_advisory_xact_lock(20260215)"))
    queued = (
        session.execute(
            select(db.planning_runs).where(db.planning_runs.c.status == "QUEUED")
        )
        .mappings()
        .one_or_none()
    )
    if queued:
        run_id = queued["id"]
        session.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run_id)
            .values(as_of=max(queued["as_of"], effective_at))
        )
    else:
        active = session.execute(
            select(db.plan_versions.c.plan_id)
            .where(db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED")))
            .order_by(db.plan_versions.c.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        run_id = str(uuid4())
        session.execute(
            insert(db.planning_runs).values(
                id=run_id,
                status="QUEUED",
                trigger=event_type,
                trigger_event_id=event_id,
                as_of=effective_at,
                input_revision=0,
                snapshot={"revises_plan_id": active},
                created_at=datetime.now(UTC),
            )
        )
    session.execute(
        insert(db.assessment_requests).values(
            event_id=event_id, run_id=run_id, effective_at=effective_at
        )
    )
    return run_id

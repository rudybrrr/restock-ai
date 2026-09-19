from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import overload
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src import database as db
from src.assessment_queue import EXPLICIT_TRIGGERS, enqueue_event
from src.errors import ApiError
from src.operations_schemas import (
    DailyDraft,
    EventType,
    InventoryAdjustmentEventPayload,
    InventoryAdjustmentLine,
)
from src.reconciliation import reconcile_sales


@overload
def _canonical_quantity(value: Decimal) -> Decimal: ...


@overload
def _canonical_quantity(value: None) -> None: ...


def _canonical_quantity(value: Decimal | None) -> Decimal | None:
    """Serialize correction quantities without database scale noise."""
    if value is None:
        return None
    return Decimal(format(value.normalize(), "f"))


def lock_inventory(session: Session) -> None:
    # One restaurant: serialize counts and receipts to enforce cutoff completeness.
    session.execute(text("SELECT pg_advisory_xact_lock(20260215)"))


def record_event(
    session: Session, event_type: EventType, actor: str, payload: dict
) -> str:
    event_id = str(uuid4())
    now = datetime.now(UTC)
    session.execute(
        insert(db.events).values(
            id=event_id,
            type=event_type,
            timestamp=now,
            source=actor,
            payload=payload,
        )
    )
    session.execute(
        insert(db.audit_entries).values(
            id=str(uuid4()),
            event_id=event_id,
            actor=actor,
            action=event_type,
            timestamp=now,
        )
    )
    if event_type in EXPLICIT_TRIGGERS:
        effective_at = datetime.fromisoformat(
            payload.get("effective_at") or payload["cutoff"]
        )
        enqueue_event(session, event_id, event_type, effective_at)
    return event_id


def save_draft(session: Session, day: date, body: DailyDraft) -> DailyDraft:
    if body.cutoff.astimezone(ZoneInfo("Asia/Singapore")).date() != day:
        raise ApiError(
            422, "INVALID_CUTOFF", "Cutoff must fall on the specified Singapore day"
        )
    lock_inventory(session)
    statement = pg_insert(db.daily_drafts).values(
        day=day, payload=body.model_dump(mode="json")
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["day"],
            set_={"payload": statement.excluded.payload},
        )
    )
    session.commit()
    return body


def read_day(session: Session, day: date) -> dict:
    draft = session.execute(
        select(db.daily_drafts.c.payload).where(db.daily_drafts.c.day == day)
    ).scalar_one_or_none()
    rows = (
        session.execute(
            select(db.daily_revisions)
            .where(db.daily_revisions.c.day == day)
            .order_by(db.daily_revisions.c.revision)
        )
        .mappings()
        .all()
    )
    return {"draft": draft, "revisions": [{**row, **row["payload"]} for row in rows]}


def submit_day(session: Session, day: date, actor: str) -> dict:
    lock_inventory(session)
    history = read_day(session, day)
    if history["draft"] is None:
        raise ApiError(
            422, "INCOMPLETE_DAILY_UPDATE", "Save a complete draft before submitting"
        )
    body = DailyDraft.model_validate(history["draft"])
    lots = set(
        session.execute(
            select(db.inventory_lots.c.id).where(
                db.inventory_lots.c.received_at <= body.cutoff,
                db.inventory_lots.c.expiry_date >= day,
            )
        ).scalars()
    )
    # Historical expired batches may also be counted explicitly.
    known = set(
        session.execute(
            select(db.inventory_lots.c.id).where(
                db.inventory_lots.c.received_at <= body.cutoff
            )
        ).scalars()
    )
    dishes = set(session.execute(select(db.menu_items.c.id)).scalars())
    if (
        not lots <= body.counts.keys()
        or not body.counts.keys() <= known
        or body.sales.keys() != dishes
    ):
        raise ApiError(
            422,
            "INCOMPLETE_DAILY_UPDATE",
            "Enter every unexpired received batch and every dish; use explicit zero",
        )
    if (
        history["revisions"]
        and DailyDraft.model_validate(
            {
                key: history["revisions"][-1][key]
                for key in ("cutoff", "counts", "sales")
            }
        ).cutoff
        != body.cutoff
    ):
        raise ApiError(
            409, "CUTOFF_CONFLICT", "Corrections must retain the original cutoff"
        )
    result = record_daily_revision(session, day, body, actor)
    session.commit()
    return result


def record_daily_revision(
    session: Session, day: date, body: DailyDraft, actor: str
) -> dict:
    """Append a validated observation inside the caller's inventory transaction."""
    expire_lots(session, body.cutoff, actor)
    history = read_day(session, day)["revisions"]
    revision = len(history) + 1
    replaces_revision_id = history[-1]["id"] if history else None
    previous_counts = history[-1]["counts"] if history else {}
    row = {
        "id": str(uuid4()),
        "day": day,
        "revision": revision,
        "cutoff": body.cutoff,
        "recorded_at": datetime.now(UTC),
        "actor": actor,
        "reconciliation": reconcile_sales(session, day, body.cutoff, body.sales),
        "payload": body.model_dump(mode="json"),
    }
    session.execute(insert(db.daily_revisions).values(**row))
    sequence = (
        session.execute(
            select(func.coalesce(func.max(db.stock_counts.c.sequence), 0))
        ).scalar_one()
        + 1
    )
    for lot_id, quantity in body.counts.items():
        session.execute(
            insert(db.stock_counts).values(
                id=str(uuid4()),
                lot_id=lot_id,
                quantity=quantity,
                counted_at=body.cutoff,
                sequence=sequence,
            )
        )
    if replaces_revision_id:
        lot_rows = {
            item["id"]: item
            for item in session.execute(
                select(
                    db.inventory_lots.c.id,
                    db.inventory_lots.c.ingredient_id,
                    db.ingredients.c.unit,
                )
                .join(
                    db.ingredients,
                    db.ingredients.c.id == db.inventory_lots.c.ingredient_id,
                )
                .where(db.inventory_lots.c.id.in_(body.counts))
            ).mappings()
        }
        adjustments = []
        for lot_id, corrected in sorted(body.counts.items()):
            previous_raw = previous_counts.get(lot_id)
            previous = Decimal(str(previous_raw)) if previous_raw is not None else None
            if previous == corrected:
                continue
            lot = lot_rows[lot_id]
            adjustments.append(
                InventoryAdjustmentLine(
                    lot_id=lot_id,
                    ingredient_id=lot["ingredient_id"],
                    unit=lot["unit"],
                    previous_quantity=_canonical_quantity(previous),
                    corrected_quantity=_canonical_quantity(corrected),
                    delta=_canonical_quantity(corrected - previous)
                    if previous is not None
                    else None,
                )
            )
        if adjustments:
            adjustment = InventoryAdjustmentEventPayload(
                revision_id=row["id"],
                replaces_revision_id=replaces_revision_id,
                day=day,
                effective_at=body.cutoff,
                adjustments=adjustments,
            )
            record_event(
                session,
                "INVENTORY_ADJUSTED",
                actor,
                adjustment.model_dump(mode="json"),
            )
    record_event(
        session,
        "DAILY_UPDATE_CORRECTED" if replaces_revision_id else "DAILY_UPDATE_SUBMITTED",
        actor,
        {
            "revision_id": row["id"],
            "replaces_revision_id": replaces_revision_id,
            "day": day.isoformat(),
            "revision": revision,
            "cutoff": body.cutoff.isoformat(),
        },
    )
    return {**row, **body.model_dump()}


def expire_lots(session: Session, as_of: datetime, actor: str) -> None:
    singapore = ZoneInfo("Asia/Singapore")
    expired = (
        session.execute(
            select(db.inventory_lots).where(
                db.inventory_lots.c.expiry_date < as_of.astimezone(singapore).date(),
                db.inventory_lots.c.status == "ACTIVE",
            )
        )
        .mappings()
        .all()
    )
    for lot in expired:
        session.execute(
            update(db.inventory_lots)
            .where(db.inventory_lots.c.id == lot["id"])
            .values(status="EXPIRED")
        )
        record_event(
            session,
            "INVENTORY_LOT_EXPIRED",
            actor,
            {
                "lot_id": lot["id"],
                "effective_at": datetime.combine(
                    lot["expiry_date"] + timedelta(days=1), time.min, singapore
                ).isoformat(),
            },
        )

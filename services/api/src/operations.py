from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations_schemas import DailyDraft


def lock_inventory(session: Session) -> None:
    # One restaurant: serialize counts and receipts to enforce cutoff completeness.
    session.execute(text("SELECT pg_advisory_xact_lock(20260215)"))


def record_event(session: Session, event_type: str, actor: str, payload: dict) -> None:
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
    revision = len(history["revisions"]) + 1
    row = {
        "id": str(uuid4()),
        "day": day,
        "revision": revision,
        "cutoff": body.cutoff,
        "recorded_at": datetime.now(UTC),
        "actor": actor,
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
    record_event(
        session,
        "DAILY_UPDATE_SUBMITTED",
        actor,
        {
            "revision_id": row["id"],
            "day": day.isoformat(),
            "revision": revision,
            "cutoff": body.cutoff.isoformat(),
        },
    )
    session.commit()
    return {**row, **body.model_dump()}

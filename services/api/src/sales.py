"""Durable simulator sales input and recipe-derived inventory estimates."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations import lock_inventory, record_event
from src.operations_schemas import SalesBatch, SalesBatchCreate

SINGAPORE = ZoneInfo("Asia/Singapore")


def _model(row: RowMapping | dict) -> SalesBatch:
    return SalesBatch.model_validate({**row, "active": bool(row["active"])})


def _known_dishes(session: Session) -> set[str]:
    return set(session.execute(select(db.menu_items.c.id)).scalars())


def _expire_lots(session: Session, as_of: datetime, actor: str) -> None:
    today = as_of.astimezone(SINGAPORE).date()
    expired = (
        session.execute(
            select(db.inventory_lots).where(
                db.inventory_lots.c.expiry_date < today,
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
                    today, datetime.min.time(), SINGAPORE
                ).isoformat(),
            },
        )


def create_sales_batch(
    session: Session, body: SalesBatchCreate, actor: str
) -> SalesBatch:
    if body.period_end <= body.period_start:
        raise ApiError(
            422, "INVALID_SALES_INTERVAL", "The batch end must follow its start"
        )
    if not set(body.sales) <= _known_dishes(session):
        raise ApiError(422, "UNKNOWN_MENU_ITEM", "Sales reference an unknown menu item")
    lock_inventory(session)
    existing = (
        session.execute(
            select(db.sales_batches)
            .where(
                db.sales_batches.c.source == body.source,
                db.sales_batches.c.batch_id == body.batch_id,
            )
            .order_by(db.sales_batches.c.revision.desc())
        )
        .mappings()
        .all()
    )
    if existing:
        original = _model(existing[-1])
        if (
            SalesBatchCreate.model_validate(
                {key: getattr(original, key) for key in SalesBatchCreate.model_fields}
            )
            == body
        ):
            return original
    if body.replaces_id is None and existing:
        raise ApiError(
            409, "SALES_BATCH_CONFLICT", "Batch identity already has different contents"
        )
    replaced = None
    if body.replaces_id:
        replaced = (
            session.execute(
                select(db.sales_batches).where(
                    db.sales_batches.c.id == body.replaces_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if replaced is None or not replaced["active"]:
            raise ApiError(
                409,
                "INVALID_SALES_CORRECTION",
                "Correction must replace an active batch",
            )
    active = (
        session.execute(select(db.sales_batches).where(db.sales_batches.c.active == 1))
        .mappings()
        .all()
    )
    for batch in active:
        if replaced is not None and batch["id"] == replaced["id"]:
            continue
        if (
            body.period_start < batch["period_end"]
            and batch["period_start"] < body.period_end
        ):
            raise ApiError(
                409,
                "SALES_INTERVAL_OVERLAP",
                "Sales batch overlaps an accepted interval",
            )
    # A complete physical count defines a hard boundary: never guess a partial batch split.
    cutoff = session.execute(
        select(db.stock_counts.c.counted_at).order_by(
            db.stock_counts.c.counted_at.desc()
        )
    ).scalar()
    if cutoff is not None and body.period_start < cutoff < body.period_end:
        raise ApiError(
            422,
            "UNSUPPORTED_CUTOFF_SPLIT",
            "Batch must end or begin at a stocktake cutoff",
        )
    if replaced is not None:
        session.execute(
            update(db.sales_batches)
            .where(db.sales_batches.c.id == replaced["id"])
            .values(active=0)
        )
    revision = max((row["revision"] for row in existing), default=0) + 1
    row = {
        "id": str(uuid4()),
        "source": body.source,
        "batch_id": body.batch_id,
        "revision": revision,
        "period_start": body.period_start,
        "period_end": body.period_end,
        "sales": body.model_dump(mode="json")["sales"],
        "replaces_id": body.replaces_id,
        "active": 1,
    }
    session.execute(insert(db.sales_batches).values(**row))
    result = _model(row)
    _expire_lots(session, body.period_end, actor)
    record_event(
        session, "SALES_UPDATED", actor, {"batch": result.model_dump(mode="json")}
    )
    session.commit()
    return result


def estimated_inventory(session: Session, as_of: datetime) -> list[dict]:
    """Calculate from the latest physical observations without mutating them."""
    latest = (
        select(db.stock_counts)
        .where(db.stock_counts.c.counted_at <= as_of)
        .distinct(db.stock_counts.c.lot_id)
        .order_by(
            db.stock_counts.c.lot_id,
            db.stock_counts.c.counted_at.desc(),
            db.stock_counts.c.sequence.desc(),
        )
        .subquery()
    )
    lots = (
        session.execute(
            select(
                db.inventory_lots,
                db.ingredients.c.unit,
                latest.c.quantity,
                latest.c.counted_at,
            )
            .join(latest, latest.c.lot_id == db.inventory_lots.c.id)
            .join(
                db.ingredients, db.ingredients.c.id == db.inventory_lots.c.ingredient_id
            )
            .order_by(db.inventory_lots.c.expiry_date, db.inventory_lots.c.id)
        )
        .mappings()
        .all()
    )
    if not lots:
        return []
    baseline = max(row["counted_at"] for row in lots)
    batches = (
        session.execute(
            select(db.sales_batches)
            .where(
                db.sales_batches.c.active == 1,
                db.sales_batches.c.period_start >= baseline,
                db.sales_batches.c.period_end <= as_of,
            )
            .order_by(db.sales_batches.c.period_start)
        )
        .mappings()
        .all()
    )
    recipe_usage: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    recipes = session.execute(select(db.recipes)).mappings().all()
    for batch in batches:
        for recipe in recipes:
            recipe_usage[recipe["ingredient_id"]] += (
                Decimal(str(batch["sales"].get(recipe["menu_item_id"], 0)))
                * recipe["quantity"]
            )
    remaining = {row["id"]: row["quantity"] for row in lots}
    today = as_of.astimezone(SINGAPORE).date()
    for ingredient, usage in recipe_usage.items():
        for lot in (
            row
            for row in lots
            if row["ingredient_id"] == ingredient and row["expiry_date"] >= today
        ):
            deduction = min(remaining[lot["id"]], usage)
            remaining[lot["id"]] -= deduction
            usage -= deduction
            if usage == 0:
                break
    coverage_end = baseline
    for batch in batches:
        if batch["period_start"] != coverage_end:
            break
        coverage_end = batch["period_end"]
    complete = coverage_end >= as_of
    return [
        {
            **row,
            "quantity": Decimal(0)
            if row["expiry_date"] < today
            else remaining[row["id"]],
            "provenance": "ESTIMATED",
            "as_of": as_of,
            "coverage_start": baseline,
            "coverage_complete": complete,
            "status": "EXPIRED" if row["expiry_date"] < today else row["status"],
        }
        for row in lots
    ]

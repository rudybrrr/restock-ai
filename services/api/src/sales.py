"""Durable simulator sales input and recipe-derived inventory estimates."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations import expire_lots, lock_inventory, record_event
from src.operations_schemas import SalesBatch, SalesBatchCreate

SINGAPORE = ZoneInfo("Asia/Singapore")


def _model(row: RowMapping | dict) -> SalesBatch:
    return SalesBatch.model_validate({**row, "active": bool(row["active"])})


def _known_dishes(session: Session) -> set[str]:
    return set(session.execute(select(db.menu_items.c.id)).scalars())


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
    for previous in existing:
        original = _model(previous)
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
        select(db.stock_counts.c.counted_at)
        .where(
            db.stock_counts.c.counted_at > body.period_start,
            db.stock_counts.c.counted_at < body.period_end,
        )
        .limit(1)
    ).scalar()
    if cutoff is not None:
        raise ApiError(
            422,
            "UNSUPPORTED_CUTOFF_SPLIT",
            "Batch must end or begin at a stocktake or receipt cutoff",
        )
    expiry_dates = session.execute(
        select(db.inventory_lots.c.expiry_date).distinct()
    ).scalars()
    crosses_expiry = any(
        body.period_start
        < datetime.combine(expiry + timedelta(days=1), time.min, SINGAPORE)
        < body.period_end
        for expiry in expiry_dates
    )
    if crosses_expiry:
        raise ApiError(
            422,
            "UNSUPPORTED_EXPIRY_SPLIT",
            "Split sales batches at midnight when stock expires",
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
    expire_lots(session, body.period_end, actor)
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
    # Replay observations and usage in time order. A new receipt only resets its
    # own lot; it must never reset consumption already recorded against old lots.
    observations = (
        session.execute(
            select(db.stock_counts)
            .where(
                db.stock_counts.c.counted_at <= as_of,
            )
            .order_by(db.stock_counts.c.counted_at, db.stock_counts.c.sequence)
        )
        .mappings()
        .all()
    )
    baseline = min(row["counted_at"] for row in observations)
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
    recipes = session.execute(select(db.recipes)).mappings().all()
    remaining: dict[str, Decimal] = {}
    deficits: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    lot_by_id = {row["id"]: row for row in lots}
    # At a shared timestamp the previous interval's sales precede the closing
    # observation; that physical observation then authoritatively resets stock.
    timeline = [
        (row["counted_at"], 1, row["sequence"], "count", row)
        for row in observations
        if row["lot_id"] in lot_by_id
    ]
    timeline += [(row["period_end"], 0, 0, "sales", row) for row in batches]
    counts_by_time: dict[datetime, set[str]] = defaultdict(set)
    for observation in observations:
        counts_by_time[observation["counted_at"]].add(observation["lot_id"])
    for event_at, _, _, kind, row in sorted(timeline, key=lambda item: item[:3]):
        if kind == "count":
            remaining[row["lot_id"]] = row["quantity"]
            ingredient = lot_by_id[row["lot_id"]]["ingredient_id"]
            current_lots = {
                lot["id"]
                for lot in lots
                if lot["ingredient_id"] == ingredient and lot["received_at"] <= event_at
            }
            if current_lots <= counts_by_time[event_at]:
                deficits[ingredient] = Decimal(0)
            continue
        usage_by_ingredient: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for recipe in recipes:
            usage_by_ingredient[recipe["ingredient_id"]] += (
                Decimal(str(row["sales"].get(recipe["menu_item_id"], 0)))
                * recipe["quantity"]
            )
        # Intervals are half-open: sales ending at midnight belong to the prior day.
        service_day = (
            (event_at - timedelta(microseconds=1)).astimezone(SINGAPORE).date()
        )
        for ingredient, usage in usage_by_ingredient.items():
            for lot in lots:
                if (
                    lot["ingredient_id"] != ingredient
                    or lot["id"] not in remaining
                    or lot["received_at"] > row["period_start"]
                    or lot["expiry_date"] < service_day
                ):
                    continue
                deduction = min(remaining[lot["id"]], usage)
                remaining[lot["id"]] -= deduction
                usage -= deduction
            deficits[ingredient] += usage
    today = as_of.astimezone(SINGAPORE).date()
    result = []
    for lot in lots:
        coverage_end = lot["counted_at"]
        for batch in batches:
            if batch["period_end"] <= coverage_end:
                continue
            if batch["period_start"] != coverage_end:
                break
            coverage_end = batch["period_end"]
        result.append(
            {
                **lot,
                "quantity": Decimal(0)
                if lot["expiry_date"] < today
                else remaining[lot["id"]],
                "provenance": "ESTIMATED",
                "as_of": as_of,
                "coverage_start": lot["counted_at"],
                "coverage_complete": coverage_end >= as_of,
                "status": "EXPIRED" if lot["expiry_date"] < today else "ACTIVE",
                "unallocated_consumption": deficits[lot["ingredient_id"]],
            }
        )
    return result

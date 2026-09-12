"""Compare equal business-day intervals without treating missing coverage as waste."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import database as db


def authoritative_daily_sales(session: Session, as_of: datetime) -> list[dict]:
    """Latest submitted totals once per day; intraday batches are never added to them."""
    latest = {}
    for row in session.execute(
        select(db.daily_revisions)
        .where(db.daily_revisions.c.cutoff <= as_of)
        .order_by(db.daily_revisions.c.day, db.daily_revisions.c.revision)
    ).mappings():
        latest[row["day"]] = {
            "day": row["day"].isoformat(),
            "revision_id": row["id"],
            "cutoff": row["cutoff"].isoformat(),
            "sales": row["payload"]["sales"],
            "source": "DAILY_FINAL",
        }
    return list(latest.values())


def reconcile_sales(
    session: Session, day: date, cutoff: datetime, totals: dict[str, int]
) -> dict:
    # MVP business day is Singapore midnight through the submitted closing cutoff.
    start = datetime.combine(day, time.min, ZoneInfo("Asia/Singapore"))
    batches = (
        session.execute(
            select(db.sales_batches)
            .where(
                db.sales_batches.c.active == 1,
                db.sales_batches.c.period_start < cutoff,
                db.sales_batches.c.period_end > start,
            )
            .order_by(db.sales_batches.c.period_start)
        )
        .mappings()
        .all()
    )
    cursor = start
    complete = True
    summed = {dish: 0 for dish in totals}
    for batch in batches:
        if batch["period_start"] < start or batch["period_end"] > cutoff:
            complete = False
            continue
        if batch["period_start"] != cursor or batch["period_end"] > cutoff:
            complete = False
        cursor = batch["period_end"]
        for dish in totals:
            summed[dish] += batch["sales"].get(dish, 0)
    complete = complete and cursor == cutoff
    comparison = [
        {
            "menu_item_id": dish,
            "daily_total": total,
            "batch_total": summed[dish],
            "difference": total - summed[dish] if complete else None,
        }
        for dish, total in sorted(totals.items())
    ]
    return {
        "period_start": start.isoformat(),
        "period_end": cutoff.isoformat(),
        "batch_ids": [batch["id"] for batch in batches],
        "status": "INCOMPLETE_COVERAGE"
        if not complete
        else (
            "MATCHED"
            if all(row["difference"] == 0 for row in comparison)
            else "RECONCILIATION_DISCREPANCY"
        ),
        "dishes": comparison,
    }

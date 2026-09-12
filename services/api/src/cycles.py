"""Anchored ingredient ordering occasions; decisions never create purchases."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations import lock_inventory, record_event


class CycleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ORDERED", "SKIPPED"]
    note: str | None = Field(default=None, max_length=500)


class OrderCycle(BaseModel):
    ingredient_id: str
    scheduled_date: date
    status: Literal["OPEN", "ORDERED", "SKIPPED"]
    decided_at: AwareDatetime | None = None
    actor: str | None = None
    note: str | None = None


def list_cycles(session: Session, start: date, end: date) -> list[OrderCycle]:
    if end < start or (end - start).days > 90:
        raise ApiError(
            422, "INVALID_CYCLE_WINDOW", "Choose an inclusive window of at most 91 days"
        )
    decisions = {
        (row["ingredient_id"], row["scheduled_date"]): dict(row)
        for row in session.execute(
            select(db.order_cycles).where(
                db.order_cycles.c.scheduled_date.between(start, end)
            )
        ).mappings()
    }
    result = []
    for ingredient in session.execute(
        select(db.ingredients).order_by(db.ingredients.c.id)
    ).mappings():
        anchor = ingredient["starting_date"]
        interval = ingredient["interval_days"]
        offset = max(0, (start - anchor).days)
        day = anchor + timedelta(days=((offset + interval - 1) // interval) * interval)
        while day <= end:
            result.append(
                OrderCycle.model_validate(
                    decisions.get(
                        (ingredient["id"], day),
                        {
                            "ingredient_id": ingredient["id"],
                            "scheduled_date": day,
                            "status": "OPEN",
                        },
                    )
                )
            )
            day += timedelta(days=interval)
    return sorted(result, key=lambda row: (row.scheduled_date, row.ingredient_id))


def decide_cycle(
    session: Session, ingredient_id: str, day: date, body: CycleDecision, actor: str
) -> OrderCycle:
    lock_inventory(session)
    ingredient = (
        session.execute(
            select(db.ingredients).where(db.ingredients.c.id == ingredient_id)
        )
        .mappings()
        .one_or_none()
    )
    if ingredient is None:
        raise ApiError(404, "INGREDIENT_NOT_FOUND", "Ingredient does not exist")
    offset = (day - ingredient["starting_date"]).days
    if offset < 0 or offset % ingredient["interval_days"]:
        raise ApiError(
            422,
            "NOT_AN_ORDERING_DATE",
            "Date must follow the ingredient's anchored interval",
        )
    existing = (
        session.execute(
            select(db.order_cycles).where(
                db.order_cycles.c.ingredient_id == ingredient_id,
                db.order_cycles.c.scheduled_date == day,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["status"] != body.status or existing["note"] != body.note:
            raise ApiError(
                409,
                "CYCLE_ALREADY_DECIDED",
                "This ordering occasion already has a different decision",
            )
        return OrderCycle.model_validate(existing)
    row = {
        "ingredient_id": ingredient_id,
        "scheduled_date": day,
        **body.model_dump(),
        "decided_at": datetime.now(UTC),
        "actor": actor,
    }
    stored = (
        session.execute(
            insert(db.order_cycles).values(**row).returning(db.order_cycles)
        )
        .mappings()
        .one()
    )
    record_event(
        session,
        "ORDER_CYCLE_UPDATED",
        actor,
        {
            "ingredient_id": ingredient_id,
            "scheduled_date": day.isoformat(),
            **body.model_dump(),
        },
    )
    session.commit()
    return OrderCycle.model_validate(stored)

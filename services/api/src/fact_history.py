"""Immutable supplier observations, separate from effective simulation time."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations_schemas import Delivery


def record_offer_version(session: Session, row: dict) -> None:
    session.execute(
        insert(db.supplier_offer_versions).values(
            id=str(uuid4()),
            offer_id=row["id"],
            effective_at=row["observed_at"],
            recorded_at=datetime.now(UTC),
            payload=json.loads(json.dumps(dict(row), default=str)),
        )
    )


def sales_at(session: Session, as_of: datetime, known_at: datetime) -> list[dict]:
    """Reconstruct active revisions without consulting today's mutable active flag."""
    rows = list(
        session.execute(
            select(db.sales_batches)
            .where(
                db.sales_batches.c.recorded_at <= known_at,
            )
            .order_by(db.sales_batches.c.recorded_at, db.sales_batches.c.id)
        ).mappings()
    )
    replaced = {row["replaces_id"] for row in rows if row["replaces_id"]}
    return sorted(
        [
            {**row, "active": 1}
            for row in rows
            if row["id"] not in replaced and row["period_end"] <= as_of
        ],
        key=lambda row: (row["period_start"], row["id"]),
    )


def offers_at(
    session: Session, as_of: datetime, known_at: datetime
) -> tuple[list[dict], list[str]]:
    latest = {}
    for row in session.execute(
        select(db.supplier_offer_versions)
        .where(
            db.supplier_offer_versions.c.effective_at <= as_of,
            db.supplier_offer_versions.c.recorded_at <= known_at,
        )
        .order_by(
            db.supplier_offer_versions.c.effective_at,
            db.supplier_offer_versions.c.recorded_at,
            db.supplier_offer_versions.c.id,
        )
    ).mappings():
        latest[row["offer_id"]] = row
    return (
        [row["payload"] for _, row in sorted(latest.items())],
        [row["id"] for _, row in sorted(latest.items())],
    )


def promotions_at(session: Session, as_of: datetime, known_at: datetime) -> list[dict]:
    latest = {}
    for event in session.execute(
        select(db.events)
        .where(
            db.events.c.type.in_(("PROMOTION_CREATED", "PROMOTION_CHANGED")),
            db.events.c.timestamp <= known_at,
        )
        .order_by(db.events.c.timestamp, db.events.c.id)
    ).mappings():
        payload = event["payload"]
        if datetime.fromisoformat(payload["effective_at"]) <= as_of:
            latest[payload["promotion_id"]] = {"id": payload["promotion_id"], **payload}
    return [value for _, value in sorted(latest.items())]


def delivery_activity_at(session: Session, delivery_id: str) -> datetime:
    """Latest effective activity; terms/cancellations cannot rewrite earlier states."""
    times = [
        datetime.fromisoformat(event["payload"]["effective_at"])
        for event in session.execute(
            select(db.events).where(
                db.events.c.type.in_(
                    ("EXTERNAL_ORDER_RECORDED", "DELIVERY_UPDATED", "DELIVERY_RECEIVED")
                )
            )
        ).mappings()
        if event["payload"]["delivery"]["id"] == delivery_id
    ]
    if not times:
        raise ApiError(
            409, "HISTORY_UNAVAILABLE", "Delivery has no recorded operational history"
        )
    return max(times)


def commitments_at(session: Session, as_of: datetime, known_at: datetime) -> list[dict]:
    # Terms come only from purchase/update events. Receipt event snapshots may
    # contain later terms when a receipt is recorded late, so never use those.
    states = {}
    events = []
    for row in session.execute(
        select(db.events).where(
            db.events.c.type.in_(("EXTERNAL_ORDER_RECORDED", "DELIVERY_UPDATED")),
            db.events.c.timestamp <= known_at,
        )
    ).mappings():
        effective = datetime.fromisoformat(row["payload"]["effective_at"])
        if effective <= as_of:
            events.append((effective, row["timestamp"], row["id"], row))
    for _, _, _, row in sorted(events):
        payload = row["payload"]["delivery"]
        states[payload["id"]] = payload
    receipts = list(
        session.execute(
            select(db.delivery_receipts)
            .where(
                db.delivery_receipts.c.received_at <= as_of,
                db.delivery_receipts.c.recorded_at <= known_at,
            )
            .order_by(db.delivery_receipts.c.received_at, db.delivery_receipts.c.id)
        ).mappings()
    )
    result = []
    for delivery_id, payload in sorted(states.items()):
        received_rows = [
            {**row, "closing_counts": {}}
            for row in receipts
            if row["delivery_id"] == delivery_id
        ]
        received = sum((row["quantity"] for row in received_rows), Decimal(0))
        expected = Decimal(payload["expected_quantity"])
        cancelled = (
            expected - received
            if any(row["remainder"] == "CANCELLED" for row in received_rows)
            else Decimal(payload["cancelled_quantity"])
        )
        if expected < received + cancelled or cancelled < 0:
            raise ApiError(
                409,
                "HISTORY_UNAVAILABLE",
                "Delivery history is inconsistent at this cutoff",
            )
        result.append(
            Delivery.model_validate(
                {
                    **payload,
                    "source_validation": payload.get("source_validation")
                    or (
                        "LEGACY_REFERENCE"
                        if payload.get("source_plan_line_id")
                        else "MANUAL"
                    ),
                    "receipts": received_rows,
                    "received_quantity": received,
                    "cancelled_quantity": cancelled,
                    "outstanding_quantity": expected - received - cancelled,
                }
            ).model_dump(mode="json")
        )
    return result

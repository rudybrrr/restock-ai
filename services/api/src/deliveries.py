from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations import lock_inventory, record_event
from src.operations_schemas import (
    Delivery,
    DeliveryCreate,
    DeliveryUpdate,
    ReceiptCreate,
)


def read_delivery(session: Session, delivery_id: str) -> Delivery:
    row = (
        session.execute(select(db.deliveries).where(db.deliveries.c.id == delivery_id))
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "DELIVERY_NOT_FOUND", "Delivery does not exist")
    receipts = (
        session.execute(
            select(db.delivery_receipts)
            .where(
                db.delivery_receipts.c.delivery_id == delivery_id,
            )
            .order_by(db.delivery_receipts.c.received_at, db.delivery_receipts.c.id)
        )
        .mappings()
        .all()
    )
    received = sum((r["quantity"] for r in receipts), Decimal("0.000"))
    return Delivery.model_validate(
        {
            **row,
            "receipts": receipts,
            "received_quantity": received,
            "outstanding_quantity": row["expected_quantity"]
            - received
            - row["cancelled_quantity"],
        }
    )


def delivery_event(
    session: Session,
    event_type: str,
    actor: str,
    delivery: Delivery,
    effective_at,
    receipt_id: str | None = None,
) -> None:
    record_event(
        session,
        event_type,
        actor,
        {
            "delivery": delivery.model_dump(mode="json"),
            "effective_at": effective_at.isoformat(),
            "receipt_id": receipt_id,
        },
    )


def create_delivery(session: Session, body: DeliveryCreate, actor: str) -> Delivery:
    lock_inventory(session)
    offer = session.execute(
        select(db.supplier_offers.c.id).where(
            db.supplier_offers.c.supplier_id == body.supplier_id,
            db.supplier_offers.c.ingredient_id == body.ingredient_id,
        )
    ).first()
    if offer is None:
        raise ApiError(
            422, "UNAPPROVED_SUPPLIER", "Use an approved supplier and ingredient offer"
        )
    if body.expected_at < body.ordered_at:
        raise ApiError(
            422, "INVALID_ARRIVAL", "Expected arrival cannot precede the purchase"
        )
    delivery_id = str(uuid4())
    session.execute(insert(db.deliveries).values(id=delivery_id, **body.model_dump()))
    result = read_delivery(session, delivery_id)
    delivery_event(session, "EXTERNAL_ORDER_RECORDED", actor, result, body.ordered_at)
    session.commit()
    return result


def update_delivery(
    session: Session, delivery_id: str, body: DeliveryUpdate, actor: str
) -> Delivery:
    lock_inventory(session)
    previous = read_delivery(session, delivery_id)
    if (
        body.expected_quantity < previous.received_quantity
        or body.expected_at < previous.ordered_at
        or body.effective_at < previous.ordered_at
    ):
        raise ApiError(
            422,
            "INVALID_DELIVERY_UPDATE",
            "Expectations must preserve actual receipts and purchase time",
        )
    if previous.outstanding_quantity == 0:
        raise ApiError(
            409,
            "DELIVERY_CLOSED",
            "A completed or cancelled delivery cannot be reopened",
        )
    cancelled = (
        body.expected_quantity - previous.received_quantity
        if body.cancel_remainder
        else Decimal(0)
    )
    session.execute(
        update(db.deliveries)
        .where(db.deliveries.c.id == delivery_id)
        .values(
            expected_quantity=body.expected_quantity,
            expected_at=body.expected_at,
            cancelled_quantity=cancelled,
        )
    )
    result = read_delivery(session, delivery_id)
    delivery_event(session, "DELIVERY_UPDATED", actor, result, body.effective_at)
    if body.expected_at > previous.expected_at:
        delivery_event(session, "DELIVERY_DELAYED", actor, result, body.effective_at)
    if body.expected_quantity < previous.expected_quantity:
        delivery_event(session, "DELIVERY_SHORT", actor, result, body.effective_at)
    if body.cancel_remainder:
        delivery_event(session, "DELIVERY_CANCELLED", actor, result, body.effective_at)
    session.commit()
    return result


def receive_delivery(
    session: Session, delivery_id: str, body: ReceiptCreate, actor: str
) -> Delivery:
    lock_inventory(session)
    previous = read_delivery(session, delivery_id)
    for receipt in previous.receipts:
        if receipt.request_id == body.request_id:
            if (
                ReceiptCreate.model_validate(
                    receipt.model_dump(include=set(ReceiptCreate.model_fields))
                )
                != body
            ):
                raise ApiError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Receipt identity already has different contents",
                )
            return previous
    if body.quantity > previous.outstanding_quantity:
        raise ApiError(
            409, "RECEIPT_EXCEEDS_REMAINDER", "Receipt exceeds outstanding quantity"
        )
    if (
        body.received_at < previous.ordered_at
        or body.expiry_date
        < body.received_at.astimezone(ZoneInfo("Asia/Singapore")).date()
    ):
        raise ApiError(
            422,
            "INVALID_RECEIPT_TIME",
            "Receipt must follow purchase and precede expiry",
        )
    # A late-reported lot would invalidate a completed stocktake's completeness.
    cutoff = session.execute(
        select(db.daily_revisions.c.cutoff)
        .where(
            db.daily_revisions.c.cutoff >= body.received_at,
        )
        .limit(1)
    ).first()
    if cutoff:
        raise ApiError(
            409,
            "STOCKTAKE_CONFLICT",
            "Receipt precedes an existing closing cutoff; reconcile before recording",
        )
    lot_id, receipt_id = str(uuid4()), str(uuid4())
    session.execute(
        insert(db.inventory_lots).values(
            id=lot_id,
            ingredient_id=previous.ingredient_id,
            received_at=body.received_at,
            expiry_date=body.expiry_date,
            initial_quantity=body.quantity,
        )
    )
    session.execute(
        insert(db.stock_counts).values(
            id=str(uuid4()),
            lot_id=lot_id,
            quantity=body.quantity,
            counted_at=body.received_at,
        )
    )
    session.execute(
        insert(db.delivery_receipts).values(
            id=receipt_id, delivery_id=delivery_id, lot_id=lot_id, **body.model_dump()
        )
    )
    if body.remainder == "CANCELLED":
        session.execute(
            update(db.deliveries)
            .where(db.deliveries.c.id == delivery_id)
            .values(cancelled_quantity=previous.outstanding_quantity - body.quantity)
        )
    result = read_delivery(session, delivery_id)
    delivery_event(
        session, "DELIVERY_RECEIVED", actor, result, body.received_at, receipt_id
    )
    if body.remainder == "CANCELLED" and result.cancelled_quantity > 0:
        delivery_event(
            session, "DELIVERY_CANCELLED", actor, result, body.received_at, receipt_id
        )
    session.commit()
    return result

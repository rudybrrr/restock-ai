from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src import database as db
from src import deliveries, operations
from src.auth import SessionDep, authenticate, require_browser_origin, require_manager
from src.operations_schemas import (
    AuditEntry,
    DailyDraft,
    DailyHistory,
    DailyRevision,
    Delivery,
    DeliveryCreate,
    DeliveryUpdate,
    Event,
    ReceiptCreate,
)
from src.schemas import Identity

router = APIRouter(
    tags=["Daily updates and deliveries"], dependencies=[Depends(authenticate)]
)
Manager = Annotated[Identity, Depends(require_manager)]
mutation = [Depends(require_browser_origin)]


@router.post(
    "/daily-updates/{day}/draft", response_model=DailyDraft, dependencies=mutation
)
def save_draft(day: date, body: DailyDraft, session: SessionDep, manager: Manager):
    return operations.save_draft(session, day, body)


@router.post(
    "/daily-updates/{day}/submit", response_model=DailyRevision, dependencies=mutation
)
def submit_day(day: date, session: SessionDep, manager: Manager):
    return operations.submit_day(session, day, manager.username)


@router.get("/daily-updates/{day}", response_model=DailyHistory)
def read_day(day: date, session: SessionDep):
    return operations.read_day(session, day)


@router.get("/events", response_model=list[Event])
def events(session: SessionDep):
    return (
        session.execute(select(db.events).order_by(db.events.c.timestamp))
        .mappings()
        .all()
    )


@router.get("/audit", response_model=list[AuditEntry])
def audit(session: SessionDep):
    return (
        session.execute(select(db.audit_entries).order_by(db.audit_entries.c.timestamp))
        .mappings()
        .all()
    )


@router.post(
    "/deliveries", response_model=Delivery, status_code=201, dependencies=mutation
)
def create_delivery(body: DeliveryCreate, session: SessionDep, manager: Manager):
    return deliveries.create_delivery(session, body, manager.username)


@router.get("/deliveries", response_model=list[Delivery])
def list_deliveries(session: SessionDep):
    return [
        deliveries.read_delivery(session, key)
        for key in session.execute(
            select(db.deliveries.c.id).order_by(db.deliveries.c.id)
        ).scalars()
    ]


@router.get("/deliveries/{delivery_id}", response_model=Delivery)
def read_delivery(delivery_id: str, session: SessionDep):
    return deliveries.read_delivery(session, delivery_id)


@router.post(
    "/deliveries/{delivery_id}/update", response_model=Delivery, dependencies=mutation
)
def update_delivery(
    delivery_id: str, body: DeliveryUpdate, session: SessionDep, manager: Manager
):
    return deliveries.update_delivery(session, delivery_id, body, manager.username)


@router.post(
    "/deliveries/{delivery_id}/receive", response_model=Delivery, dependencies=mutation
)
def receive_delivery(
    delivery_id: str, body: ReceiptCreate, session: SessionDep, manager: Manager
):
    return deliveries.receive_delivery(session, delivery_id, body, manager.username)

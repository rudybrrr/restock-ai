from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src import database as db
from src import deliveries, operations, planning, sales
from src.auth import (
    SessionDep,
    authenticate,
    require_agent,
    require_browser_origin,
    require_manager,
)
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
    SalesBatch,
    SalesBatchCreate,
)
from src.planning_schemas import (
    AssessmentRequest,
    Candidate,
    Completion,
    OptimiseRequest,
    PlanningRun,
    PurchasePlanVersion,
)
from src.schemas import EstimatedInventoryLot, Identity

router = APIRouter(
    tags=["Daily updates and deliveries"], dependencies=[Depends(authenticate)]
)
Manager = Annotated[Identity, Depends(require_manager)]
Agent = Annotated[Identity, Depends(require_agent)]
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
    "/sales-batches", response_model=SalesBatch, status_code=201, dependencies=mutation
)
def create_sales_batch(body: SalesBatchCreate, session: SessionDep, manager: Manager):
    return sales.create_sales_batch(session, body, manager.username)


@router.get("/inventory/estimated", response_model=list[EstimatedInventoryLot])
def estimated_inventory(as_of: datetime, session: SessionDep):
    return sales.estimated_inventory(session, as_of)


@router.post(
    "/assessments", response_model=PlanningRun, status_code=202, dependencies=mutation
)
def request_assessment(body: AssessmentRequest, session: SessionDep, manager: Manager):
    return planning.request_run(session, body.as_of)


@router.get("/runs/{run_id}", response_model=PlanningRun)
def read_run(run_id: str, session: SessionDep):
    return planning.get_run(session, run_id)


@router.post("/runs/claim", response_model=PlanningRun)
def claim_run(session: SessionDep, agent: Agent):
    return planning.claim_run(session)


@router.post("/runs/{run_id}/tools/optimise", response_model=Candidate)
def optimise_run(run_id: str, body: OptimiseRequest, session: SessionDep, agent: Agent):
    return planning.optimise(session, run_id, body)


@router.post("/runs/{run_id}/complete", response_model=PlanningRun)
def complete_run(run_id: str, body: Completion, session: SessionDep, agent: Agent):
    return planning.complete_run(session, run_id, body)


@router.get("/plans/{version_id}", response_model=PurchasePlanVersion)
def read_plan(version_id: str, session: SessionDep):
    return planning.read_plan(session, version_id)


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

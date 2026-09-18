from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime
from sqlalchemy import select

from src import (
    changes,
    cycles,
    deliveries,
    inventory_adjustment_contracts,
    operations,
    planning,
    procurement_contracts,
    sales,
    sales_materiality_contracts,
)
from src import database as db
from src.auth import (
    SessionDep,
    authenticate,
    require_agent,
    require_browser_origin,
    require_manager,
)
from src.errors import ApiError
from src.inventory_adjustment_schemas import (
    InventoryAdjustmentAssessment,
    InventoryAdjustmentContext,
    InventoryAdjustmentResultWrite,
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
    AssessmentTrigger,
    Candidate,
    Completion,
    OptimiseRequest,
    PlanDecision,
    PlanningRun,
    PurchasePlanVersion,
    StoredPlanLine,
)
from src.procurement_contract_schemas import (
    ProcurementContract,
    ProcurementDisplay,
    ProcurementPolicyVersion,
)
from src.sales_materiality_schemas import (
    SalesMaterialityAssessment,
    SalesMaterialityContext,
    SalesMaterialityRequestCreate,
    SalesMaterialityResultWrite,
)
from src.sales_threshold_schemas import SalesThresholdPolicyVersion
from src.schemas import EstimatedInventoryLot, Identity, SupplierOffer

router = APIRouter(
    tags=["Daily updates and deliveries"], dependencies=[Depends(authenticate)]
)
Manager = Annotated[Identity, Depends(require_manager)]
Agent = Annotated[Identity, Depends(require_agent)]
mutation = [Depends(require_browser_origin)]


@router.put(
    "/promotions/{promotion_id}",
    response_model=changes.Promotion,
    dependencies=mutation,
)
def save_promotion(
    promotion_id: str,
    body: changes.PromotionInput,
    session: SessionDep,
    manager: Manager,
):
    return changes.save_promotion(session, promotion_id, body, manager.username)


@router.get("/promotions", response_model=list[changes.Promotion])
def list_promotions(session: SessionDep):
    return [
        {"id": row["id"], **row["payload"]}
        for row in session.execute(
            select(db.promotions).order_by(db.promotions.c.id)
        ).mappings()
    ]


@router.patch(
    "/supplier-offers/{offer_id}", response_model=SupplierOffer, dependencies=mutation
)
def change_supplier(
    offer_id: str, body: changes.SupplierChange, session: SessionDep, manager: Manager
):
    return changes.change_supplier(session, offer_id, body, manager.username)


@router.get("/order-cycles", response_model=list[cycles.OrderCycle])
def list_order_cycles(start: date, end: date, session: SessionDep):
    return cycles.list_cycles(session, start, end)


@router.post(
    "/order-cycles/{ingredient_id}/{day}/decision",
    response_model=cycles.OrderCycle,
    dependencies=mutation,
)
def decide_order_cycle(
    ingredient_id: str,
    day: date,
    body: cycles.CycleDecision,
    session: SessionDep,
    manager: Manager,
):
    return cycles.decide_cycle(session, ingredient_id, day, body, manager.username)


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
def estimated_inventory(as_of: AwareDatetime, session: SessionDep):
    return sales.estimated_inventory(session, as_of)


@router.post(
    "/assessments", response_model=PlanningRun, status_code=202, dependencies=mutation
)
def request_assessment(body: AssessmentRequest, session: SessionDep, manager: Manager):
    return planning.request_run(session, body.as_of, body.revises_plan_id)


@router.get("/runs/{run_id}", response_model=PlanningRun)
def read_run(run_id: str, session: SessionDep):
    return planning.get_run(session, run_id)


@router.get(
    "/manager/procurement-policies", response_model=list[ProcurementPolicyVersion]
)
def list_manager_procurement_policies(session: SessionDep, manager: Manager):
    """Discover persisted versions, without implying a version applies to every run."""
    return (
        session.execute(
            select(db.procurement_policy_versions).order_by(
                db.procurement_policy_versions.c.recorded_at.desc(),
                db.procurement_policy_versions.c.version.desc(),
            )
        )
        .mappings()
        .all()
    )


@router.get(
    "/manager/procurement-policies/{policy_id}/versions/{version}",
    response_model=ProcurementDisplay,
)
def read_manager_procurement_policy(
    policy_id: str, version: int, session: SessionDep, manager: Manager
):
    contract = procurement_contracts.read_policy_contract(session, policy_id, version)
    return ProcurementDisplay(
        policy=contract.policy,
        domain=contract.domain,
        forecast_input=contract.forecast_input,
    )


@router.get(
    "/manager/runs/{run_id}/procurement-evidence", response_model=ProcurementDisplay
)
def read_manager_run_procurement_evidence(
    run_id: str, session: SessionDep, manager: Manager
):
    run = planning.get_run(session, run_id)
    value = run.snapshot.get("procurement_contract")
    if value is None:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "No frozen procurement contract recorded for this run",
        )
    contract = ProcurementContract.model_validate(value)
    return ProcurementDisplay(
        policy=contract.policy,
        domain=contract.domain,
        forecast_input=contract.forecast_input,
    )


@router.get(
    "/procurement-policies/{policy_id}/versions/{version}",
    response_model=ProcurementContract,
)
def read_procurement_policy(
    policy_id: str, version: int, session: SessionDep, agent: Agent
):
    """Canonical policy/domain source; no current operational state is inferred."""
    return procurement_contracts.read_policy_contract(session, policy_id, version)


@router.get("/runs/{run_id}/procurement-contract", response_model=ProcurementContract)
def read_frozen_procurement_contract(run_id: str, session: SessionDep, agent: Agent):
    """Agent adapter boundary: return exactly the contract frozen at claim time."""
    run = planning.get_run(session, run_id)
    contract = run.snapshot.get("procurement_contract")
    if contract is None:
        reason = run.snapshot.get("procurement_contract_unavailable_reason")
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "First-slice procurement contract is unavailable"
            + (f": {reason}" if reason else ""),
        )
    return ProcurementContract.model_validate(contract)


@router.get(
    "/sales-threshold-policies/{version}",
    response_model=SalesThresholdPolicyVersion,
)
def read_sales_threshold_policy(version: str, session: SessionDep, agent: Agent):
    return sales_materiality_contracts.read_policy(session, version)


@router.get(
    "/runs/{run_id}/sales-materiality-context",
    response_model=SalesMaterialityContext,
)
def read_sales_materiality_context(run_id: str, session: SessionDep, agent: Agent):
    run = planning.get_run(session, run_id)
    raw = run.snapshot.get("procurement_contract")
    if raw is None:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Run has no frozen procurement contract",
        )
    return sales_materiality_contracts.context_from_contract(
        ProcurementContract.model_validate(raw)
    )


@router.post(
    "/runs/{run_id}/sales-materiality-requests",
    response_model=SalesMaterialityAssessment,
    status_code=201,
)
def create_sales_materiality_request(
    run_id: str,
    body: SalesMaterialityRequestCreate,
    session: SessionDep,
    agent: Agent,
):
    return sales_materiality_contracts.create_request(session, run_id, body)


@router.get(
    "/runs/{run_id}/sales-materiality-assessment",
    response_model=SalesMaterialityAssessment,
)
def read_sales_materiality_assessment(run_id: str, session: SessionDep, agent: Agent):
    planning.get_run(session, run_id)
    return sales_materiality_contracts.read_assessment(session, run_id)


@router.put(
    "/runs/{run_id}/sales-materiality-requests/{request_id}/result",
    response_model=SalesMaterialityAssessment,
)
def save_sales_materiality_result(
    run_id: str,
    request_id: str,
    body: SalesMaterialityResultWrite,
    session: SessionDep,
    agent: Agent,
):
    return sales_materiality_contracts.save_result(session, run_id, request_id, body)


@router.get(
    "/runs/{run_id}/inventory-adjustment-context",
    response_model=InventoryAdjustmentContext,
)
def read_inventory_adjustment_context(run_id: str, session: SessionDep, agent: Agent):
    return inventory_adjustment_contracts.context_from_run(
        planning.get_run(session, run_id)
    )


@router.get(
    "/runs/{run_id}/inventory-adjustment-assessment",
    response_model=InventoryAdjustmentAssessment,
)
def read_inventory_adjustment_assessment(
    run_id: str, session: SessionDep, agent: Agent
):
    return inventory_adjustment_contracts.read_assessment(session, run_id)


@router.put(
    "/runs/{run_id}/inventory-adjustment-assessment",
    response_model=InventoryAdjustmentAssessment,
)
def save_inventory_adjustment_assessment(
    run_id: str,
    body: InventoryAdjustmentResultWrite,
    session: SessionDep,
    agent: Agent,
):
    return inventory_adjustment_contracts.save_result(session, run_id, body)


@router.get("/runs", response_model=list[PlanningRun])
def list_runs(session: SessionDep):
    return (
        session.execute(
            select(db.planning_runs)
            .order_by(db.planning_runs.c.created_at.desc())
            .limit(100)
        )
        .mappings()
        .all()
    )


@router.post(
    "/runs/{run_id}/retry",
    response_model=PlanningRun,
    status_code=202,
    dependencies=mutation,
)
def retry_run(
    run_id: str, body: AssessmentRequest, session: SessionDep, manager: Manager
):
    return planning.retry_run(session, run_id, body.as_of)


@router.get("/plan-history", response_model=list[PurchasePlanVersion])
def plan_history(session: SessionDep):
    ids = (
        session.execute(
            select(db.plan_versions.c.id)
            .order_by(db.plan_versions.c.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return [planning.read_plan(session, version_id) for version_id in ids]


@router.get("/runs/{run_id}/triggers", response_model=list[AssessmentTrigger])
def read_run_triggers(run_id: str, session: SessionDep):
    planning.get_run(session, run_id)
    return (
        session.execute(
            select(db.assessment_requests)
            .where(db.assessment_requests.c.run_id == run_id)
            .order_by(db.assessment_requests.c.effective_at)
        )
        .mappings()
        .all()
    )


@router.post("/runs/claim", response_model=PlanningRun)
def claim_run(session: SessionDep, agent: Agent):
    return planning.claim_run(session)


@router.post("/runs/{run_id}/tools/optimise", response_model=Candidate)
def optimise_run(
    run_id: str,
    body: OptimiseRequest,
    session: SessionDep,
    agent: Agent,
    request: Request,
):
    if not request.app.state.settings.enable_development_calculator:
        raise ApiError(
            503,
            "DECISION_ENGINE_NOT_CONNECTED",
            "The ML decision engine is not connected. The limited development calculator requires explicit opt-in.",
        )
    return planning.optimise(session, run_id, body)


@router.post("/runs/{run_id}/complete", response_model=PlanningRun)
def complete_run(run_id: str, body: Completion, session: SessionDep, agent: Agent):
    return planning.complete_run(session, run_id, body)


@router.get("/plans/{version_id}", response_model=PurchasePlanVersion)
def read_plan(version_id: str, session: SessionDep):
    return planning.read_plan(session, version_id)


@router.get("/plans/{version_id}/lines", response_model=list[StoredPlanLine])
def read_plan_lines(version_id: str, session: SessionDep):
    planning.read_plan(session, version_id)
    lines = (
        session.execute(
            select(db.purchase_plan_lines)
            .where(db.purchase_plan_lines.c.plan_version_id == version_id)
            .order_by(db.purchase_plan_lines.c.id)
        )
        .mappings()
        .all()
    )
    result = []
    for line in lines:
        linked = deliveries.linked_quantity(session, line["id"])
        result.append(
            {
                **line,
                "linked_quantity": linked,
                "uncommitted_quantity": max(line["quantity"] - linked, 0),
            }
        )
    return result


@router.post(
    "/plans/{version_id}/decision",
    response_model=PurchasePlanVersion,
    dependencies=mutation,
)
def decide_plan(
    version_id: str, body: PlanDecision, session: SessionDep, manager: Manager
):
    return planning.decide_plan(session, version_id, body, manager.username)


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

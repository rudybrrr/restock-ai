from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: AwareDatetime
    revises_plan_id: str | None = None


class PlanningRun(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    trigger: str
    trigger_event_id: str | None = None
    as_of: AwareDatetime
    input_revision: int
    snapshot: dict
    outcome: (
        Literal[
            "KEEP_CURRENT_PLAN", "REVISE_PLAN", "REQUEST_HUMAN_APPROVAL", "ESCALATE"
        ]
        | None
    ) = None
    plan_version_id: str | None = None
    escalation_reason: str | None = None
    failure_reason: str | None = None
    created_at: AwareDatetime
    claimed_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None


class OptimiseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dish_quantities: dict[str, Annotated[int, Field(ge=0, strict=True)]]


class PlanLine(BaseModel):
    ingredient_id: str
    supplier_id: str
    quantity: Annotated[Decimal, Field(gt=0)]
    unit_price: Annotated[Decimal, Field(ge=0)]
    arrival_at: AwareDatetime


class Candidate(BaseModel):
    calculation_mode: Literal["DEVELOPMENT_FIXTURE", "ENGINE"] = "DEVELOPMENT_FIXTURE"
    forecast_id: str
    inventory_snapshot_id: str
    lines: list[PlanLine]
    total_purchase_cost: Decimal
    expected_waste_cost: Decimal = Decimal(0)
    expected_stockout_cost: Decimal = Decimal(0)
    delivery_cost: Decimal = Decimal(0)
    emergency_penalty: Decimal = Decimal(0)
    total_expected_cost: Decimal


class StoredPlanLine(PlanLine):
    id: str
    plan_version_id: str


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal[
        "KEEP_CURRENT_PLAN", "REVISE_PLAN", "REQUEST_HUMAN_APPROVAL", "ESCALATE"
    ]
    escalation_reason: (
        Literal[
            "MISSING_REQUIRED_DATA",
            "NO_FEASIBLE_SUPPLIER",
            "UNRESOLVED_SHORTAGE",
            "POLICY_VIOLATION",
            "TOOL_FAILURE",
        ]
        | None
    ) = None
    candidate: Candidate | None = None


class PurchasePlanVersion(Candidate):
    id: str
    plan_id: str
    version: int
    status: Literal[
        "PENDING_APPROVAL", "APPROVED", "REJECTED", "INVALIDATED", "SUPERSEDED"
    ]
    run_id: str
    created_at: AwareDatetime


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    plan_version: Annotated[int, Field(gt=0)]
    decision: Literal["APPROVED", "REJECTED"]
    instructions: str | None = Field(default=None, max_length=1000)


class AssessmentTrigger(BaseModel):
    event_id: str
    run_id: str
    effective_at: AwareDatetime

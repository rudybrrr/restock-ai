"""Backend contract for deterministic closing-count correction assessment."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from src.operations_schemas import InventoryAdjustmentEvent
from src.schemas import EstimatedInventoryLot


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryAdjustmentContext(StrictModel):
    supported: Literal[True] = True
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    snapshot_reference: str
    inventory_snapshot_reference: str
    procurement_contract_reference: str | None
    plan_id: str | None
    plan_version_reference: str | None
    required_evidence_refs: list[str]
    assessed_lot_ids: list[str]
    assessed_ingredient_ids: list[str]
    adjustment_events: list[InventoryAdjustmentEvent] = Field(min_length=1)
    inventory: list[EstimatedInventoryLot]


class InventoryAdjustmentFinding(StrictModel):
    code: str
    source: str


class InventoryAdjustmentResult(StrictModel):
    material_change: bool | None
    complete: bool
    inventory_feasible: bool | None
    assessed_lot_ids: list[str]
    assessed_ingredient_ids: list[str]
    findings: list[InventoryAdjustmentFinding]
    evidence_refs: list[str]
    required_follow_up: list[str]
    run_id: str
    snapshot_reference: str
    inventory_snapshot_reference: str
    captured_state_revision: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    adjustment_event_ids: list[str]
    plan_id: str | None
    plan_version_reference: str | None

    @model_validator(mode="after")
    def non_material_requires_complete_assessment(self) -> "InventoryAdjustmentResult":
        if self.material_change is False and (
            not self.complete or self.inventory_feasible is not True
        ):
            raise ValueError(
                "Non-material certification requires a complete feasible result"
            )
        return self


class InventoryAdjustmentResultWrite(StrictModel):
    result: InventoryAdjustmentResult


class InventoryAdjustmentAssessment(StrictModel):
    result_reference: str
    result_sha256: str
    result: InventoryAdjustmentResult
    completed_at: AwareDatetime

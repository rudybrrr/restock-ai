"""Backend-owned transport for the approved sales-materiality calculation."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from src.history_dataset import Catalogue
from src.procurement_contract_schemas import ForecastInputArtifact, ProcurementContract
from src.promotion_forecasting import ForecastVersion
from src.sales_threshold_schemas import (
    FrozenSalesThresholdPolicy,
    MaterialityEvidence,
    SalesThresholdPolicyPayload,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SalesMaterialityContext(StrictModel):
    supported: Literal[True] = True
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    procurement_contract_reference: str
    snapshot_reference: str
    snapshot_evidence: MaterialityEvidence
    forecast_input_reference: str
    policy: FrozenSalesThresholdPolicy


class SalesMaterialityRequestCreate(StrictModel):
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    captured_state_revision: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    known_at: AwareDatetime
    issued_forecast_reference: Annotated[str, Field(min_length=1)]
    issued_forecast: ForecastVersion
    plan_reference: str | None = None
    safety_reference: Annotated[str, Field(min_length=1)]
    risk: dict[str, JsonValue] | None


class SalesThresholdPolicyInput(SalesThresholdPolicyPayload):
    evidence: MaterialityEvidence


class SalesMaterialityEngineRequest(StrictModel):
    contract_reference: str
    contract: ProcurementContract
    issued_forecast_reference: str
    issued_forecast: ForecastVersion
    issued_input: ForecastInputArtifact
    issued_catalogue: Catalogue
    snapshot_evidence: MaterialityEvidence
    threshold_policy: SalesThresholdPolicyInput
    plan_reference: str | None
    safety_reference: str
    risk: dict[str, JsonValue] | None


class MaterialityFinding(StrictModel):
    code: str
    source: str


class SalesDeviationResult(StrictModel):
    dish_id: str
    expected: Decimal | None
    observed: Decimal | None
    deviation: Decimal | None
    threshold: Decimal | None
    adequate_exposure: bool | None
    material: bool | None


class SafetyBreachResult(StrictModel):
    ingredient_id: str
    at: AwareDatetime
    deficit: Decimal


class ShortageIntervalResult(StrictModel):
    ingredient_id: str
    start: AwareDatetime
    end: AwareDatetime


class SalesMaterialityResult(StrictModel):
    material_change: bool | None
    complete: bool
    feasible_under_observed_state: bool | None
    inventory_feasible: bool | None
    assessed_scope: list[
        Literal["SALES_DEVIATION", "PHYSICAL_SHORTAGE", "SAFETY_STOCK"]
    ]
    sales: list[SalesDeviationResult]
    projection: dict[str, JsonValue] | None
    safety_breaches: list[SafetyBreachResult]
    first_stockout_interval: ShortageIntervalResult | None
    first_safety_breach_at: AwareDatetime | None
    first_risk_at: AwareDatetime | None
    affected_ids: list[str]
    compared_intervals: list[tuple[AwareDatetime, AwareDatetime]]
    missing_intervals: list[tuple[AwareDatetime, AwareDatetime]]
    remainder: dict[str, JsonValue] | None
    daily_history: list[dict[str, JsonValue]] | None
    findings: list[MaterialityFinding]
    material_findings: list[MaterialityFinding]
    evidence_refs: list[str]
    required_follow_up: list[str]
    run_id: str
    snapshot_reference: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    forecast_reference: str | None
    forecast_input_reference: str
    threshold_policy_version: Literal["SALES_MATERIALITY_V1"]
    coverage_through: AwareDatetime
    limitations: list[str]

    @model_validator(mode="after")
    def false_requires_complete_scope(self) -> "SalesMaterialityResult":
        if self.material_change is False and not self.complete:
            raise ValueError("Non-material certification requires a complete result")
        return self


class SalesMaterialityResultWrite(StrictModel):
    request_reference: str
    result: SalesMaterialityResult


class SalesMaterialityAssessment(StrictModel):
    id: str
    run_id: str
    policy_version_id: str
    captured_state_revision: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    request_reference: str
    request_sha256: str
    engine_request: SalesMaterialityEngineRequest
    result_reference: str | None
    result_sha256: str | None
    result: SalesMaterialityResult | None
    created_at: AwareDatetime
    completed_at: AwareDatetime | None


class SalesMaterialityDisplay(StrictModel):
    """Manager evidence without the full engine request or frozen operational state."""

    run_id: str
    request_reference: str
    result_reference: str | None
    created_at: AwareDatetime
    completed_at: AwareDatetime | None
    result: SalesMaterialityResult | None

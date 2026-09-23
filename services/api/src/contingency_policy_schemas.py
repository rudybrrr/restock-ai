"""Backend-owned, versioned policy values for the bounded contingency slice."""

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContingencyPolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE"]
    activation_state: Literal["STAGED", "ACTIVE"]
    objective_policy: Literal["BOUNDED_CONTINGENCY_CASH_V1"]
    search_policy: Literal["CONTINGENCY_CARTESIAN_V1"]
    fee_policy: Literal["EXPLICIT_NEW_SHIPMENT_ONCE_V1"]
    cash_policy: Literal["CASH_SLICE_V1"]
    expiry_policy: Literal["EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1"]
    tie_break_policy: Literal["SUPPLIER_ID_THEN_INGREDIENT_ID_V1"]
    reliability_mode: Literal["CONTEXT_ONLY"]
    constraint_policy: Literal["SERVICE_END_SAFETY_RECEIPT_STORAGE_V1"]
    fefo_policy: Literal["FEFO_EXPIRY_RECEIVED_LOT_ID_V1"]
    currency: Literal["SGD"]
    issue_time: AwareDatetime
    new_order_budget_sgd: Decimal = Field(ge=0)
    safety_stock: dict[str, Decimal]
    storage_limits: dict[str, Decimal]
    protected_end: dict[str, AwareDatetime]
    assessment_end: dict[str, AwareDatetime]
    max_horizon_days: int = Field(gt=0, le=31)
    work_limit: int = Field(gt=0, le=1_000_000)
    approved_domain_id: str | None
    forecast_artifact_id: str | None

    @model_validator(mode="after")
    def complete_policy(self) -> "ContingencyPolicyPayload":
        ingredients = set(self.safety_stock)
        if not ingredients or any(
            set(values) != ingredients
            for values in (
                self.storage_limits,
                self.protected_end,
                self.assessment_end,
            )
        ):
            raise ValueError("All ingredient policy vectors need the same manifest")
        if any(value < 0 for value in self.safety_stock.values()) or any(
            value < 0 for value in self.storage_limits.values()
        ):
            raise ValueError("Safety and storage values cannot be negative")
        latest = self.issue_time + timedelta(days=self.max_horizon_days)
        if any(
            not self.issue_time
            < self.protected_end[key]
            <= self.assessment_end[key]
            <= latest
            for key in ingredients
        ):
            raise ValueError("Coverage and assessment ends must fit the issue horizon")
        if self.activation_state == "ACTIVE" and (
            not self.approved_domain_id or not self.forecast_artifact_id
        ):
            raise ValueError("An active policy requires domain and forecast references")
        return self


class ContingencyPolicyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    policy_id: str
    version: int = Field(gt=0)
    effective_at: AwareDatetime
    recorded_at: AwareDatetime
    source_revision: str
    payload: ContingencyPolicyPayload

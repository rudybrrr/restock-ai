"""Versioned Backend transport for the approved sales threshold policy."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ThresholdModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialityEvidence(ThresholdModel):
    reference: str = Field(min_length=1)
    available_at: AwareDatetime
    captured_revision: str = Field(min_length=1)


class SalesThresholdPolicyPayload(ThresholdModel):
    version: Literal["SALES_MATERIALITY_V1"]
    rule: Literal["V2_DEMO_ABSOLUTE_OR_RELATIVE_V1"]
    absolute_floor: Annotated[Decimal, Field(ge=0)]
    relative_threshold: Annotated[Decimal, Field(ge=0)]
    minimum_expected_portions: Annotated[Decimal, Field(ge=0)]
    minimum_complete_buckets: Literal[2]
    scope: Literal["ONE_SINGAPORE_SERVICE_DAY_PER_DISH_CUMULATIVE_COMPLETE_HALF_HOURS"]


class SalesThresholdPolicyVersion(ThresholdModel):
    id: str
    version: Literal["SALES_MATERIALITY_V1"]
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    recorded_at: AwareDatetime
    source_revision: str
    payload: SalesThresholdPolicyPayload


class FrozenSalesThresholdPolicy(SalesThresholdPolicyVersion):
    evidence: MaterialityEvidence

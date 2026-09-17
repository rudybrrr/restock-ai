"""Backend-owned transport for an immutable first-slice procurement contract."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.schemas import SupplierOffer


class ServicePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime
    weight: Decimal = Field(gt=0, le=1)


class ProcurementPolicyPayload(BaseModel):
    """Policy semantics, independently of a particular live run."""

    model_config = ConfigDict(extra="forbid")

    objective_policy: Literal["CASH_SLICE_V1"]
    currency: Literal["SGD"]
    new_order_budget_sgd: Decimal = Field(ge=0)
    target_date: date
    issue_time: AwareDatetime
    horizon_end: AwareDatetime
    timezone: Literal["Asia/Singapore"]
    bucket_minutes: Literal[30]
    service_profile: list[ServicePeriod]
    safety_stock: dict[str, Decimal]
    storage_limits: dict[str, Decimal]
    fee_policy: Literal["SUPPLIER_ARRIVAL_ONCE_V1"]
    fee_grouping: Literal["SUPPLIER_ID_AND_ARRIVAL_AT"]
    emergency_mode: Literal["NORMAL_ONLY"]
    reliability_mode: Literal["CONTEXT_ONLY"]
    fefo_policy: Literal["FEFO_EXPIRY_RECEIVED_LOT_ID_V1"]
    new_supply_expiry_policy: Literal["EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1"]
    tie_break_policy: Literal["SUPPLIER_ID_THEN_INGREDIENT_ID_V1"]
    search_policy: Literal["COMPLETE_PRUNED_DOMAIN_V1"]
    approved_domain_id: str
    approved_supplier_ids: list[str]
    expected_offer_count: Literal[24]
    expected_opportunity_count: Literal[24]
    explicit_empty_post_count_activity: Literal[True]
    explicit_empty_outstanding_commitments: Literal[True]


class ProcurementPolicyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    policy_id: str
    version: int = Field(gt=0)
    effective_at: AwareDatetime
    recorded_at: AwareDatetime
    payload: ProcurementPolicyPayload


class FrozenOfferRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    offer_id: str
    supplier_id: str
    ingredient_id: str
    source_revision: str
    offer: SupplierOffer


class FrozenOrderingOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    opportunity_id: str
    offer_id: str
    ordered_at: AwareDatetime
    arrival_at: AwareDatetime
    kind: Literal["NORMAL", "EMERGENCY"]
    expiry_date: date
    source_revision: str


class ProcurementDomainPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["FIRST_SLICE_SYNTHETIC_FIXTURE"]
    source_description: str
    opening_lot_ids: list[str]


class ApprovedProcurementDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    domain_id: str
    version: int = Field(gt=0)
    source_revision: str
    recorded_at: AwareDatetime
    payload: ProcurementDomainPayload
    offers: list[FrozenOfferRevision]
    opportunities: list[FrozenOrderingOpportunity]


class HistoricalDemandObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_date: date
    available_at: AwareDatetime
    revision: int = Field(gt=0)
    promotion: bool
    censored: bool
    portions: dict[str, Annotated[int, Field(ge=0)]]


class ForecastInputPayload(BaseModel):
    """Versioned historical inputs for the deterministic forecast kernel."""

    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["FIRST_SLICE_SYNTHETIC_HISTORY"]
    forecast_method: Literal["SEASONAL_BASELINE_V1"]
    target_date: date
    menu_item_ids: list[str] = Field(min_length=1)
    history: list[HistoricalDemandObservation] = Field(min_length=4, max_length=4)


class ForecastInputArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    policy_version_id: str
    artifact_id: str
    version: int = Field(gt=0)
    effective_at: AwareDatetime
    recorded_at: AwareDatetime
    source_revision: str
    payload: ForecastInputPayload


class ProcurementContract(BaseModel):
    """Exact backend evidence an Agent adapter may pass to pure numerical code."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    policy: ProcurementPolicyVersion
    domain: ApprovedProcurementDomain
    forecast_input: ForecastInputArtifact
    frozen_state: dict | None = None

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Quantity = Annotated[
    Decimal,
    Field(
        ge=0,
        max_digits=12,
        decimal_places=3,
        examples=["10.000"],
        json_schema_extra={"example": "10.000"},
    ),
]

EventType = Literal[
    "PROMOTION_CREATED",
    "PROMOTION_CHANGED",
    "SUPPLIER_AVAILABILITY_CHANGED",
    "SUPPLIER_PRICE_CHANGED",
    "SUPPLIER_STATUS_CHANGED",
    "SUPPLIER_RELIABILITY_UPDATED",
    "DAILY_UPDATE_SUBMITTED",
    "EXTERNAL_ORDER_RECORDED",
    "DELIVERY_UPDATED",
    "DELIVERY_DELAYED",
    "DELIVERY_SHORT",
    "DELIVERY_RECEIVED",
    "DELIVERY_CANCELLED",
    "SALES_UPDATED",
    "INVENTORY_LOT_EXPIRED",
    "MANUAL_REASSESSMENT_REQUESTED",
    "PLAN_APPROVED",
    "PLAN_REJECTED",
    "PLAN_SUPERSEDED",
    "ORDER_CYCLE_UPDATED",
]


class DailyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutoff: AwareDatetime
    counts: dict[str, Quantity] = Field(default_factory=dict)
    sales: dict[str, Annotated[int, Field(ge=0, strict=True)]] = Field(
        default_factory=dict
    )


class SalesBatchCreate(BaseModel):
    """Complete interval report: omitted dishes explicitly mean zero, never partial coverage.

    Corrections keep source, batch_id and both interval bounds, using replaces_id
    to identify the active revision. Partial sales reports are not supported.
    """

    model_config = ConfigDict(extra="forbid")
    source: Annotated[str, Field(min_length=1, max_length=128)]
    batch_id: Annotated[str, Field(min_length=1, max_length=128)]
    period_start: AwareDatetime
    period_end: AwareDatetime
    sales: dict[str, Annotated[int, Field(ge=0, strict=True)]] = Field(
        default_factory=dict
    )
    replaces_id: str | None = None


class SalesBatch(SalesBatchCreate):
    model_config = ConfigDict(extra="ignore")
    id: str
    revision: int
    active: bool


class SalesBatchEventPayload(BaseModel):
    batch: SalesBatch


class SalesBatchEvent(BaseModel):
    id: str
    type: Literal["SALES_UPDATED"]
    timestamp: AwareDatetime
    source: str
    payload: SalesBatchEventPayload


class ExpiryEvent(BaseModel):
    id: str
    type: Literal["INVENTORY_LOT_EXPIRED"]
    timestamp: AwareDatetime
    source: str
    payload: dict


class ManualAssessmentEvent(BaseModel):
    id: str
    type: Literal["MANUAL_REASSESSMENT_REQUESTED"]
    timestamp: AwareDatetime
    source: str
    payload: dict


class SalesComparison(BaseModel):
    menu_item_id: str
    daily_total: int
    batch_total: int
    difference: int | None


class SalesReconciliation(BaseModel):
    period_start: AwareDatetime
    period_end: AwareDatetime
    batch_ids: list[str]
    status: Literal["MATCHED", "RECONCILIATION_DISCREPANCY", "INCOMPLETE_COVERAGE"]
    dishes: list[SalesComparison]


class DailyRevision(DailyDraft):
    reconciliation: SalesReconciliation | None = None
    model_config = ConfigDict(extra="ignore")
    id: str
    day: date
    revision: int
    recorded_at: AwareDatetime
    actor: str


class DailyHistory(BaseModel):
    draft: DailyDraft | None
    revisions: list[DailyRevision]


class DailyEventPayload(BaseModel):
    revision_id: str
    day: date
    revision: int
    cutoff: AwareDatetime


class DeliveryCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "supplier_id": "fresh-market",
                "ingredient_id": "chicken",
                "kind": "NORMAL",
                "expected_quantity": "10.000",
                "expected_at": "2026-02-16T10:00:00+08:00",
                "ordered_at": "2026-02-16T08:00:00+08:00",
            }
        },
    )
    supplier_id: str
    ingredient_id: str
    kind: Literal["NORMAL", "EMERGENCY"]
    expected_quantity: Annotated[Quantity, Field(gt=0)]
    expected_at: AwareDatetime
    ordered_at: AwareDatetime
    source_plan_line_id: str | None = None
    cycle_date: date | None = None


class DeliveryUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "expected_quantity": "8.000",
                "expected_at": "2026-02-16T12:00:00+08:00",
                "cancel_remainder": False,
                "effective_at": "2026-02-16T09:00:00+08:00",
            }
        },
    )
    expected_quantity: Annotated[Quantity, Field(gt=0)]
    expected_at: AwareDatetime
    cancel_remainder: bool = False
    effective_at: AwareDatetime


class ReceiptCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "request_id": "supplier-slip-001",
                "quantity": "4.000",
                "received_at": "2026-02-16T10:00:00+08:00",
                "expiry_date": "2026-02-19",
                "remainder": "EXPECTED",
                "closing_counts": {},
            }
        },
    )
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    quantity: Annotated[Quantity, Field(gt=0)]
    received_at: AwareDatetime
    expiry_date: date
    remainder: Literal["EXPECTED", "CANCELLED"]
    closing_counts: dict[date, Quantity] = Field(default_factory=dict)


class Receipt(ReceiptCreate):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "receipt-001",
                "delivery_id": "delivery-001",
                "lot_id": "lot-001",
                "request_id": "supplier-slip-001",
                "quantity": "4.000",
                "received_at": "2026-02-16T10:00:00+08:00",
                "expiry_date": "2026-02-19",
                "remainder": "EXPECTED",
                "closing_counts": {},
            }
        },
    )
    id: str
    delivery_id: str
    lot_id: str


class Delivery(DeliveryCreate):
    source_validation: Literal["MANUAL", "APPROVED_ALLOCATION", "LEGACY_REFERENCE"] = (
        "LEGACY_REFERENCE"
    )
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "delivery-001",
                "supplier_id": "fresh-market",
                "ingredient_id": "chicken",
                "kind": "NORMAL",
                "expected_quantity": "10.000",
                "expected_at": "2026-02-16T10:00:00+08:00",
                "ordered_at": "2026-02-16T08:00:00+08:00",
                "received_quantity": "4.000",
                "cancelled_quantity": "0.000",
                "outstanding_quantity": "6.000",
                "receipts": [
                    {
                        "id": "receipt-001",
                        "delivery_id": "delivery-001",
                        "lot_id": "lot-001",
                        "request_id": "supplier-slip-001",
                        "quantity": "4.000",
                        "received_at": "2026-02-16T10:00:00+08:00",
                        "expiry_date": "2026-02-19",
                        "remainder": "EXPECTED",
                        "closing_counts": {},
                    }
                ],
            }
        },
    )
    id: str
    received_quantity: Quantity
    cancelled_quantity: Quantity
    outstanding_quantity: Quantity
    receipts: list[Receipt]


class DeliveryEventPayload(BaseModel):
    delivery: Delivery
    effective_at: AwareDatetime
    receipt_id: str | None = None


class DailyEvent(BaseModel):
    id: str
    type: Literal["DAILY_UPDATE_SUBMITTED"]
    timestamp: AwareDatetime
    source: str
    payload: DailyEventPayload


class DeliveryEvent(BaseModel):
    id: str
    type: Literal[
        "EXTERNAL_ORDER_RECORDED",
        "DELIVERY_UPDATED",
        "DELIVERY_DELAYED",
        "DELIVERY_SHORT",
        "DELIVERY_RECEIVED",
        "DELIVERY_CANCELLED",
    ]
    timestamp: AwareDatetime
    source: str
    payload: DeliveryEventPayload


class PlanDecisionEventPayload(BaseModel):
    plan_id: str
    version_id: str
    version: int
    instructions: str | None = None
    reason: str | None = None
    replacement_version_id: str | None = None
    previous_status: str | None = None


class PlanDecisionEvent(BaseModel):
    id: str
    type: Literal["PLAN_APPROVED", "PLAN_REJECTED", "PLAN_SUPERSEDED"]
    timestamp: AwareDatetime
    source: str
    payload: PlanDecisionEventPayload


class CycleEventPayload(BaseModel):
    effective_at: AwareDatetime | None = None
    ingredient_id: str
    scheduled_date: date
    status: Literal["ORDERED", "SKIPPED"]
    note: str | None = None


class CycleEvent(BaseModel):
    id: str
    type: Literal["ORDER_CYCLE_UPDATED"]
    timestamp: AwareDatetime
    source: str
    payload: CycleEventPayload


class PromotionEventPayload(BaseModel):
    promotion_id: str
    revision: int
    name: str
    start_date: date
    end_date: date
    menu_item_ids: list[str]
    demand_multiplier: Decimal
    active: bool
    effective_at: AwareDatetime


class PromotionEvent(BaseModel):
    id: str
    type: Literal["PROMOTION_CREATED", "PROMOTION_CHANGED"]
    timestamp: AwareDatetime
    source: str
    payload: PromotionEventPayload


class SupplierEventPayload(BaseModel):
    offer_id: str
    field: Literal[
        "unit_price", "available_quantity", "current_status", "recent_on_time_rate"
    ]
    previous: str | None
    value: str | None
    effective_at: AwareDatetime


class SupplierEvent(BaseModel):
    id: str
    type: Literal[
        "SUPPLIER_AVAILABILITY_CHANGED",
        "SUPPLIER_PRICE_CHANGED",
        "SUPPLIER_STATUS_CHANGED",
        "SUPPLIER_RELIABILITY_UPDATED",
    ]
    timestamp: AwareDatetime
    source: str
    payload: SupplierEventPayload


Event = Annotated[
    DailyEvent
    | DeliveryEvent
    | SalesBatchEvent
    | ExpiryEvent
    | ManualAssessmentEvent
    | PlanDecisionEvent
    | CycleEvent
    | PromotionEvent
    | SupplierEvent,
    Field(discriminator="type"),
]


class AuditEntry(BaseModel):
    id: str
    event_id: str
    actor: str
    action: str
    timestamp: AwareDatetime

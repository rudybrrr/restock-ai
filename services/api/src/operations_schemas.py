from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Quantity = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]


class DailyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutoff: AwareDatetime
    counts: dict[str, Quantity] = Field(default_factory=dict)
    sales: dict[str, Annotated[int, Field(ge=0, strict=True)]] = Field(
        default_factory=dict
    )


class DailyRevision(DailyDraft):
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
    model_config = ConfigDict(extra="forbid")
    supplier_id: str
    ingredient_id: str
    kind: Literal["NORMAL", "EMERGENCY"]
    expected_quantity: Annotated[Quantity, Field(gt=0)]
    expected_at: AwareDatetime
    ordered_at: AwareDatetime


class DeliveryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_quantity: Annotated[Quantity, Field(gt=0)]
    expected_at: AwareDatetime
    cancel_remainder: bool = False
    effective_at: AwareDatetime


class ReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    quantity: Annotated[Quantity, Field(gt=0)]
    received_at: AwareDatetime
    expiry_date: date
    remainder: Literal["EXPECTED", "CANCELLED"]


class Receipt(ReceiptCreate):
    model_config = ConfigDict(extra="ignore")
    id: str
    delivery_id: str
    lot_id: str


class Delivery(DeliveryCreate):
    model_config = ConfigDict(extra="ignore")
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


Event = Annotated[DailyEvent | DeliveryEvent, Field(discriminator="type")]


class AuditEntry(BaseModel):
    id: str
    event_id: str
    actor: str
    action: str
    timestamp: AwareDatetime

from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NamedRecord(Model):
    id: str
    name: str


class MenuItem(NamedRecord):
    pass


class Ingredient(NamedRecord):
    unit: Literal["kg", "litres", "pieces"]
    interval_days: int = Field(gt=0)
    starting_date: date


class RecipeItem(Model):
    menu_item_id: str
    ingredient_id: str
    quantity: Decimal


class Supplier(NamedRecord):
    pass


class NoCutoff(BaseModel):
    kind: Literal["NONE"]


class UnknownCutoff(BaseModel):
    kind: Literal["UNKNOWN"]


class LocalCutoff(BaseModel):
    kind: Literal["LOCAL_TIME"]
    local_time: time
    timezone: Literal["Asia/Singapore"] = "Asia/Singapore"


class SupplierOffer(Model):
    id: str
    supplier_id: str
    ingredient_id: str
    currency: Literal["SGD"] = "SGD"
    unit_price: Decimal | None
    available_quantity: Decimal | None
    moq: Decimal | None
    pack_size: Decimal | None
    lead_time_minutes: int | None
    order_cutoff: NoCutoff | LocalCutoff | UnknownCutoff
    feasible_delivery_at: list[AwareDatetime] | None
    current_status: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]
    recent_on_time_rate: Decimal | None
    shelf_life_days_on_arrival: int | None
    delivery_fee_sgd: Decimal | None
    emergency_fee_sgd: Decimal | None
    observed_at: AwareDatetime


class Holiday(Model):
    date: date
    name: str
    source_url: str


class InventoryLot(Model):
    id: str
    ingredient_id: str
    unit: Literal["kg", "litres", "pieces"]
    received_at: AwareDatetime
    expiry_date: date
    initial_quantity: Decimal
    quantity: Decimal
    counted_at: AwareDatetime
    provenance: Literal["PHYSICAL"] = "PHYSICAL"


class EstimatedInventoryLot(Model):
    id: str
    ingredient_id: str
    unit: Literal["kg", "litres", "pieces"]
    received_at: AwareDatetime
    expiry_date: date
    initial_quantity: Decimal
    counted_at: AwareDatetime
    quantity: Decimal
    provenance: Literal["ESTIMATED"] = "ESTIMATED"
    as_of: AwareDatetime
    coverage_start: AwareDatetime
    coverage_complete: bool
    unallocated_consumption: Decimal = Field(
        default=Decimal(0),
        ge=0,
        description="Ingredient-level recipe usage not covered by usable stock; repeated across its lots, not additive and not measured waste.",
    )
    status: Literal["ACTIVE", "EXPIRED"]


class LoginRequest(BaseModel):
    username: str
    password: str


class Identity(BaseModel):
    role: Literal["manager", "agent"]
    username: str

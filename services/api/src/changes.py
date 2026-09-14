"""Manager-supplied promotion and supplier facts with atomic reassessment requests."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.fact_history import record_offer_version
from src.operations import lock_inventory, record_event
from src.operations_schemas import EventType
from src.schemas import SupplierOffer


class PromotionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    menu_item_ids: list[str] = Field(min_length=1)
    demand_multiplier: Decimal = Field(gt=0, le=10)
    active: bool = True
    effective_at: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self):
        if self.end_date < self.start_date:
            raise ValueError("Promotion end must not precede start")
        if len(set(self.menu_item_ids)) != len(self.menu_item_ids):
            raise ValueError("Menu items must be unique")
        return self


class Promotion(PromotionInput):
    id: str


class SupplierChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_at: AwareDatetime
    unit_price: Annotated[Decimal, Field(ge=0)] | None = None
    available_quantity: Annotated[Decimal, Field(ge=0)] | None = None
    current_status: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"] | None = None
    recent_on_time_rate: Annotated[Decimal, Field(ge=0, le=1)] | None = None


def save_promotion(
    session: Session, promotion_id: str, body: PromotionInput, actor: str
) -> Promotion:
    lock_inventory(session)
    existing = (
        session.execute(select(db.promotions).where(db.promotions.c.id == promotion_id))
        .mappings()
        .one_or_none()
    )
    payload = body.model_dump(mode="json")
    if existing and existing["payload"] == payload:
        return Promotion(id=promotion_id, **payload)
    if body.revision != (existing["revision"] + 1 if existing else 1):
        raise ApiError(
            409,
            "PROMOTION_REVISION_CONFLICT",
            "Submit the next promotion revision; conflicting retries are rejected",
        )
    if existing and body.effective_at < datetime.fromisoformat(
        existing["payload"]["effective_at"]
    ):
        raise ApiError(
            409,
            "STALE_PROMOTION_UPDATE",
            "Promotion revisions must preserve effective-time order",
        )
    menu = set(session.execute(select(db.menu_items.c.id)).scalars())
    if not set(body.menu_item_ids) <= menu:
        raise ApiError(422, "UNKNOWN_MENU_ITEM", "Promotion references an unknown dish")
    if existing:
        session.execute(
            update(db.promotions)
            .where(db.promotions.c.id == promotion_id)
            .values(revision=body.revision, payload=payload)
        )
    else:
        session.execute(
            insert(db.promotions).values(
                id=promotion_id, revision=body.revision, payload=payload
            )
        )
    record_event(
        session,
        "PROMOTION_CHANGED" if existing else "PROMOTION_CREATED",
        actor,
        {"promotion_id": promotion_id, **payload},
    )
    session.commit()
    return Promotion(id=promotion_id, **payload)


def change_supplier(
    session: Session, offer_id: str, body: SupplierChange, actor: str
) -> SupplierOffer:
    lock_inventory(session)
    existing = (
        session.execute(
            select(db.supplier_offers).where(db.supplier_offers.c.id == offer_id)
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        raise ApiError(404, "OFFER_NOT_FOUND", "Supplier offer does not exist")
    if body.effective_at < existing["observed_at"]:
        raise ApiError(
            409,
            "STALE_SUPPLIER_UPDATE",
            "Supplier observation predates the current facts",
        )
    fields = body.model_dump(exclude={"effective_at"}, exclude_unset=True)
    if not fields or ("current_status" in fields and fields["current_status"] is None):
        raise ApiError(
            422,
            "INVALID_SUPPLIER_UPDATE",
            "Supply changed fields; use UNKNOWN rather than null status",
        )
    changed = {key: value for key, value in fields.items() if existing[key] != value}
    if not changed:
        return SupplierOffer.model_validate(existing)
    session.execute(
        update(db.supplier_offers)
        .where(db.supplier_offers.c.id == offer_id)
        .values(**changed, observed_at=body.effective_at)
    )
    kinds: dict[str, EventType] = {
        "unit_price": "SUPPLIER_PRICE_CHANGED",
        "available_quantity": "SUPPLIER_AVAILABILITY_CHANGED",
        "current_status": "SUPPLIER_STATUS_CHANGED",
        "recent_on_time_rate": "SUPPLIER_RELIABILITY_UPDATED",
    }
    for field, value in changed.items():
        record_event(
            session,
            kinds[field],
            actor,
            {
                "offer_id": offer_id,
                "field": field,
                "previous": str(existing[field])
                if existing[field] is not None
                else None,
                "value": str(value) if value is not None else None,
                "effective_at": body.effective_at.isoformat(),
            },
        )
    result = (
        session.execute(
            select(db.supplier_offers).where(db.supplier_offers.c.id == offer_id)
        )
        .mappings()
        .one()
    )
    record_offer_version(session, dict(result))
    session.commit()
    return SupplierOffer.model_validate(result)

"""Typed, versioned synthetic input for the first contingency integration case."""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from src.procurement_contract_schemas import (
    FrozenOfferRevision,
    FrozenOrderingOpportunity,
    ServicePeriod,
)
from src.schemas import Ingredient, MenuItem, RecipeItem, Supplier


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def catalogue_sha256(
    menu_items: list[MenuItem],
    ingredients: list[Ingredient],
    recipes: list[RecipeItem],
    suppliers: list[Supplier],
) -> str:
    """Bind the exact decision catalogue, independent of row insertion order."""
    document = {
        "menu_items": sorted(
            (row.model_dump(mode="json") for row in menu_items),
            key=lambda row: row["id"],
        ),
        "ingredients": sorted(
            (row.model_dump(mode="json") for row in ingredients),
            key=lambda row: row["id"],
        ),
        "recipes": sorted(
            (
                {
                    **row.model_dump(mode="json"),
                    "quantity": _decimal_text(row.quantity),
                }
                for row in recipes
            ),
            key=lambda row: (row["menu_item_id"], row["ingredient_id"]),
        ),
        "suppliers": sorted(
            (row.model_dump(mode="json") for row in suppliers),
            key=lambda row: row["id"],
        ),
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ResidualDemandBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime
    expected_portions: dict[str, Decimal]

    @model_validator(mode="after")
    def valid_bucket(self) -> "ResidualDemandBucket":
        if self.end <= self.start or any(
            quantity < 0 for quantity in self.expected_portions.values()
        ):
            raise ValueError("Residual bucket needs positive time and demand")
        return self


class ResidualForecastDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_date: date
    profile: list[ServicePeriod] = Field(min_length=1)
    buckets: list[ResidualDemandBucket] = Field(min_length=1)
    promotion_state: Literal["EXCLUDED", "APPLIED"]

    @model_validator(mode="after")
    def complete_profile(self) -> "ResidualForecastDay":
        if len(self.profile) != len(self.buckets) or any(
            period.start != bucket.start
            or period.end != bucket.end
            or period.start.date() != self.target_date
            for period, bucket in zip(self.profile, self.buckets, strict=True)
        ):
            raise ValueError("Every residual bucket needs a matching dated profile")
        if sum((period.weight for period in self.profile), Decimal(0)) != 1:
            raise ValueError("Residual profile weights must total one")
        if any(
            self.profile[index - 1].end > self.profile[index].start
            for index in range(1, len(self.profile))
        ):
            raise ValueError("Residual profile periods overlap or are out of order")
        return self


class FixedSupplyExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    ingredient_id: str
    kind: Literal["NORMAL", "EMERGENCY"]
    ordered_at: AwareDatetime
    expected_at: AwareDatetime
    expected_quantity: Decimal = Field(gt=0)
    received_quantity: Decimal = Field(ge=0)
    cancelled_quantity: Decimal = Field(ge=0)
    outstanding_quantity: Decimal = Field(ge=0)
    received_expiry_date: date

    @model_validator(mode="after")
    def conserves_quantity(self) -> "FixedSupplyExpectation":
        if self.expected_quantity != (
            self.received_quantity + self.cancelled_quantity + self.outstanding_quantity
        ):
            raise ValueError("Fixed commitment quantities must conserve")
        return self


class ContingencyCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE"]
    as_of: AwareDatetime
    domain_id: str
    forecast_method: Literal["EXPLICIT_RESIDUAL_DEMO_V1"]
    ingredient_ids: list[str] = Field(min_length=1)
    menu_item_ids: list[str] = Field(min_length=1)
    catalogue_ingredients: list[Ingredient] | None = None
    catalogue_menu_items: list[MenuItem] | None = None
    catalogue_recipes: list[RecipeItem] | None = None
    catalogue_suppliers: list[Supplier] | None = None
    recipe_manifest: list[tuple[str, str]] | None = None
    catalogue_sha256: str | None = None
    forecasts: list[ResidualForecastDay] = Field(min_length=1)
    opening_expected: dict[str, Decimal]
    fixed_supply_expected: FixedSupplyExpectation
    approved_offer_manifest: list[tuple[str, str, str]] = Field(min_length=1)
    offers: list[FrozenOfferRevision] = Field(min_length=1)
    opportunity_manifest: list[str] = Field(min_length=1)
    opportunities: list[FrozenOrderingOpportunity] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_declared_domain(self) -> "ContingencyCasePayload":
        ingredients, menu = set(self.ingredient_ids), set(self.menu_item_ids)
        if (
            len(ingredients) != len(self.ingredient_ids)
            or len(menu) != len(self.menu_item_ids)
            or set(self.opening_expected) != ingredients
            or any(quantity < 0 for quantity in self.opening_expected.values())
        ):
            raise ValueError("Opening and catalogue manifests are incomplete")
        dates = [day.target_date for day in self.forecasts]
        if dates != sorted(set(dates)) or any(
            set(bucket.expected_portions) != menu
            for day in self.forecasts
            for bucket in day.buckets
        ):
            raise ValueError("Residual forecast dish/date coverage is incomplete")
        if self.forecasts[0].buckets[0].start < self.as_of:
            raise ValueError("Residual forecast includes already elapsed demand")
        offer_keys = [
            (row.offer_id, row.supplier_id, row.ingredient_id) for row in self.offers
        ]
        if (
            len(set(offer_keys)) != len(offer_keys)
            or sorted(offer_keys) != sorted(self.approved_offer_manifest)
            or any(
                row.offer.id != row.offer_id
                or row.offer.supplier_id != row.supplier_id
                or row.offer.ingredient_id != row.ingredient_id
                or row.ingredient_id not in ingredients
                for row in self.offers
            )
        ):
            raise ValueError("Approved offer manifest does not match frozen offers")
        for row in self.offers:
            offer = row.offer
            if (
                offer.unit_price is None
                or offer.unit_price < 0
                or offer.available_quantity is None
                or offer.available_quantity < 0
                or offer.moq is None
                or offer.moq <= 0
                or offer.pack_size is None
                or offer.pack_size <= 0
                or offer.lead_time_minutes is None
                or offer.lead_time_minutes < 0
                or offer.order_cutoff.kind == "UNKNOWN"
                or offer.feasible_delivery_at is None
                or offer.shelf_life_days_on_arrival is None
                or offer.shelf_life_days_on_arrival < 1
                or offer.delivery_fee_sgd is None
                or offer.delivery_fee_sgd < 0
                or offer.emergency_fee_sgd is None
                or offer.emergency_fee_sgd < 0
            ):
                raise ValueError("Approved offer is missing decision-relevant terms")
        opportunity_ids = [row.opportunity_id for row in self.opportunities]
        offer_ids = {row.offer_id for row in self.offers}
        if (
            len(set(opportunity_ids)) != len(opportunity_ids)
            or sorted(opportunity_ids) != sorted(self.opportunity_manifest)
            or any(
                row.offer_id not in offer_ids
                or row.ordered_at != self.as_of
                or not row.shipment_group_id
                for row in self.opportunities
            )
        ):
            raise ValueError("Approved opportunity domain lacks new shipment evidence")
        offers = {row.offer_id: row.offer for row in self.offers}
        for row in self.opportunities:
            offer = offers[row.offer_id]
            if (
                row.arrival_at not in (offer.feasible_delivery_at or ())
                or offer.shelf_life_days_on_arrival is None
                or row.expiry_date
                != row.arrival_at.astimezone(ZoneInfo("Asia/Singapore")).date()
                + timedelta(days=offer.shelf_life_days_on_arrival - 1)
            ):
                raise ValueError("Opportunity arrival or expiry contradicts offer")
        catalogue = (
            self.catalogue_ingredients,
            self.catalogue_menu_items,
            self.catalogue_recipes,
            self.catalogue_suppliers,
            self.recipe_manifest,
            self.catalogue_sha256,
        )
        if any(value is not None for value in catalogue):
            if any(value is None for value in catalogue):
                raise ValueError("Decision catalogue must be complete")
            assert self.catalogue_ingredients is not None
            assert self.catalogue_menu_items is not None
            assert self.catalogue_recipes is not None
            assert self.catalogue_suppliers is not None
            assert self.recipe_manifest is not None
            assert self.catalogue_sha256 is not None
            keys = [
                (row.menu_item_id, row.ingredient_id) for row in self.catalogue_recipes
            ]
            supplier_ids = {row.id for row in self.catalogue_suppliers}
            if (
                {row.id for row in self.catalogue_ingredients} != ingredients
                or len(self.catalogue_ingredients) != len(ingredients)
                or {row.id for row in self.catalogue_menu_items} != menu
                or len(self.catalogue_menu_items) != len(menu)
                or len(supplier_ids) != len(self.catalogue_suppliers)
                or self.fixed_supply_expected.supplier_id not in supplier_ids
                or any(row.supplier_id not in supplier_ids for row in self.offers)
                or {row.menu_item_id for row in self.catalogue_recipes} != menu
                or len(set(keys)) != len(keys)
                or sorted(keys) != sorted(self.recipe_manifest)
                or any(
                    dish not in menu or ingredient not in ingredients
                    for dish, ingredient in keys
                )
                or any(row.quantity <= 0 for row in self.catalogue_recipes)
                or self.catalogue_sha256
                != catalogue_sha256(
                    self.catalogue_menu_items,
                    self.catalogue_ingredients,
                    self.catalogue_recipes,
                    self.catalogue_suppliers,
                )
            ):
                raise ValueError("Decision catalogue disagrees with its manifest")
        return self


class ContingencyCaseInputVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    policy_version_id: str
    artifact_id: str
    version: int = Field(gt=0)
    effective_at: AwareDatetime
    recorded_at: AwareDatetime
    source_revision: str
    payload: ContingencyCasePayload

    @model_validator(mode="after")
    def same_issue_time(self) -> "ContingencyCaseInputVersion":
        if self.effective_at != self.payload.as_of:
            raise ValueError("Case artifact effective time must equal its issue time")
        if any(row.offer.observed_at > self.recorded_at for row in self.payload.offers):
            raise ValueError(
                "Case offer observation must be recorded before the artifact"
            )
        if self.version >= 2 and self.payload.catalogue_sha256 is None:
            raise ValueError("Version 2 requires a complete decision catalogue")
        return self

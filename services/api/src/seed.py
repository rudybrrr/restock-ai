"""Insert the fixed, synthetic 2026-02-15 demo baseline without overwriting data."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert

from src.config import Settings
from src.contingency_case_contracts import (
    first_case_seed_input,
    first_case_seed_input_v2,
    first_case_seed_input_v3,
)
from src.contingency_policy_contracts import (
    first_case_seed_policy,
    first_case_seed_policy_v2,
    first_case_seed_policy_v3,
)
from src.database import (
    contingency_case_inputs,
    contingency_policy_versions,
    holidays,
    ingredients,
    inventory_lots,
    menu_items,
    procurement_domain_offer_revisions,
    procurement_domain_opportunities,
    procurement_forecast_inputs,
    procurement_policy_domains,
    procurement_policy_versions,
    recipes,
    sales_threshold_policy_versions,
    stock_counts,
    supplier_offer_versions,
    supplier_offers,
    suppliers,
)
from src.procurement_contracts import first_slice_seed_rows
from src.sales_materiality_contracts import seed_policy


@dataclass(frozen=True)
class IngredientSeed:
    id: str
    name: str
    unit: Literal["kg", "litres", "pieces"]
    opening_quantity: Decimal
    interval_days: int
    shelf_life_days: int


def seed(database_url: str | None = None) -> None:
    settings = Settings(database_url=database_url) if database_url else Settings()
    engine = create_engine(settings.database_url)
    observed = datetime.fromisoformat("2026-02-15T22:00:00+08:00")
    policy_recorded_at = datetime.now(UTC)
    dishes = [
        ("chicken-rice", "Chicken rice"),
        ("fried-rice", "Egg fried rice"),
        ("chicken-noodles", "Chicken noodles"),
        ("tofu-bowl", "Tofu vegetable bowl"),
        ("vegetable-noodles", "Vegetable noodles"),
    ]
    ingredient_seeds = [
        IngredientSeed("chicken", "Chicken", "kg", Decimal(12), 1, 3),
        IngredientSeed("rice", "Rice", "kg", Decimal(30), 14, 90),
        IngredientSeed("noodles", "Noodles", "kg", Decimal(15), 3, 4),
        IngredientSeed("eggs", "Eggs", "pieces", Decimal(120), 3, 14),
        IngredientSeed("tofu", "Tofu", "kg", Decimal(10), 2, 3),
        IngredientSeed("vegetables", "Vegetables", "kg", Decimal(18), 1, 2),
        IngredientSeed("oil", "Cooking oil", "litres", Decimal(8), 7, 120),
        IngredientSeed("soy-sauce", "Soy sauce", "litres", Decimal(6), 7, 90),
    ]
    recipe_data = {
        "chicken-rice": {"chicken": ".150", "rice": ".100", "soy-sauce": ".010"},
        "fried-rice": {
            "rice": ".100",
            "eggs": "1",
            "vegetables": ".050",
            "oil": ".010",
        },
        "chicken-noodles": {"chicken": ".120", "noodles": ".150", "soy-sauce": ".010"},
        "tofu-bowl": {"tofu": ".150", "rice": ".100", "vegetables": ".100"},
        "vegetable-noodles": {"noodles": ".150", "vegetables": ".120", "oil": ".010"},
    }
    supplier_data = [
        ("fresh", "Fresh Foods"),
        ("pantry", "Pantry Supply"),
        ("market", "Market Supply"),
    ]
    menu_rows = [{"id": key, "name": name} for key, name in dishes]
    ingredient_rows = [
        {
            "id": ingredient.id,
            "name": ingredient.name,
            "unit": ingredient.unit,
            "interval_days": ingredient.interval_days,
            "starting_date": date(2026, 2, 15),
        }
        for ingredient in ingredient_seeds
    ]
    recipe_rows = [
        {
            "menu_item_id": dish,
            "ingredient_id": ingredient,
            "quantity": Decimal(quantity),
        }
        for dish, recipe in recipe_data.items()
        for ingredient, quantity in recipe.items()
    ]
    supplier_rows = [{"id": key, "name": name} for key, name in supplier_data]
    # Synthetic demo tradeoffs, not real supplier quotes or food-storage guidance.
    # Fresh is the standard offer, Pantry is cheaper/bulk/slower, Market is urgent.
    terms = {
        "fresh": (Decimal("1.00"), 200, 1, 1, 480, ".9700", 5, 12),
        "pantry": (Decimal("0.85"), 300, 10, 5, 1440, ".9400", 8, 20),
        "market": (Decimal("1.25"), 80, 1, 1, 120, ".9900", 12, 25),
    }
    delivery_slots = [
        (observed.replace(hour=hour) + timedelta(days=day)).isoformat()
        for day in range(1, 30)
        for hour in (8, 14, 18)
    ]
    source = "https://www.mom.gov.sg/newsroom/press-releases/2025/0616-public-holidays-for-2026"
    try:
        with engine.begin() as conn:

            def insert_if_absent(table, rows):
                conn.execute(insert(table).values(rows).on_conflict_do_nothing())

            insert_if_absent(menu_items, menu_rows)
            insert_if_absent(ingredients, ingredient_rows)
            insert_if_absent(recipes, recipe_rows)
            insert_if_absent(suppliers, supplier_rows)
            first_slice = first_slice_seed_rows(policy_recorded_at)
            insert_if_absent(procurement_policy_versions, first_slice["policies"])
            insert_if_absent(
                contingency_policy_versions,
                [
                    first_case_seed_policy(policy_recorded_at),
                    first_case_seed_policy_v2(policy_recorded_at),
                    first_case_seed_policy_v3(policy_recorded_at),
                ],
            )
            insert_if_absent(
                contingency_case_inputs,
                [
                    first_case_seed_input(policy_recorded_at),
                    first_case_seed_input_v2(
                        policy_recorded_at,
                        menu_items=menu_rows,
                        ingredients=ingredient_rows,
                        recipes=recipe_rows,
                        suppliers=supplier_rows,
                    ),
                    first_case_seed_input_v3(
                        policy_recorded_at,
                        menu_items=menu_rows,
                        ingredients=ingredient_rows,
                        recipes=recipe_rows,
                        suppliers=supplier_rows,
                    ),
                ],
            )
            insert_if_absent(procurement_policy_domains, first_slice["domains"])
            insert_if_absent(
                procurement_forecast_inputs, first_slice["forecast_inputs"]
            )
            insert_if_absent(procurement_domain_offer_revisions, first_slice["offers"])
            insert_if_absent(
                procurement_domain_opportunities, first_slice["opportunities"]
            )
            insert_if_absent(
                sales_threshold_policy_versions, [seed_policy(policy_recorded_at)]
            )
            insert_if_absent(
                supplier_offers,
                [
                    {
                        "id": f"{supplier}-{ingredient.id}",
                        "supplier_id": supplier,
                        "ingredient_id": ingredient.id,
                        "unit_price": ((Decimal("4.50") + index) * multiplier).quantize(
                            Decimal(".01")
                        ),
                        "available_quantity": Decimal(capacity),
                        "moq": Decimal(moq),
                        "pack_size": Decimal(pack),
                        "lead_time_minutes": lead_time,
                        "order_cutoff": {
                            "kind": "LOCAL_TIME",
                            "local_time": "23:00:00",
                            "timezone": "Asia/Singapore",
                        },
                        "feasible_delivery_at": delivery_slots,
                        "current_status": "AVAILABLE",
                        "recent_on_time_rate": Decimal(reliability),
                        "shelf_life_days_on_arrival": ingredient.shelf_life_days,
                        "delivery_fee_sgd": Decimal(delivery_fee),
                        "emergency_fee_sgd": Decimal(emergency_fee),
                        "observed_at": observed,
                    }
                    for index, ingredient in enumerate(ingredient_seeds)
                    for supplier, _ in supplier_data
                    for multiplier, capacity, moq, pack, lead_time, reliability, delivery_fee, emergency_fee in [
                        terms[supplier]
                    ]
                ],
            )
            insert_if_absent(
                holidays,
                [
                    {
                        "date": date(2026, 2, day),
                        "name": "Chinese New Year",
                        "source_url": source,
                    }
                    for day in (17, 18)
                ],
            )
            insert_if_absent(
                supplier_offer_versions,
                [
                    {
                        "id": "baseline:" + row["id"],
                        "offer_id": row["id"],
                        "effective_at": row["observed_at"],
                        "recorded_at": datetime.now(UTC),
                        "payload": json.loads(json.dumps(dict(row), default=str)),
                    }
                    for row in conn.execute(select(supplier_offers)).mappings()
                ],
            )
            lots = [
                {
                    "id": f"{ingredient.id}-01",
                    "ingredient_id": ingredient.id,
                    "received_at": datetime.fromisoformat("2026-02-15T08:00:00+08:00"),
                    "expiry_date": date(2026, 2, 15)
                    + timedelta(days=ingredient.shelf_life_days),
                    "initial_quantity": ingredient.opening_quantity,
                }
                for ingredient in ingredient_seeds
            ]
            lots.append(
                {
                    "id": "chicken-02",
                    "ingredient_id": "chicken",
                    "received_at": datetime.fromisoformat("2026-02-15T12:00:00+08:00"),
                    "expiry_date": date(2026, 2, 20),
                    "initial_quantity": Decimal(5),
                }
            )
            insert_if_absent(inventory_lots, lots)
            insert_if_absent(
                stock_counts,
                [
                    {
                        "id": f"seed-{lot['id']}",
                        "lot_id": lot["id"],
                        "quantity": lot["initial_quantity"],
                        "counted_at": observed,
                    }
                    for lot in lots
                ],
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    seed()

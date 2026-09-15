"""Insert the fixed, synthetic 2026-02-15 demo baseline without overwriting data."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert

from src.config import Settings
from src.database import (
    holidays,
    ingredients,
    inventory_lots,
    menu_items,
    recipes,
    stock_counts,
    supplier_offer_versions,
    supplier_offers,
    suppliers,
)


@dataclass(frozen=True)
class IngredientSeed:
    id: str
    name: str
    unit: Literal["kg", "litres", "pieces"]
    opening_quantity: Decimal
    interval_days: int
    shelf_life_days: int


def seed() -> None:
    engine = create_engine(Settings().database_url)
    observed = datetime.fromisoformat("2026-02-15T22:00:00+08:00")
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

            insert_if_absent(
                menu_items, [{"id": key, "name": name} for key, name in dishes]
            )
            insert_if_absent(
                ingredients,
                [
                    {
                        "id": seed.id,
                        "name": seed.name,
                        "unit": seed.unit,
                        "interval_days": seed.interval_days,
                        "starting_date": date(2026, 2, 15),
                    }
                    for seed in ingredient_seeds
                ],
            )
            insert_if_absent(
                recipes,
                [
                    {
                        "menu_item_id": dish,
                        "ingredient_id": ingredient,
                        "quantity": Decimal(quantity),
                    }
                    for dish, recipe in recipe_data.items()
                    for ingredient, quantity in recipe.items()
                ],
            )
            insert_if_absent(
                suppliers, [{"id": key, "name": name} for key, name in supplier_data]
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

"""Insert the fixed, synthetic 2026-02-15 demo baseline without overwriting data."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert

from src.config import Settings
from src.database import (
    holidays,
    ingredients,
    inventory_lots,
    menu_items,
    recipes,
    stock_counts,
    supplier_offers,
    suppliers,
)


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
    items = [
        ("chicken", "Chicken", "kg"),
        ("rice", "Rice", "kg"),
        ("noodles", "Noodles", "kg"),
        ("eggs", "Eggs", "pieces"),
        ("tofu", "Tofu", "kg"),
        ("vegetables", "Vegetables", "kg"),
        ("oil", "Cooking oil", "litres"),
        ("soy-sauce", "Soy sauce", "litres"),
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
    quantities = ["12", "30", "15", "120", "10", "18", "8", "6"]
    source = "https://www.mom.gov.sg/newsroom/press-releases/2025/0616-public-holidays-for-2026"
    try:
        with engine.begin() as conn:

            def add(table, rows):
                conn.execute(insert(table).values(rows).on_conflict_do_nothing())

            add(menu_items, [{"id": key, "name": name} for key, name in dishes])
            add(
                ingredients,
                [{"id": key, "name": name, "unit": unit} for key, name, unit in items],
            )
            add(
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
            add(suppliers, [{"id": key, "name": name} for key, name in supplier_data])
            add(
                supplier_offers,
                [
                    {
                        "id": f"{supplier}-{ingredient}",
                        "supplier_id": supplier,
                        "ingredient_id": ingredient,
                        "unit_price": Decimal("4.50") + index,
                        "available_quantity": Decimal(200),
                        "moq": Decimal(1),
                        "pack_size": Decimal(1),
                        "lead_time_minutes": 480,
                        "order_cutoff": {
                            "kind": "LOCAL_TIME",
                            "local_time": "23:00:00",
                            "timezone": "Asia/Singapore",
                        },
                        "feasible_delivery_at": ["2026-02-16T08:00:00+08:00"],
                        "current_status": "AVAILABLE",
                        "recent_on_time_rate": Decimal(".9500"),
                        "shelf_life_days_on_arrival": 5,
                        "delivery_fee_sgd": Decimal(5),
                        "emergency_fee_sgd": Decimal(12),
                        "observed_at": observed,
                    }
                    for index, (ingredient, _, _) in enumerate(items)
                    for supplier, _ in supplier_data
                ],
            )
            add(
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
            lots = [
                {
                    "id": f"{ingredient}-01",
                    "ingredient_id": ingredient,
                    "received_at": datetime.fromisoformat("2026-02-15T08:00:00+08:00"),
                    "expiry_date": date(2026, 2, 18),
                    "initial_quantity": Decimal(quantities[index]),
                }
                for index, (ingredient, _, _) in enumerate(items)
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
            add(inventory_lots, lots)
            add(
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

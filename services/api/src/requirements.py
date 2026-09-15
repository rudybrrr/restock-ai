"""Shared pure recipe arithmetic using the existing catalogue models."""

from collections.abc import Mapping, Sequence
from decimal import Context, Decimal, localcontext

from src.schemas import Ingredient, MenuItem, RecipeItem


def _quantity(value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Quantities must be finite Decimal values in base units")
    if value < 0 or (positive and value == 0):
        raise ValueError("Recipe quantities must be positive; portions nonnegative")


def sum_recipe_usage(
    portions: Mapping[str, Decimal], recipes: Sequence[RecipeItem]
) -> dict[str, Decimal]:
    """Shared multiplication for already resolved backend recipe inputs.

    Missing portions mean zero ONLY at this low-level seam: existing complete
    simulator batches/development requests already define that convention.
    Forecast callers must use calculate_requirements to enforce completeness,
    references and units. No database, inventory replay or transport logic here.
    """
    for quantity in portions.values():
        _quantity(quantity)
    for recipe in recipes:
        _quantity(recipe.quantity, positive=True)
    result: dict[str, Decimal] = {}
    # Enough precision for exact nonnegative products and their sums, including
    # fractional expected pieces. Independent of the caller's Decimal context.
    terms = [(portions.get(r.menu_item_id, Decimal(0)), r) for r in recipes]
    nonzero = [(q, r.quantity) for q, r in terms if q]
    precision = 28
    if nonzero:
        lowest = min(
            int(q.as_tuple().exponent) + int(r.as_tuple().exponent) for q, r in nonzero
        )
        highest = max(q.adjusted() + r.adjusted() + 1 for q, r in nonzero)
        precision = max(precision, highest - lowest + len(str(len(nonzero))) + 1)
    with localcontext(Context(prec=precision)):
        for portions_value, recipe in sorted(
            terms, key=lambda item: (item[1].ingredient_id, item[1].menu_item_id)
        ):
            ingredient = recipe.ingredient_id
            result[ingredient] = (
                result.get(ingredient, Decimal(0)) + portions_value * recipe.quantity
            )
    return result


def calculate_requirements(
    forecast: Mapping[str, Decimal],
    menu_items: Sequence[MenuItem],
    ingredients: Sequence[Ingredient],
    recipes: Sequence[RecipeItem],
    *,
    sparse: bool = False,
) -> dict[str, Decimal]:
    """Sum expected served portions times recipe base-unit quantities.

    Default requires every catalogue dish, including explicit zeros. sparse=True
    explicitly declares omitted dishes out of scope (zero contribution), never
    unknown demand. Always returns every supplied ingredient, including zeros.
    Recipes must be the caller's complete resolved version, even for zero dishes.
    A RecipeItem has no separate unit: quantity uses its Ingredient.unit exactly.
    """
    dish_ids = {dish.id for dish in menu_items}
    ingredient_ids = {ingredient.id for ingredient in ingredients}
    if not dish_ids or len(dish_ids) != len(menu_items):
        raise ValueError("Menu must contain unique dish IDs")
    if not ingredient_ids or len(ingredient_ids) != len(ingredients):
        raise ValueError("Ingredients must contain unique IDs")
    if type(sparse) is not bool:
        raise ValueError("sparse must be an explicit boolean")
    if set(forecast) - dish_ids:
        raise ValueError("Unknown dish in forecast")
    if not sparse and set(forecast) != dish_ids:
        raise ValueError(
            "Incomplete forecast: supply all dishes or explicitly set sparse=True"
        )
    if any(i.unit not in ("kg", "litres", "pieces") for i in ingredients):
        raise ValueError("Unsupported ingredient base unit")
    pairs: set[tuple[str, str]] = set()
    for recipe in recipes:
        if (
            recipe.menu_item_id not in dish_ids
            or recipe.ingredient_id not in ingredient_ids
        ):
            raise ValueError("Unknown dish or ingredient in recipe")
        pair = (recipe.menu_item_id, recipe.ingredient_id)
        if pair in pairs:
            raise ValueError("Duplicate recipe line")
        pairs.add(pair)
    if {dish for dish, _ in pairs} != dish_ids:
        raise ValueError("Missing recipe for a catalogue dish")
    usage = sum_recipe_usage(forecast, recipes)
    return {
        ingredient: usage.get(ingredient, Decimal(0))
        for ingredient in sorted(ingredient_ids)
    }

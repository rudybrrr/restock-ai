"""Recipe oracles do not use production arithmetic to build expected values."""

import json
from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.requirements import calculate_requirements
from src.schemas import Ingredient, MenuItem, RecipeItem


@pytest.fixture
def catalogue():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "seasonal_baseline_v3.json").read_text()
    )
    return (
        [MenuItem.model_validate(row) for row in fixture["menu_items"]],
        [Ingredient.model_validate(row) for row in fixture["ingredients"]],
        [RecipeItem.model_validate(row) for row in fixture["recipes"]],
    )


def test_shared_ingredients_and_fractional_expected_pieces(catalogue):
    # 2.5 chicken rice + 1.5 fried rice + .5 chicken noodles.
    result = calculate_requirements(
        {
            "chicken-rice": Decimal("2.5"),
            "fried-rice": Decimal("1.5"),
            "chicken-noodles": Decimal(".5"),
        },
        *catalogue,
        sparse=True,
    )
    assert result == {
        "chicken": Decimal(".435"),
        "rice": Decimal(".400"),
        "noodles": Decimal(".075"),
        "eggs": Decimal("1.5"),
        "tofu": Decimal(0),
        "vegetables": Decimal(".075"),
        "oil": Decimal(".015"),
        "soy-sauce": Decimal(".030"),
    }


def test_complete_zero_vector_and_explicit_empty_sparse_vector(catalogue):
    menu, ingredients, _ = catalogue
    expected = {ingredient.id: Decimal(0) for ingredient in ingredients}
    assert (
        calculate_requirements({dish.id: Decimal(0) for dish in menu}, *catalogue)
        == expected
    )
    assert calculate_requirements({}, *catalogue, sparse=True) == expected
    with pytest.raises(ValueError, match="Incomplete forecast"):
        calculate_requirements({}, *catalogue)


def test_accidentally_incomplete_forecast_is_not_sparse(catalogue):
    with pytest.raises(ValueError, match="Incomplete forecast"):
        calculate_requirements({"chicken-rice": Decimal(100)}, *catalogue)
    result = calculate_requirements(
        {"chicken-rice": Decimal(100)}, *catalogue, sparse=True
    )
    assert result == {
        "chicken": Decimal(15),
        "rice": Decimal(10),
        "soy-sauce": Decimal(1),
        "noodles": Decimal(0),
        "eggs": Decimal(0),
        "tofu": Decimal(0),
        "vegetables": Decimal(0),
        "oil": Decimal(0),
    }


@pytest.mark.parametrize(
    "value",
    [
        Decimal(-1),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        None,
        1.2,
        True,
        "1",
        1,
    ],
)
def test_invalid_forecast_quantities(catalogue, value):
    with pytest.raises(ValueError, match="Quantities|nonnegative"):
        calculate_requirements({"chicken-rice": value}, *catalogue, sparse=True)


@pytest.mark.parametrize(
    "value", [Decimal(-1), Decimal(0), Decimal("NaN"), Decimal("Infinity"), 0.15]
)
def test_invalid_recipe_quantities_even_when_forecast_is_zero(catalogue, value):
    menu, ingredients, recipes = catalogue
    recipes[0] = recipes[0].model_copy(update={"quantity": value})
    with pytest.raises(ValueError, match="Quantities|positive"):
        calculate_requirements({}, menu, ingredients, recipes, sparse=True)


def test_unknown_forecast_and_recipe_references(catalogue):
    menu, ingredients, recipes = catalogue
    with pytest.raises(ValueError, match="Unknown dish"):
        calculate_requirements({"D1": Decimal(1)}, *catalogue, sparse=True)
    for field, value in (("menu_item_id", "D1"), ("ingredient_id", "CHICKEN")):
        invalid = [recipes[0].model_copy(update={field: value}), *recipes[1:]]
        with pytest.raises(ValueError, match="Unknown dish or ingredient"):
            calculate_requirements({}, menu, ingredients, invalid, sparse=True)


def test_missing_recipe_and_duplicate_lines_are_not_silently_accepted(catalogue):
    menu, ingredients, recipes = catalogue
    missing = [row for row in recipes if row.menu_item_id != "tofu-bowl"]
    with pytest.raises(ValueError, match="Missing recipe"):
        calculate_requirements({}, menu, ingredients, missing, sparse=True)
    with pytest.raises(ValueError, match="Duplicate recipe"):
        calculate_requirements(
            {}, menu, ingredients, recipes + recipes[:1], sparse=True
        )


def test_units_use_existing_schema_without_implicit_conversion(catalogue):
    menu, ingredients, recipes = catalogue
    for unit in ("g", "ml", "piece", "unknown"):
        with pytest.raises(ValidationError):
            Ingredient.model_validate({**ingredients[0].model_dump(), "unit": unit})
        invalid = [ingredients[0].model_copy(update={"unit": unit}), *ingredients[1:]]
        with pytest.raises(ValueError, match="Unsupported ingredient base unit"):
            calculate_requirements({}, menu, invalid, recipes, sparse=True)


def test_unused_catalogue_ingredient_is_explicit_zero(catalogue):
    menu, ingredients, recipes = catalogue
    ingredients.append(
        Ingredient(
            id="salt",
            name="Salt",
            unit="kg",
            interval_days=1,
            starting_date=date(2026, 2, 15),
        )
    )
    result = calculate_requirements(
        {"chicken-rice": Decimal(1)}, menu, ingredients, recipes, sparse=True
    )
    assert result["salt"] == 0
    assert len(result) == 9


def test_recipe_inputs_are_used_not_fixture_constants(catalogue):
    menu, ingredients, recipes = catalogue
    recipes[0] = recipes[0].model_copy(update={"quantity": Decimal(".200")})
    result = calculate_requirements(
        {"chicken-rice": Decimal(3)}, menu, ingredients, recipes, sparse=True
    )
    assert result["chicken"] == Decimal(".600")


def test_repeated_results_input_permutations_and_decimal_context(catalogue):
    portions = {"chicken-rice": Decimal("2.5"), "fried-rice": Decimal("1.5")}
    original = [list(rows) for rows in catalogue]
    expected = calculate_requirements(portions, *catalogue, sparse=True)
    menu, ingredients, recipes = catalogue
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.rounding = ROUND_DOWN
        actual = calculate_requirements(
            dict(reversed(list(portions.items()))),
            list(reversed(menu)),
            list(reversed(ingredients)),
            list(reversed(recipes)),
            sparse=True,
        )
    assert (
        actual == expected == calculate_requirements(portions, *catalogue, sparse=True)
    )
    assert list(actual) == sorted(actual)
    assert list(catalogue) == original


def test_precise_decimal_products_are_not_quantized_to_database_scale(catalogue):
    menu, ingredients, recipes = catalogue
    recipes[0] = recipes[0].model_copy(
        update={"quantity": Decimal(".12345678901234567890123456789")}
    )
    result = calculate_requirements(
        {"chicken-rice": Decimal(3)}, menu, ingredients, recipes, sparse=True
    )
    assert result["chicken"] == Decimal(".37037036703703703670370370367")


def test_empty_duplicate_catalogues_and_nonboolean_sparse_are_rejected(catalogue):
    menu, ingredients, recipes = catalogue
    for bad_menu in ([], menu + menu[:1]):
        with pytest.raises(ValueError, match="unique dish"):
            calculate_requirements({}, bad_menu, ingredients, recipes, sparse=True)
    for bad_ingredients in ([], ingredients + ingredients[:1]):
        with pytest.raises(ValueError, match="unique IDs"):
            calculate_requirements({}, menu, bad_ingredients, recipes, sparse=True)
    with pytest.raises(ValueError, match="explicit boolean"):
        calculate_requirements({}, *catalogue, sparse="yes")  # pyright: ignore[reportArgumentType]

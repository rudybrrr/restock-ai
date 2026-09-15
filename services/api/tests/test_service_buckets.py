"""Independent service allocation oracles and conservation/validation boundaries."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.requirements import calculate_requirements
from src.schemas import Ingredient, MenuItem, RecipeItem
from src.service_buckets import ServicePeriod, allocate_service_buckets

FIXTURES = Path(__file__).parent / "fixtures"
TARGET = date(2026, 2, 16)
MENU = [MenuItem(id="chicken-rice", name="Chicken rice")]


@pytest.fixture
def profile() -> list[ServicePeriod]:
    fixture = json.loads((FIXTURES / "service_profile_v2.json").read_text())
    assert date.fromisoformat(fixture["target_date"]) == TARGET
    return [
        ServicePeriod(
            datetime.fromisoformat(p["start"]),
            datetime.fromisoformat(p["end"]),
            Decimal(p["weight"]),
        )
        for p in fixture["periods"]
    ]


def allocate(quantity: Decimal, profile: list[ServicePeriod]):
    return allocate_service_buckets(
        {"chicken-rice": quantity}, MENU, target_date=TARGET, profile=profile
    )


def values(result) -> list[Decimal]:
    return [bucket.expected_portions["chicken-rice"] for bucket in result]


def test_reference_profile_matches_independent_bucket_oracles(profile):
    result = allocate(Decimal(100), profile)
    # 40/6 = 6.666666...; four residual millionths go to earliest lunch buckets.
    assert (
        values(result)
        == [Decimal("6.666667")] * 4
        + [Decimal("6.666666")] * 2
        + [Decimal("7.500000")] * 8
    )
    assert sum(values(result)[:6]) == Decimal(40)
    assert sum(values(result)[6:]) == Decimal(60)
    assert sum(values(result)) == Decimal(100)
    expected_starts = [
        "11:00",
        "11:30",
        "12:00",
        "12:30",
        "13:00",
        "13:30",
        "17:00",
        "17:30",
        "18:00",
        "18:30",
        "19:00",
        "19:30",
        "20:00",
        "20:30",
    ]
    assert [bucket.start.strftime("%H:%M") for bucket in result] == expected_starts
    assert result[5].end.hour == 14 and result[-1].end.hour == 21
    assert all(bucket.end - bucket.start == timedelta(minutes=30) for bucket in result)
    assert all(
        bucket.start.date() == TARGET and bucket.start.utcoffset() == timedelta(hours=8)
        for bucket in result
    )
    assert all(bucket.provenance == "PROJECTED" for bucket in result)


def test_existing_baseline_to_buckets_to_recipes_uses_current_five_dishes(profile):
    fixture = json.loads((FIXTURES / "seasonal_baseline_v3.json").read_text())
    menu = [MenuItem.model_validate(row) for row in fixture["menu_items"]]
    ingredients = [Ingredient.model_validate(row) for row in fixture["ingredients"]]
    recipes = [RecipeItem.model_validate(row) for row in fixture["recipes"]]
    history = [
        DailySalesObservation(
            date.fromisoformat(row["service_date"]),
            datetime.fromisoformat(row["available_at"]),
            row["revision"],
            row["portions"],
            row["promotion"],
            row["censored"],
        )
        for row in fixture["history"]
    ]
    baseline = seasonal_baseline(
        history,
        menu,
        issue_time=datetime.fromisoformat(fixture["issue_time"]),
        target_date=TARGET,
    )
    daily = {}
    for dish, forecast in baseline.items():
        assert forecast.expected_portions is not None
        daily[dish] = forecast.expected_portions
    buckets = allocate_service_buckets(daily, menu, target_date=TARGET, profile=profile)
    lunch_oracles = {
        "chicken-rice": ["6.666667"] * 4 + ["6.666666"] * 2,
        "fried-rice": ["4"] * 6,
        "chicken-noodles": ["5.333334"] * 2 + ["5.333333"] * 4,
        "tofu-bowl": ["2.666667"] * 4 + ["2.666666"] * 2,
        "vegetable-noodles": ["2.666667"] * 4 + ["2.666666"] * 2,
    }
    dinner_oracles = {
        "chicken-rice": "7.5",
        "fried-rice": "4.5",
        "chicken-noodles": "6",
        "tofu-bowl": "3",
        "vegetable-noodles": "3",
    }
    for dish in daily:
        assert [b.expected_portions[dish] for b in buckets] == [
            Decimal(q) for q in lunch_oracles[dish]
        ] + [Decimal(dinner_oracles[dish])] * 8
        assert sum(b.expected_portions[dish] for b in buckets) == Decimal(
            fixture["expected_forecast"][dish]
        )
    needs = [
        calculate_requirements(b.expected_portions, menu, ingredients, recipes)
        for b in buckets
    ]
    assert {i.id: sum(n[i.id] for n in needs) for i in ingredients} == {
        i: Decimal(q) for i, q in fixture["expected_requirements"].items()
    }


def test_fractional_demand_independent_oracle(profile):
    result = values(allocate(Decimal("25.25"), profile))
    # Lunch total 10.10, dinner total 15.15; dinner half-hours are exact.
    assert (
        result
        == [Decimal("1.683334")] * 2
        + [Decimal("1.683333")] * 4
        + [Decimal("1.893750")] * 8
    )
    assert sum(result) == Decimal("25.25")


def test_zero_demand_keeps_every_dated_bucket(profile):
    result = allocate(Decimal(0), profile)
    assert len(result) == 14
    assert values(result) == [Decimal(0)] * 14


def test_tiny_fraction_is_preserved_not_rounded_away(profile):
    result = values(allocate(Decimal("0.0000001"), profile))
    # One unit at 1e-7: dinner has the largest remainder; earliest dinner wins.
    assert result == [Decimal(0)] * 6 + [Decimal("0.0000001")] + [Decimal(0)] * 7


@pytest.mark.parametrize(
    "quantity",
    [
        "0",
        "1",
        "0.00123",
        "0.0000000000001",
        "0.1428571428571428571428571429",
        "123456789012345678901234567890.123456789",
    ],
)
def test_exact_conservation_and_error_less_than_one_quantum(profile, quantity):
    daily = Decimal(quantity)
    result = values(allocate(daily, profile))
    # Fraction is an independent exact summation oracle, unaffected by ambient
    # Decimal precision when testing values larger than 28 significant digits.
    assert sum(map(Fraction, result)) == Fraction(daily)
    quantum = min(Fraction(1, 10**6), Fraction(10) ** int(daily.as_tuple().exponent))
    shares = [Fraction(1, 15)] * 6 + [Fraction(3, 40)] * 8
    assert all(
        q >= 0 and abs(Fraction(q) - Fraction(daily) * share) < quantum
        for q, share in zip(result, shares, strict=True)
    )


def test_order_timezone_decimal_context_and_representation_invariance(profile):
    expected = allocate(Decimal("25.25"), profile)
    utc = [
        replace(p, start=p.start.astimezone(UTC), end=p.end.astimezone(UTC))
        for p in reversed(profile)
    ]
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.rounding = ROUND_UP
        assert allocate(Decimal("25.250000000"), utc) == expected
    assert allocate(Decimal("25.25"), profile) == expected
    with pytest.raises(TypeError):
        expected[0].expected_portions["chicken-rice"] = Decimal(999)  # pyright: ignore[reportIndexIssue]


def test_explicit_different_profile_is_used_and_zero_weight_is_supported(profile):
    different = [
        replace(
            profile[0],
            end=profile[0].start + timedelta(minutes=30),
            weight=Decimal(".2"),
        ),
        replace(
            profile[1], end=profile[1].start + timedelta(hours=1), weight=Decimal(".8")
        ),
    ]
    assert values(allocate(Decimal(10), different)) == [
        Decimal(2),
        Decimal(4),
        Decimal(4),
    ]
    zero_weight = [
        replace(different[0], weight=Decimal(0)),
        replace(different[1], weight=Decimal(1)),
    ]
    assert values(allocate(Decimal(10), zero_weight)) == [
        Decimal(0),
        Decimal(5),
        Decimal(5),
    ]


def test_adjacent_periods_and_end_at_next_midnight_are_valid(profile):
    first = replace(
        profile[0],
        start=profile[0].start.replace(hour=23),
        end=profile[0].start.replace(hour=23, minute=30),
        weight=Decimal(".5"),
    )
    second = replace(first, start=first.end, end=first.end + timedelta(minutes=30))
    result = allocate(Decimal(2), [first, second])
    assert values(result) == [Decimal(1), Decimal(1)]
    assert result[-1].end.date() == TARGET + timedelta(days=1)


@pytest.mark.parametrize(
    "weight",
    [
        Decimal(-1),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        0.4,
        "0.4",
        None,
        True,
    ],
)
def test_invalid_profile_weights(profile, weight):
    with pytest.raises(ValueError, match="finite nonnegative Decimals"):
        allocate(Decimal(1), [replace(profile[0], weight=weight), profile[1]])


@pytest.mark.parametrize(
    "weights",
    [("0", "0"), (".3", ".6"), (".5", ".6"), (".4", ".6000000000000000000000000001")],
)
def test_profile_weight_sum_is_exact_not_tolerant_or_normalised(profile, weights):
    with pytest.raises(ValueError, match="sum exactly"):
        allocate(
            Decimal(1),
            [
                replace(p, weight=Decimal(w))
                for p, w in zip(profile, weights, strict=True)
            ],
        )


@pytest.mark.parametrize(
    "change",
    [
        {"start": datetime.fromisoformat("2026-02-16T11:00:00")},
        {"end": "2026-02-16T14:00:00+08:00"},
        {"start": None},
        {"start": datetime.fromisoformat("2026-02-16T14:00:00+08:00")},
        {"start": datetime.fromisoformat("2026-02-16T15:00:00+08:00")},
        {"start": datetime.fromisoformat("2026-02-15T11:00:00+08:00")},
        {"end": datetime.fromisoformat("2026-02-17T00:30:00+08:00")},
        {"start": datetime.fromisoformat("2026-02-16T11:15:00+08:00")},
        {"end": datetime.fromisoformat("2026-02-16T13:45:00+08:00")},
        {"start": datetime.fromisoformat("2026-02-16T11:00:01+08:00")},
        {"end": datetime.fromisoformat("2026-02-16T14:00:00.000001+08:00")},
    ],
)
def test_invalid_timestamps_and_intervals(profile, change):
    with pytest.raises(ValueError):
        allocate(Decimal(1), [replace(profile[0], **change), profile[1]])


def test_overlaps_duplicates_and_timezone_disguised_overlaps(profile):
    for second in (
        replace(profile[1], start=profile[0].start, end=profile[0].end),
        replace(profile[1], start=profile[0].end - timedelta(minutes=30)),
        replace(
            profile[1],
            start=profile[0].start.astimezone(UTC),
            end=profile[0].end.astimezone(UTC),
        ),
    ):
        with pytest.raises(ValueError, match="overlap"):
            allocate(Decimal(1), [profile[0], second])


@pytest.mark.parametrize(
    "quantity",
    [
        Decimal(-1),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        None,
        1,
        1.2,
        "1",
        True,
    ],
)
def test_invalid_daily_quantities(profile, quantity):
    with pytest.raises(ValueError, match="finite nonnegative Decimals"):
        allocate(quantity, profile)


def test_invalid_catalogue_completeness_profile_and_target(profile):
    for daily, menu in (
        ({}, MENU),
        ({"unknown": Decimal(1)}, MENU),
        ({"chicken-rice": Decimal(1)}, []),
        ({"chicken-rice": Decimal(1)}, MENU * 2),
    ):
        with pytest.raises(ValueError):
            allocate_service_buckets(daily, menu, target_date=TARGET, profile=profile)
    with pytest.raises(ValueError, match="nonempty"):
        allocate(Decimal(1), [])
    with pytest.raises(ValueError, match="must be a date"):
        allocate_service_buckets(
            {"chicken-rice": Decimal(1)},
            MENU,
            target_date=profile[0].start,
            profile=profile,
        )
    with pytest.raises(TypeError, match="ServicePeriod"):
        allocate(Decimal(1), [None])  # pyright: ignore[reportArgumentType]

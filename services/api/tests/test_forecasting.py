"""Independent normal-day arithmetic and issue-time eligibility oracles."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.requirements import calculate_requirements
from src.schemas import Ingredient, MenuItem, RecipeItem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "seasonal_baseline_v3.json"
ISSUE = datetime.fromisoformat("2026-02-15T22:00:00+08:00")
TARGET = date(2026, 2, 16)
MENU = [MenuItem(id="chicken-rice", name="Chicken rice")]


def observation(day: date, portions: int = 10) -> DailySalesObservation:
    return DailySalesObservation(
        day,
        datetime.fromisoformat(f"{day}T22:00:00+08:00"),
        1,
        {"chicken-rice": portions},
        promotion=False,
        censored=False,
    )


def mondays(values=(100, 100, 100, 100)) -> list[DailySalesObservation]:
    return [
        observation(date(2026, 1, 19) + timedelta(weeks=i), q)
        for i, q in enumerate(values)
    ]


def forecast(history):
    return seasonal_baseline(history, MENU, issue_time=ISSUE, target_date=TARGET)[
        "chicken-rice"
    ]


def test_v3_four_monday_forecast_and_all_eight_requirements():
    fixture = json.loads(FIXTURE_PATH.read_text())
    menu = [MenuItem.model_validate(row) for row in fixture["menu_items"]]
    ingredients = [Ingredient.model_validate(row) for row in fixture["ingredients"]]
    recipes = [RecipeItem.model_validate(row) for row in fixture["recipes"]]
    history = [
        DailySalesObservation(
            service_date=date.fromisoformat(row["service_date"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            revision=row["revision"],
            portions=row["portions"],
            promotion=row["promotion"],
            censored=row["censored"],
        )
        for row in fixture["history"]
    ]
    result = seasonal_baseline(history, menu, issue_time=ISSUE, target_date=TARGET)
    expected = {
        key: Decimal(value) for key, value in fixture["expected_forecast"].items()
    }
    actual = {}
    for dish, value in result.items():
        assert value.expected_portions == expected[dish]
        assert value.method == "weekday_mean"
        assert value.eligible_days == value.matching_weekdays == 4
        assert value.coverage_flags == ()
        assert value.expected_portions is not None
        actual[dish] = value.expected_portions
    requirements = calculate_requirements(actual, menu, ingredients, recipes)
    assert requirements == {
        key: Decimal(value) for key, value in fixture["expected_requirements"].items()
    }
    # Separate hand arithmetic: chicken 15+9.6; rice 10+6+4;
    # noodles 12+6; vegetables 3+4+4.8; oil .6+.4; soy 1+.8.
    assert len(requirements) == 8


def test_varied_series_averages_latest_four_matching_days_not_last_value():
    history = [observation(date(2026, 1, 12), 900)] + mondays((10, 20, 30, 41))
    history.append(observation(date(2026, 2, 10), 700))
    result = forecast(history)
    assert result.expected_portions == Decimal("25.25")  # 101 / 4
    assert result.eligible_days == 6
    assert result.matching_weekdays == 5
    assert [ref[0] for ref in result.used_history] == [
        r.service_date for r in mondays()
    ]


def test_future_rows_and_late_corrections_do_not_change_an_earlier_forecast():
    history = mondays()
    late = replace(
        history[-1],
        revision=2,
        available_at=ISSUE + timedelta(seconds=1),
        portions={"chicken-rice": 900},
    )
    future = observation(TARGET, 900)
    assert forecast(history + [late, future]) == forecast(history)
    assert forecast(
        history + [replace(late, available_at=ISSUE)]
    ).expected_portions == Decimal(300)


def test_corrected_total_replaces_day_once_and_retries_are_idempotent():
    history = mondays()
    correction = replace(
        history[-1], revision=2, available_at=ISSUE, portions={"chicken-rice": 140}
    )
    result = forecast(history + [correction, correction])
    assert result.expected_portions == Decimal(110)  # (100+100+100+140)/4
    assert result.eligible_days == 4
    assert result.used_history[-1] == (date(2026, 2, 9), 2, ISSUE)
    with pytest.raises(ValueError, match="Conflicting"):
        forecast(history + [replace(history[-1], portions={"chicken-rice": 999})])


@pytest.mark.parametrize(
    "change,flag",
    [
        ({"promotion": True}, "PROMOTIONAL_DAYS_EXCLUDED"),
        ({"censored": True}, "CENSORED_DAYS_EXCLUDED"),
        ({"portions": {}}, "MISSING_DISH_OBSERVATIONS"),
    ],
)
def test_latest_ineligible_correction_does_not_resurrect_old_total(change, flag):
    history = mondays()
    corrected = replace(history[-1], revision=2, available_at=ISSUE, **change)
    result = forecast(history + [corrected])
    assert result.expected_portions is None
    assert result.eligible_days == 3
    assert result.method == "manual_required"
    assert flag in result.coverage_flags


def test_exclusions_are_applied_before_selecting_last_four_weekdays():
    older = observation(date(2026, 1, 12), 20)
    history = mondays((40, 60, 80, 999))
    result = forecast([older, *history[:-1], replace(history[-1], promotion=True)])
    assert result.expected_portions == Decimal(50)


@pytest.mark.parametrize("count,expected", [(6, None), (7, "4"), (8, "4.5")])
def test_sparse_weekdays_use_all_eligible_days_only_at_seven_or_more(count, expected):
    history = [
        observation(date(2026, 2, 1) + timedelta(days=i), i + 1) for i in range(count)
    ]
    result = forecast(history)
    assert result.expected_portions == (Decimal(expected) if expected else None)
    assert result.method == ("eligible_day_mean" if count >= 7 else "manual_required")
    assert result.eligible_days == count


@pytest.mark.parametrize("flag", ["promotion", "censored"])
def test_ineligible_days_do_not_satisfy_fallback_minimum(flag):
    history = [observation(date(2026, 2, 1) + timedelta(days=i)) for i in range(7)]
    history[-1] = replace(history[-1], **{flag: True})
    assert forecast(history).expected_portions is None
    assert forecast(history).eligible_days == 6


def test_missing_history_is_distinct_from_four_explicit_zero_days():
    assert forecast([]).expected_portions is None
    assert forecast(mondays((0, 0, 0, 0))).expected_portions == Decimal(0)
    result = forecast([replace(row, portions={}) for row in mondays()])
    assert result.expected_portions is None
    assert result.eligible_days == 0


def test_missing_dish_does_not_impair_another_dish_with_complete_history():
    menu = MENU + [MenuItem(id="tofu-bowl", name="Tofu vegetable bowl")]
    result = seasonal_baseline(mondays(), menu, issue_time=ISSUE, target_date=TARGET)
    assert result["chicken-rice"].expected_portions == 100
    assert result["tofu-bowl"].expected_portions is None


def test_origin_cutoff_holds_even_when_target_is_farther_in_future():
    history = mondays() + [observation(date(2026, 2, 16), 900)]
    result = seasonal_baseline(
        history, MENU, issue_time=ISSUE, target_date=date(2026, 2, 23)
    )
    assert result["chicken-rice"].expected_portions == 100


def test_target_day_observation_is_excluded_even_if_available_at_issue():
    result = seasonal_baseline(
        mondays() + [observation(TARGET, 900)],
        MENU,
        issue_time=datetime.fromisoformat("2026-02-16T22:00:00+08:00"),
        target_date=TARGET,
    )
    assert result["chicken-rice"].expected_portions == 100


def test_input_order_timezone_and_decimal_context_do_not_change_results():
    history = mondays((10, 20, 30, 41))
    expected = forecast(history)
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.rounding = ROUND_DOWN
        result = seasonal_baseline(
            list(reversed(history)),
            MENU,
            issue_time=ISSUE.astimezone(UTC),
            target_date=TARGET,
        )["chicken-rice"]
    assert result == expected == forecast(history)


def test_repeating_mean_declares_decimal_precision():
    history = [
        observation(date(2026, 2, 1) + timedelta(days=i), int(i == 0)) for i in range(7)
    ]
    assert forecast(history).expected_portions == Decimal(
        "0.1428571428571428571428571429"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"promotion": None},
        {"censored": None},
        {"promotion": 0},
        {"revision": 0},
        {"revision": True},
        {"available_at": ISSUE.replace(tzinfo=None)},
        {"available_at": datetime.fromisoformat("2026-01-01T22:00:00+08:00")},
        {"portions": {"chicken-rice": -1}},
        {"portions": {"chicken-rice": 1.5}},
        {"portions": {"chicken-rice": float("nan")}},
        {"portions": {"chicken-rice": float("inf")}},
        {"portions": {"chicken-rice": True}},
    ],
)
def test_invalid_observations_are_rejected(change):
    with pytest.raises(ValueError):
        replace(mondays()[0], **change)


def test_required_eligibility_is_not_defaulted_and_portions_are_copied():
    source = {"chicken-rice": 7}
    row = replace(mondays()[0], portions=source)
    source["chicken-rice"] = 99
    assert row.portions["chicken-rice"] == 7
    with pytest.raises(TypeError):
        DailySalesObservation(  # pyright: ignore[reportCallIssue]
            service_date=row.service_date,
            available_at=row.available_at,
            revision=1,
            portions=source,
        )


def test_unknown_dish_invalid_menu_and_invalid_issue_target_are_rejected():
    with pytest.raises(ValueError, match="Unknown dish"):
        forecast([replace(mondays()[0], portions={"D1": 100})])
    for menu in ([], MENU + MENU):
        with pytest.raises(ValueError, match="unique dish"):
            seasonal_baseline([], menu, issue_time=ISSUE, target_date=TARGET)
    with pytest.raises(ValueError, match="timezone-aware"):
        seasonal_baseline(
            [], MENU, issue_time=ISSUE.replace(tzinfo=None), target_date=TARGET
        )
    with pytest.raises(ValueError, match="precede"):
        seasonal_baseline([], MENU, issue_time=ISSUE, target_date=date(2026, 2, 14))

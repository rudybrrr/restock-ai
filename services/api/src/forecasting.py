"""Pure normal-day seasonal baseline; internal values, not an HTTP contract."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext
from types import MappingProxyType
from typing import Literal

from src.schemas import MenuItem

SINGAPORE = timezone(timedelta(hours=8))


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")


@dataclass(frozen=True)
class DailySalesObservation:
    """One final daily submission revision, with explicitly known eligibility.

    Portions are served integer portions, not transactions or intraday batches.
    An omitted dish is unobserved. A revision replaces the entire daily vector.
    Day-wide promotion/censoring flags conservatively apply to every listed dish.
    """

    service_date: date
    available_at: datetime
    revision: int
    portions: Mapping[str, int]
    promotion: bool
    censored: bool

    def __post_init__(self) -> None:
        _aware(self.available_at)
        if type(self.service_date) is not date:
            raise ValueError("service_date must be a date")
        if self.available_at.astimezone(SINGAPORE).date() < self.service_date:
            raise ValueError(
                "Daily sales cannot be available before their service date"
            )
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if type(self.promotion) is not bool or type(self.censored) is not bool:
            raise ValueError(
                "Explicit boolean promotion and censoring metadata required"
            )
        if any(type(q) is not int or q < 0 for q in self.portions.values()):
            raise ValueError("Observed portions must be nonnegative integers")
        object.__setattr__(self, "portions", MappingProxyType(dict(self.portions)))


@dataclass(frozen=True)
class DishForecast:
    expected_portions: Decimal | None
    method: Literal["weekday_mean", "eligible_day_mean", "manual_required"]
    eligible_days: int
    matching_weekdays: int
    used_history: tuple[tuple[date, int, datetime], ...]
    coverage_flags: tuple[str, ...]


def seasonal_baseline(
    history: Sequence[DailySalesObservation],
    menu_items: Sequence[MenuItem],
    *,
    issue_time: datetime,
    target_date: date,
) -> dict[str, DishForecast]:
    """Average four latest eligible matching weekdays, else all eligible days
    when at least seven exist; otherwise return None with manual_required.

    Only final totals available at issue_time for dates before target_date and
    no later than the Singapore issue date participate. Select the highest
    visible revision per day BEFORE excluding promotional/censored/missing rows.
    No promotion normalisation, manual values or holiday factors are invented.
    Division uses 28 significant Decimal digits, half-even, with no order rounding.
    """
    _aware(issue_time)
    if (
        type(target_date) is not date
        or target_date < issue_time.astimezone(SINGAPORE).date()
    ):
        raise ValueError("target_date must not precede the Singapore issue date")
    dish_ids = [dish.id for dish in menu_items]
    if not dish_ids or len(set(dish_ids)) != len(dish_ids):
        raise ValueError("Menu must contain unique dish IDs")
    known = set(dish_ids)
    visible: dict[tuple[date, int], DailySalesObservation] = {}
    for row in history:
        if set(row.portions) - known:
            raise ValueError("Unknown dish in history")
        if (
            row.available_at > issue_time
            or row.service_date >= target_date
            or row.service_date > issue_time.astimezone(SINGAPORE).date()
        ):
            continue
        key = (row.service_date, row.revision)
        if key in visible and visible[key] != row:
            raise ValueError("Conflicting daily submission revision")
        visible[key] = row
    latest: dict[date, DailySalesObservation] = {}
    for row in visible.values():
        previous = latest.get(row.service_date)
        if previous is None or row.revision > previous.revision:
            latest[row.service_date] = row
    ordered = [latest[day] for day in sorted(latest)]
    result: dict[str, DishForecast] = {}
    for dish in sorted(dish_ids):
        eligible = [
            row
            for row in ordered
            if not row.promotion and not row.censored and dish in row.portions
        ]
        matching = [
            row
            for row in eligible
            if row.service_date.weekday() == target_date.weekday()
        ]
        flags = []
        if any(row.promotion for row in ordered):
            flags.append("PROMOTIONAL_DAYS_EXCLUDED")
        if any(row.censored for row in ordered):
            flags.append("CENSORED_DAYS_EXCLUDED")
        if any(dish not in row.portions for row in ordered):
            flags.append("MISSING_DISH_OBSERVATIONS")
        if len(matching) >= 4:
            selected = matching[-4:]
            method = "weekday_mean"
        elif len(eligible) >= 7:
            selected = eligible
            method = "eligible_day_mean"
            flags.append("SPARSE_WEEKDAY_HISTORY")
        else:
            selected = []
            method = "manual_required"
            flags.extend(
                (
                    "SPARSE_WEEKDAY_HISTORY",
                    "INSUFFICIENT_HISTORY",
                    "MANUAL_FORECAST_REQUIRED",
                )
            )
        with localcontext(Context(prec=28)):
            expected = (
                Decimal(sum(row.portions[dish] for row in selected))
                / Decimal(len(selected))
                if selected
                else None
            )
        result[dish] = DishForecast(
            expected,
            method,
            len(eligible),
            len(matching),
            tuple(
                (row.service_date, row.revision, row.available_at) for row in selected
            ),
            tuple(flags),
        )
    return result

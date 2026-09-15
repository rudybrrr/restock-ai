"""Pure allocation of projected daily demand to dated half-hour service buckets."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Literal

from src.forecasting import SINGAPORE
from src.schemas import MenuItem

HALF_HOUR = timedelta(minutes=30)


@dataclass(frozen=True)
class ServicePeriod:
    """An explicitly dated service interval and its share of daily demand.

    Weight is divided evenly among half-hours in [start, end). No default
    lunch/dinner hours or inferred closed intervals are supplied by the kernel.
    """

    start: datetime
    end: datetime
    weight: Decimal


@dataclass(frozen=True)
class ProjectedDemandBucket:
    start: datetime
    end: datetime
    expected_portions: Mapping[str, Decimal]
    provenance: Literal["PROJECTED"] = field(default="PROJECTED", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "expected_portions", MappingProxyType(dict(self.expected_portions))
        )


def _finite_nonnegative(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Demand and weights must be finite nonnegative Decimals")


def _dated_buckets(
    profile: Sequence[ServicePeriod], target_date: date
) -> list[tuple[datetime, datetime, Fraction]]:
    if type(target_date) is not date:
        raise ValueError("target_date must be a date")
    if not profile:
        raise ValueError("An explicit nonempty dated service profile is required")
    day_start = datetime.combine(target_date, time(0), tzinfo=SINGAPORE)
    day_end = day_start + timedelta(days=1)
    periods = []
    for period in profile:
        if not isinstance(period, ServicePeriod):
            raise TypeError("Profile entries must be ServicePeriod values")
        _finite_nonnegative(period.weight)
        for timestamp in (period.start, period.end):
            if (
                not isinstance(timestamp, datetime)
                or timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise ValueError("Service timestamps must be timezone-aware datetimes")
        start, end = (
            period.start.astimezone(SINGAPORE),
            period.end.astimezone(SINGAPORE),
        )
        if not day_start <= start < end <= day_end:
            raise ValueError(
                "Service intervals must be positive and within target_date"
            )
        if any(t.minute % 30 or t.second or t.microsecond for t in (start, end)):
            raise ValueError("Service timestamps must align to half-hour boundaries")
        periods.append((start, end, Fraction(period.weight)))
    if sum((p[2] for p in periods), Fraction(0)) != 1:
        raise ValueError("Profile weights must sum exactly to one; no normalisation")
    periods.sort(key=lambda p: p[0])
    result = []
    previous_end = day_start
    for start, end, weight in periods:
        if start < previous_end:
            raise ValueError("Service intervals must not overlap or duplicate")
        count = (end - start) // HALF_HOUR
        result.extend(
            (start + i * HALF_HOUR, start + (i + 1) * HALF_HOUR, weight / count)
            for i in range(count)
        )
        previous_end = end
    return result


def _allocation_units(quantity: Decimal) -> tuple[int, int]:
    """Choose a power-of-ten quantum that exactly represents this daily total."""
    if not quantity:
        return 0, -6
    parts = quantity.as_tuple()
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    # Ignore representation-only trailing zeros without context-sensitive normalize().
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    exponent = min(-6, exponent)
    units = Fraction(quantity) * 10 ** (-exponent)
    assert units.denominator == 1
    return units.numerator, exponent


def allocate_service_buckets(
    daily_forecast: Mapping[str, Decimal],
    menu_items: Sequence[MenuItem],
    *,
    target_date: date,
    profile: Sequence[ServicePeriod],
) -> tuple[ProjectedDemandBucket, ...]:
    """Allocate a complete daily forecast, preserving every dish total exactly.

    Per dish, the quantum is 1e-6 portions or finer if necessary to represent its
    daily total exactly. Floor ideal bucket allocations to that quantum, then
    distribute residual units by descending fractional remainder, earliest start
    breaking ties. Rational intermediate arithmetic avoids rounding 0.4/6 first.
    Decimal outputs are constructed exactly, independent of ambient precision.

    Every bucket includes every menu dish, including zeros, and is PROJECTED.
    Missing/unknown dishes, None forecasts, floats, invalid weights and invalid
    dates/intervals are errors. This does not estimate observed consumption.
    """
    dish_ids = {dish.id for dish in menu_items}
    if not dish_ids or len(dish_ids) != len(menu_items):
        raise ValueError("Menu must contain unique dish IDs")
    if set(daily_forecast) != dish_ids:
        raise ValueError("Daily forecast must contain exactly the catalogue dishes")
    for quantity in daily_forecast.values():
        _finite_nonnegative(quantity)
    buckets = _dated_buckets(profile, target_date)
    portions: list[dict[str, Decimal]] = [{} for _ in buckets]
    for dish in sorted(dish_ids):
        total_units, exponent = _allocation_units(daily_forecast[dish])
        ideals = [total_units * weight for _, _, weight in buckets]
        units = [ideal.numerator // ideal.denominator for ideal in ideals]
        residual = total_units - sum(units)
        priority = sorted(
            range(len(buckets)), key=lambda i: (-(ideals[i] - units[i]), i)
        )
        for i in priority[:residual]:
            units[i] += 1
        for i, count in enumerate(units):
            portions[i][dish] = Decimal((0, Decimal(count).as_tuple().digits, exponent))
    return tuple(
        ProjectedDemandBucket(start, end, values)
        for (start, end, _), values in zip(buckets, portions, strict=True)
    )

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from src.forecasting import DailySalesObservation
from src.sales_materiality_adapter import _json
from src.service_buckets import ProjectedDemandBucket


@dataclass(frozen=True)
class FrozenAssessmentInputs:
    history: tuple[DailySalesObservation, ...]
    forecast: tuple[ProjectedDemandBucket, ...]


def test_json_serializes_nested_frozen_dataclasses_with_mappingproxy_fields():
    observed_at = datetime(2026, 9, 24, 12, tzinfo=UTC)
    interval_start = datetime(2026, 9, 25, 9, tzinfo=UTC)
    frozen = FrozenAssessmentInputs(
        history=(
            DailySalesObservation(
                service_date=date(2026, 9, 24),
                available_at=observed_at,
                revision=2,
                portions={"dish-1": 7},
                promotion=False,
                censored=False,
            ),
        ),
        forecast=(
            ProjectedDemandBucket(
                start=interval_start,
                end=datetime(2026, 9, 25, 9, 30, tzinfo=UTC),
                expected_portions={"dish-1": Decimal("3.5")},
            ),
        ),
    )

    assert _json(frozen) == {
        "history": [
            {
                "service_date": "2026-09-24",
                "available_at": "2026-09-24T12:00:00+00:00",
                "revision": 2,
                "portions": {"dish-1": 7},
                "promotion": False,
                "censored": False,
            }
        ],
        "forecast": [
            {
                "start": "2026-09-25T09:00:00+00:00",
                "end": "2026-09-25T09:30:00+00:00",
                "expected_portions": {"dish-1": "3.5"},
                "provenance": "PROJECTED",
            }
        ],
    }

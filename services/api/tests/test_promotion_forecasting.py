"""Independent promotion/diff oracles using the current canonical catalogue."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest
from test_inventory_projection import inputs as inputs  # noqa: PLC0414

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.inventory_projection import SourceEvidence, project_inventory
from src.operations_schemas import PromotionEvent, SalesBatch
from src.promotion_forecasting import (
    SOURCES,
    ForecastVersion,
    apply_promotions,
    compare_forecast_versions,
)
from src.requirements import calculate_requirements
from src.schemas import Ingredient, MenuItem, RecipeItem
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"


def dt(value):
    return datetime.fromisoformat(value)


@pytest.fixture
def case():
    fixture = json.loads((FIXTURES / "promotion_forecast_v1.json").read_text())
    normal = json.loads((FIXTURES / fixture["catalogue_history_fixture"]).read_text())
    service = json.loads((FIXTURES / fixture["service_profile_fixture"]).read_text())
    menu = [MenuItem.model_validate(r) for r in normal["menu_items"]]
    history = [
        DailySalesObservation(
            date.fromisoformat(r["service_date"]),
            dt(r["available_at"]),
            r["revision"],
            r["portions"],
            r["promotion"],
            r["censored"],
        )
        for r in normal["history"]
    ]
    clock = dt(normal["issue_time"])
    target = date.fromisoformat(normal["target_date"])
    forecast = seasonal_baseline(history, menu, issue_time=clock, target_date=target)
    daily = {}
    for dish, result in forecast.items():
        assert result.expected_portions is not None
        daily[dish] = result.expected_portions
    profile = tuple(
        ServicePeriod(dt(p["start"]), dt(p["end"]), D(p["weight"]))
        for p in service["periods"]
    )
    evidence = SourceEvidence(
        fixture["context_reference"], clock, fixture["captured_revision"]
    )
    basis = ForecastVersion(
        "fixture/normal",
        clock,
        clock,
        target,
        profile,
        tuple(
            (k, replace(evidence, reference="fixture/" + k)) for k in sorted(SOURCES)
        ),
        allocate_service_buckets(daily, menu, target_date=target, profile=profile),
        "EXCLUDED",
        "fixture/normal",
    )
    return {
        "fixture": fixture,
        "normal": normal,
        "menu": menu,
        "basis": basis,
        "events": [PromotionEvent.model_validate(fixture["event"])],
        "kwargs": {
            "context_evidence": evidence,
            "context_complete": True,
            "as_of": clock,
            "known_at": clock,
            "result_reference": fixture["result_reference"],
        },
    }


def apply(case, **kwargs):
    return apply_promotions(
        case["basis"],
        case["menu"],
        events=case["events"],
        **(case["kwargs"] | kwargs),
    )


def total(forecast, dish):
    return sum(
        (Fraction(b.expected_portions[dish]) for b in forecast.buckets), Fraction()
    )


def edit(case, **values):
    event = case["events"][0].model_copy(deep=True)
    event.payload = event.payload.model_copy(update=values)
    case["events"] = [event]


def revision(case, *, recorded="2026-02-15T21:30:00+08:00", **values):
    first = case["events"][0]
    return first.model_copy(
        update={
            "id": "fixture-event-promo-2",
            "type": "PROMOTION_CHANGED",
            "timestamp": dt(recorded),
            "payload": first.payload.model_copy(update={"revision": 2} | values),
        },
        deep=True,
    )


def assert_incomplete(result, message):
    assert not result.complete and result.forecast is None
    assert message.lower() in result.findings[0].source.lower()


def test_normal_and_explicit_multiplier_recipe_oracle(case):
    events = case["events"]
    case["events"] = []
    normal = apply(case)
    assert normal.complete and normal.forecast
    assert normal.forecast.buckets == case["basis"].buckets
    case["events"] = events
    result = apply(case)
    assert result.complete and result.forecast
    expected = case["fixture"]["expected_daily_portions"]
    # Explicit independent totals, not generated from the production calculation.
    for dish, quantity in expected.items():
        assert total(result.forecast, dish) == D(quantity)
    daily = {
        dish: sum((b.expected_portions[dish] for b in result.forecast.buckets), D(0))
        for dish in expected
    }
    cat = case["normal"]
    requirements = calculate_requirements(
        daily,
        case["menu"],
        [Ingredient.model_validate(r) for r in cat["ingredients"]],
        [RecipeItem.model_validate(r) for r in cat["recipes"]],
    )
    assert requirements == {
        k: D(v) for k, v in case["fixture"]["expected_ingredient_quantities"].items()
    }
    # Promotion effects are already portions; no second free-portion multiplier.
    assert result.forecast.buckets[6].expected_portions["chicken-rice"] == D(9)
    assert len(result.overlaps) == 14


def test_downstream_projector_receives_only_adjusted_portions(case, inputs):
    result = apply(case)
    assert result.forecast
    # Existing fixture provides complete opening/supply evidence and exact recipes.
    inputs.update(
        buckets=result.forecast.buckets,
        service_profile=result.forecast.profile,
        horizon_end=dt("2026-02-16T22:00:00+08:00"),
    )
    projection = project_inventory(**inputs)
    assert projection.complete and projection.ingredients
    assert {i.ingredient_id: i.required for i in projection.ingredients} == {
        k: D(v) for k, v in case["fixture"]["expected_ingredient_quantities"].items()
    }


@pytest.mark.parametrize(
    "start,end", [("2026-02-17", "2026-02-18"), ("2026-02-14", "2026-02-15")]
)
def test_nonoverlap_unchanged(case, start, end):
    edit(case, start_date=date.fromisoformat(start), end_date=date.fromisoformat(end))
    result = apply(case)
    assert result.complete and result.forecast
    assert result.forecast.buckets == case["basis"].buckets
    assert result.overlaps == ()


def test_known_future_effective_revision_changes_only_dinner(case):
    edit(case, effective_at=dt("2026-02-16T17:00:00+08:00"))
    result = apply(case)
    assert result.complete and result.forecast
    assert result.forecast.buckets[:6] == case["basis"].buckets[:6]
    # 40 normal lunch + (60 * 1.2) dinner = 112.
    assert total(result.forecast, "chicken-rice") == 112


def test_later_recording_cannot_change_frozen_result(case):
    event = case["events"][0]
    event.timestamp = case["basis"].known_at + timedelta(seconds=1)
    result = apply(case)
    assert result.complete and result.forecast
    assert result.forecast.buckets == case["basis"].buckets
    assert not result.overlaps


def test_revisions_cancellation_and_input_order(case):
    second = revision(case, demand_multiplier=D("1.5"))
    case["events"].append(second)
    result = apply(case)
    assert result.complete and result.forecast
    assert total(result.forecast, "chicken-rice") == 150
    case["events"].reverse()
    assert apply(case) == result
    second.payload.active = False
    cancelled = apply(case)
    assert cancelled.complete and cancelled.forecast
    assert cancelled.forecast.buckets == case["basis"].buckets


def test_late_cancellation_excluded_and_future_cancellation_applied(case):
    second = revision(case, recorded="2026-02-15T22:01:00+08:00", active=False)
    case["events"].append(second)
    early = apply(case)
    assert early.forecast and total(early.forecast, "chicken-rice") == 120
    second.timestamp = dt("2026-02-15T21:30:00+08:00")
    second.payload.effective_at = dt("2026-02-16T17:00:00+08:00")
    result = apply(case)
    assert result.forecast
    # Lunch 40 * 1.2, dinner 60 unchanged after cancellation.
    assert total(result.forecast, "chicken-rice") == 108


def test_repeated_frozen_inputs_and_mutation(case):
    before = [e.model_dump_json() for e in case["events"]]
    basis = case["basis"]
    first = apply(case)
    assert first == apply(case)
    assert before == [e.model_dump_json() for e in case["events"]]
    assert case["basis"] == basis
    assert first.forecast
    case["basis"] = first.forecast
    assert_incomplete(apply(case), "unadjusted")
    # Mutating the caller's canonical event cannot mutate an emitted artifact.
    case["events"][0].payload.demand_multiplier = D(9)
    assert total(first.forecast, "chicken-rice") == 120
    with pytest.raises(TypeError):
        first.forecast.buckets[0].expected_portions["chicken-rice"] = D(0)  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize("state", ["UNKNOWN", "APPLIED"])
def test_ambiguous_or_included_basis(case, state):
    case["basis"] = replace(case["basis"], promotion_state=state)
    assert not apply(case).complete


def test_overlapping_promotions_explicitly_incomplete(case):
    event = case["events"][0].model_copy(deep=True)
    event.id = "other-event"
    event.payload.promotion_id = "other-promotion"
    case["events"].append(event)
    result = apply(case)
    assert_incomplete(result, "stacking")
    assert result.overlaps  # independent of any sales-deviation threshold


def test_different_dishes_can_share_period_without_stacking(case):
    event = case["events"][0].model_copy(deep=True)
    event.id = "other-event"
    event.payload.promotion_id = "other-promotion"
    event.payload.menu_item_ids = ["tofu-bowl"]
    event.payload.demand_multiplier = D("1.5")
    case["events"].append(event)
    result = apply(case)
    assert result.forecast
    assert total(result.forecast, "chicken-rice") == 120
    assert total(result.forecast, "tofu-bowl") == 60


@pytest.mark.parametrize(
    "values,fragment",
    [
        ({"menu_item_ids": ["unknown"]}, "dish"),
        ({"menu_item_ids": []}, "dish"),
        ({"demand_multiplier": D("-1")}, "nonnegative"),
        ({"demand_multiplier": D("NaN")}, "finite"),
        ({"demand_multiplier": D("Infinity")}, "finite"),
        ({"demand_multiplier": D("0")}, "adjustment"),
        ({"demand_multiplier": D("11")}, "adjustment"),
        ({"demand_multiplier": None}, "Decimal"),
        ({"revision": 2}, "revision history"),
    ],
)
def test_invalid_promotion_inputs(case, values, fragment):
    edit(case, **values)
    assert_incomplete(apply(case), fragment)


@pytest.mark.parametrize("field", ["reference", "captured_revision", "available_at"])
def test_missing_evidence(case, field):
    ev = replace(case["kwargs"]["context_evidence"], **{field: None})
    assert_incomplete(apply(case, context_evidence=ev), "evidence")


def test_missing_assumption_and_incomplete_context(case):
    case["events"][0].source = ""
    assert_incomplete(apply(case), "identities")
    assert not apply(case, context_complete=False).complete


@pytest.mark.parametrize(
    "when", ["2026-02-16T11:15:00+08:00", "2026-02-16T17:15:00+08:00"]
)
def test_partial_bucket_effect_unsupported(case, when):
    edit(case, effective_at=dt(when))
    assert_incomplete(apply(case), "inside service bucket")


def test_partial_bucket_cancellation_is_not_silently_ignored(case):
    case["events"].append(
        revision(case, active=False, effective_at=dt("2026-02-16T11:15:00+08:00"))
    )
    assert_incomplete(apply(case), "inside service bucket")


def sales_for(case):
    # Six complete elapsed lunch half-hours, seven actual chicken portions each.
    return [
        (
            SalesBatch(
                id=f"actual-{i}",
                source="fixture",
                batch_id=str(i),
                revision=1,
                active=True,
                period_start=b.start,
                period_end=b.end,
                sales={"chicken-rice": 7},
            ),
            case["kwargs"]["context_evidence"],
        )
        for i, b in enumerate(case["basis"].buckets[:6])
    ]


def test_actual_lunch_preserved_only_future_adjusted(case):
    result = apply(
        case,
        as_of=dt("2026-02-16T14:00:00+08:00"),
        sales=sales_for(case),
        actual_coverage=case["kwargs"]["context_evidence"],
    )
    assert result.complete and result.forecast
    assert len(result.forecast.buckets) == 8
    assert total(result.forecast, "chicken-rice") == 72
    assert sum(dict(a.portions)["chicken-rice"] for a in result.forecast.actuals) == 42
    assert all(dict(a.portions)["fried-rice"] == 0 for a in result.forecast.actuals)
    assert all(b.start.hour >= 17 for b in result.forecast.buckets)
    assert all(a.evidence for a in result.forecast.actuals)


@pytest.mark.parametrize(
    "mode", ["missing", "duplicate", "inactive", "late", "partial"]
)
def test_actual_coverage_errors_explicit(case, mode):
    sales = sales_for(case)
    if mode == "missing":
        sales.pop()
    elif mode == "duplicate":
        sales.append(sales[0])
    elif mode == "inactive":
        sales[0][0].active = False
    elif mode == "late":
        sales[0] = (
            sales[0][0],
            replace(sales[0][1], available_at=dt("2026-02-16T15:00:00+08:00")),
        )
    else:
        sales[0][0].period_end -= timedelta(minutes=15)
    assert not apply(
        case,
        as_of=dt("2026-02-16T14:00:00+08:00"),
        sales=sales,
        actual_coverage=case["kwargs"]["context_evidence"],
    ).complete


def test_intraday_cutoff_inside_bucket_incomplete(case):
    assert_incomplete(
        apply(case, as_of=dt("2026-02-16T11:15:00+08:00")), "partial-bucket"
    )


def test_decimal_conservation_independent_of_ambient_context(case):
    edit(case, demand_multiplier=D("1.23456789"))
    with localcontext() as ctx:
        ctx.prec = 3
        result = apply(case)
    assert result.forecast
    assert total(result.forecast, "chicken-rice") == Fraction("123.456789")
    assert result.forecast.buckets[6].expected_portions["chicken-rice"] == D(
        "9.259259175"
    )


def test_immutable_comparison_deltas_and_initial_forecast(case):
    result = apply(case)
    assert result.forecast
    comparison = compare_forecast_versions(case["basis"], result.forecast, case["menu"])
    assert comparison.status == "COMPARED" and comparison.deltas
    dinner = next(
        d
        for d in comparison.deltas
        if d.start.hour == 17 and d.dish_id == "chicken-rice"
    )
    assert (
        dinner.old,
        dinner.new,
        dinner.delta,
        dinner.absolute_delta,
        dinner.relative_delta,
    ) == (D("7.5"), D("9"), D("1.5"), D("1.5"), D(".2"))
    assert sum(d.delta for d in comparison.deltas if d.dish_id == "chicken-rice") == 20
    assert comparison.previous is case["basis"]
    assert comparison.current is result.forecast
    assert comparison.attribution == "NO_CAUSAL_CLAIM"
    initial = compare_forecast_versions(None, result.forecast, case["menu"])
    assert initial.status == "NO_PREVIOUS_VERSION" and not initial.findings
    assert initial.current is result.forecast  # new forecast remains valid


def test_negative_and_zero_baseline_deltas(case):
    old = case["basis"]
    buckets = list(old.buckets)
    values = dict(buckets[0].expected_portions)
    values["chicken-rice"] = D(0)
    buckets[0] = ProjectedDemandBucket(buckets[0].start, buckets[0].end, values)
    zero = replace(old, reference="zero", base_reference="zero", buckets=tuple(buckets))
    comparison = compare_forecast_versions(zero, old, case["menu"])
    assert comparison.deltas
    row = next(d for d in comparison.deltas if d.dish_id == "chicken-rice")
    assert row.relative_delta is None and row.relative_reason == "ZERO_BASELINE"
    reverse = compare_forecast_versions(old, zero, case["menu"])
    assert reverse.deltas
    row = next(d for d in reverse.deltas if d.dish_id == "chicken-rice")
    assert row.delta == D("-6.666667") and row.absolute_delta == D("6.666667")
    assert row.relative_delta == -1


@pytest.mark.parametrize(
    "source", ["catalogue", "recipe", "model", "profile", "policy"]
)
def test_incompatible_source_versions(case, source):
    old = case["basis"]
    sources = dict(old.sources)
    sources[source] = replace(sources[source], reference="changed")
    new = replace(
        old, reference="new", base_reference="new", sources=tuple(sources.items())
    )
    diff = compare_forecast_versions(old, new, case["menu"])
    assert diff.status == "INCOMPATIBLE" and diff.deltas is None
    assert source in diff.changed_context


def test_changed_history_disallows_promotion_only_attribution(case):
    result = apply(case)
    assert result.forecast
    sources = dict(result.forecast.sources)
    sources["history"] = replace(sources["history"], reference="changed-history")
    current = replace(result.forecast, sources=tuple(sources.items()))
    comparison = compare_forecast_versions(case["basis"], current, case["menu"])
    assert comparison.status == "COMPARED"
    assert "history" in comparison.changed_context
    assert "promotions" in comparison.changed_context
    assert comparison.attribution == "NO_CAUSAL_CLAIM"


@pytest.mark.parametrize(
    "change",
    [
        {"units": "TRANSACTIONS"},
        {"buckets": ()},
        {"target_date": date(2026, 2, 17)},
        {"application_policy": "unknown"},
    ],
)
def test_incompatible_coverage(case, change):
    current = replace(case["basis"], reference="new", base_reference="new", **change)
    result = compare_forecast_versions(case["basis"], current, case["menu"])
    assert result.status == "INCOMPATIBLE" and result.deltas is None


def test_conflicting_immutable_id_and_reordered_profile(case):
    old = case["basis"]
    changed = replace(old, known_at=old.known_at + timedelta(seconds=1))
    assert (
        compare_forecast_versions(old, changed, case["menu"]).status == "INCOMPATIBLE"
    )
    reordered = replace(
        old,
        reference="same-content",
        base_reference="same-content",
        profile=old.profile[::-1],
    )
    result = compare_forecast_versions(old, reordered, case["menu"])
    assert result.status == "COMPARED" and result.deltas
    assert all(d.delta == 0 for d in result.deltas)


def test_name_does_not_double_demand_without_factor(case):
    edit(case, demand_multiplier=D(1))
    result = apply(case)
    assert result.forecast and result.forecast.buckets == case["basis"].buckets
    assert (
        result.overlaps
    )  # Known overlap remains evidence even with no quantity delta.


def test_cancellation_keeps_resolvable_revision_evidence(case):
    case["events"].append(revision(case, active=False))
    result = apply(case)
    assert result.forecast
    assert result.forecast.revision_evidence == (
        ("fixture-promotion-chicken", 1, "fixture-event-promo-1"),
        ("fixture-promotion-chicken", 2, "fixture-event-promo-2"),
    )
    assert result.forecast.context_evidence == case["kwargs"]["context_evidence"]


@pytest.mark.parametrize("quantity", [D(-1), D("NaN"), D("Infinity"), 1.2])
def test_invalid_basis_quantities_incomplete(case, quantity):
    basis = case["basis"]
    buckets = list(basis.buckets)
    portions = dict(buckets[0].expected_portions)
    portions["chicken-rice"] = quantity
    buckets[0] = ProjectedDemandBucket(buckets[0].start, buckets[0].end, portions)
    case["basis"] = replace(basis, buckets=tuple(buckets))
    assert not apply(case).complete


def test_missing_basis_sources_and_invalid_clocks(case):
    basis = case["basis"]
    case["basis"] = replace(basis, sources=basis.sources[:-1])
    assert_incomplete(apply(case), "source manifest")
    case["basis"] = basis
    assert not apply(case, known_at=basis.known_at - timedelta(seconds=1)).complete
    assert not apply(case, as_of=basis.as_of.replace(tzinfo=None)).complete
    assert not apply(case, result_reference=basis.reference).complete


def test_duplicate_and_nonmonotone_revisions_rejected(case):
    case["events"].append(case["events"][0])
    assert not apply(case).complete
    case["events"].pop()
    case["events"].append(revision(case, effective_at=dt("2026-02-15T19:00:00+08:00")))
    assert_incomplete(apply(case), "Non-monotone")


def test_no_comparison_calls_forecasting_or_application(case, monkeypatch):
    result = apply(case)
    assert result.forecast

    def forbidden(*args, **kwargs):
        pytest.fail("Diff must not reforecast or reapply promotions")

    monkeypatch.setattr("src.forecasting.seasonal_baseline", forbidden)
    monkeypatch.setattr("src.promotion_forecasting.apply_promotions", forbidden)
    comparison = compare_forecast_versions(case["basis"], result.forecast, case["menu"])
    assert comparison.status == "COMPARED"


def test_relative_rounding_and_zero_to_zero_independent(case):
    old = case["basis"]

    def fixed(reference, quantity):
        buckets = tuple(
            ProjectedDemandBucket(
                b.start,
                b.end,
                {
                    dish: quantity if dish == "chicken-rice" else D(0)
                    for dish in b.expected_portions
                },
            )
            for b in old.buckets
        )
        return replace(
            old, reference=reference, base_reference=reference, buckets=buckets
        )

    with localcontext() as ctx:
        ctx.prec = 3
        result = compare_forecast_versions(
            fixed("three", D(3)), fixed("four", D(4)), case["menu"]
        )
    assert result.deltas
    chicken = next(d for d in result.deltas if d.dish_id == "chicken-rice")
    assert chicken.delta == chicken.absolute_delta == 1
    assert chicken.relative_delta == D("0.3333333333333333333333333333")
    other = next(d for d in result.deltas if d.dish_id == "fried-rice")
    assert other.old == other.new == other.delta == 0
    assert other.relative_reason == "ZERO_BASELINE" and other.relative_delta is None


def test_current_canonical_model_rejects_partial_day_extra_fields(case):
    # Canonical transport has dates, no campaign clock-window field. Do not
    # construct an alternate interval payload and silently apply a whole day.
    from pydantic import ValidationError

    from src.changes import PromotionInput

    raw = case["events"][0].payload.model_dump()
    del raw["promotion_id"]
    raw["service_start"] = "17:00:00"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PromotionInput.model_validate(raw)

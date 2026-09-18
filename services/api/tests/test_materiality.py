"""Independent sales/risk oracles against canonical Backend frozen payloads."""

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from test_procurement import reference as reference  # noqa: PLC0414

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.history_dataset import Catalogue
from src.inventory_projection import FEFO_POLICY, ExpectedSupply, SourceEvidence
from src.materiality import (
    SAFETY_POLICY,
    RiskSnapshot,
    SalesThresholdPolicy,
    assess_sales_materiality,
    select_daily_history,
)
from src.operations_schemas import (
    DailyRevision,
    Delivery,
    PromotionEvent,
    Receipt,
    SalesBatch,
    SalesReconciliation,
)
from src.procurement_contract_schemas import ProcurementContract
from src.procurement_contracts import (
    _build,
    first_slice_seed_rows,
    freeze_operational_activity,
)
from src.promotion_forecasting import SOURCES, ForecastVersion, apply_promotions
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

D = Decimal
dt = datetime.fromisoformat


@pytest.fixture
def case(reference):
    f = json.loads(
        (Path(__file__).parent / "fixtures/sales_materiality_v1.json").read_text()
    )
    known, cutoff = dt(f["known_at"]), dt(f["as_of"])
    rows = first_slice_seed_rows(known - timedelta(hours=1))
    for row in rows["forecast_inputs"][0]["payload"]["history"]:
        row["portions"] = {d: 150 for d in row["portions"]}
    c = _build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    )
    c = c.model_copy(
        update={
            "as_of": cutoff,
            "known_at": known,
            "run_id": "synthetic-sales-run",
            "captured_state_revision": f["captured_state_revision"],
        }
    )
    inv = reference.inventory.copy()
    cat = Catalogue(
        menu_items=tuple(inv["menu_items"]),
        ingredients=tuple(inv["ingredients"]),
        recipes=tuple(inv["recipes"]),
    )
    ev = SourceEvidence("synthetic/frozen-snapshot", known, c.captured_state_revision)
    profile = tuple(
        ServicePeriod(p.start, p.end, p.weight)
        for p in c.policy.payload.service_profile
    )
    history = [
        DailySalesObservation(
            r.service_date,
            r.available_at,
            r.revision,
            r.portions,
            r.promotion,
            r.censored,
        )
        for r in c.forecast_input.payload.history
    ]
    forecast = seasonal_baseline(
        history,
        cat.menu_items,
        issue_time=c.policy.payload.issue_time,
        target_date=c.policy.payload.target_date,
    )
    daily = {}
    for dish, value in forecast.items():
        assert value.expected_portions is not None
        daily[dish] = value.expected_portions
    basis = ForecastVersion(
        "synthetic/normal",
        c.policy.payload.issue_time,
        known - timedelta(minutes=10),
        c.policy.payload.target_date,
        profile,
        tuple(
            (
                k,
                replace(
                    ev,
                    reference=c.forecast_input.id
                    if k == "history"
                    else "synthetic/" + k,
                    available_at=known - timedelta(hours=1),
                ),
            )
            for k in sorted(SOURCES)
        ),
        allocate_service_buckets(
            daily,
            cat.menu_items,
            target_date=c.policy.payload.target_date,
            profile=profile,
        ),
        "EXCLUDED",
        "synthetic/normal",
    )
    applied = apply_promotions(
        basis,
        cat.menu_items,
        events=[],
        context_evidence=replace(
            ev,
            reference="synthetic/promotion-context",
            available_at=known - timedelta(hours=1),
        ),
        context_complete=True,
        as_of=basis.as_of,
        known_at=basis.known_at,
        result_reference="synthetic/issued",
    )
    assert applied.forecast is not None
    issued = applied.forecast
    inv.update(
        as_of=cutoff,
        known_at=known,
        captured_revision=c.captured_state_revision,
        horizon_end=c.policy.payload.horizon_end,
        service_profile=profile,
        buckets=tuple(b for b in issued.buckets if b.start >= cutoff),
        fixture_fefo=FEFO_POLICY,
        evidence={
            k: replace(
                ev, reference=issued.reference if k == "forecast" else "synthetic/" + k
            )
            for k in inv["evidence"]
        },
    )
    inv["opening_lots"] = [
        lot.model_copy(
            update={
                "quantity": D(f["opening_per_ingredient"]),
                "initial_quantity": D(f["opening_per_ingredient"]),
                "as_of": cutoff,
                "counted_at": cutoff,
                "coverage_start": cutoff,
            }
        )
        for lot in inv["opening_lots"]
    ]
    batches = []
    for index, b in enumerate(issued.buckets[:2]):
        batch = SalesBatch(
            id=f"sales-{index}-r1",
            source="synthetic-pos",
            batch_id=f"batch-{index}",
            period_start=b.start,
            period_end=b.end,
            sales={d: 10 for d in daily},
            revision=1,
            active=True,
        )
        batches.append(
            batch.model_dump(mode="json")
            | {"recorded_at": (known - timedelta(minutes=2)).isoformat()}
        )
    state = {
        "inventory": [r.model_dump(mode="json") for r in inv["opening_lots"]],
        "menu_items": [r.model_dump(mode="json") for r in cat.menu_items],
        "ingredients": [r.model_dump(mode="json") for r in cat.ingredients],
        "recipes": [r.model_dump(mode="json") for r in cat.recipes],
        "commitments": [],
        "sales_batches": batches,
        "daily_history": [],
        "authoritative_daily_sales": [],
    }
    c = ProcurementContract.model_validate(
        freeze_operational_activity(c.model_dump(mode="json"), state)
    )
    threshold = f["threshold"]
    policy = SalesThresholdPolicy(
        threshold["version"],
        threshold["rule"],
        D(threshold["absolute_floor"]),
        D(threshold["relative_threshold"]),
        D(threshold["minimum_expected_portions"]),
        threshold["minimum_complete_buckets"],
        replace(ev, reference="synthetic/threshold-policy"),
    )
    return {
        "contract": c,
        "issued_forecast": issued,
        "issued_input": c.forecast_input.model_copy(deep=True),
        "issued_catalogue": cat,
        "snapshot_evidence": ev,
        "threshold_policy": policy,
        "risk": RiskSnapshot(
            inv,
            replace(ev, reference="synthetic/active-plan-v1"),
            dict(c.policy.payload.safety_stock),
            SAFETY_POLICY,
            replace(ev, reference="synthetic/safety"),
        ),
    }


def run(case, **changes):
    return assess_sales_materiality(**(case | changes))


def batches(case):
    return case["contract"].frozen_state["sales_batches"]


def observed(case, count, dish="chicken-rice"):
    batches(case)[1]["sales"][dish] = count - batches(case)[0]["sales"].get(dish, 0)


def codes(result):
    return {f.code for f in result.findings}


def chicken(result):
    return next(r for r in result.sales if r.dish_id == "chicken-rice")


def set_expected(case, quantity):
    issued = case["issued_forecast"]
    values = list(issued.buckets)
    for i in range(2):
        old = values[i]
        values[i] = ProjectedDemandBucket(
            old.start,
            old.end,
            dict(old.expected_portions) | {"chicken-rice": D(quantity) / 2},
        )
    case["issued_forecast"] = replace(issued, buckets=tuple(values))


@pytest.mark.parametrize(
    ("actual", "material", "delta"),
    [
        (24, False, "4"),
        (25, True, "5"),
        (26, True, "6"),
        (16, False, "-4"),
        (15, True, "-5"),
        (14, True, "-6"),
    ],
)
def test_explicit_twenty_portion_policy_boundaries(case, actual, material, delta):
    observed(case, actual)
    result = run(case)
    assert result.complete
    assert result.material_change is material
    row = chicken(result)
    assert (row.expected, row.observed, row.deviation, row.threshold) == (
        D(20),
        D(actual),
        D(delta),
        D(5),
    )
    assert row.adequate_exposure
    assert result.feasible_under_observed_state is None
    assert result.inventory_feasible is True
    assert not hasattr(result, "outcome")


@pytest.mark.parametrize(
    ("expected", "observed_count", "threshold", "material"),
    [
        ("100", 119, "20", False),
        ("100", 120, "20", True),
        ("100", 80, "20", True),
        ("24.999999", 30, "5", True),
        ("25.000001", 30, "5.0000002", False),
        ("20.000001", 25, "5", False),
        ("19.999999", 25, "5", True),
    ],
)
def test_fractional_and_percentage_oracles(
    case, expected, observed_count, threshold, material
):
    set_expected(case, expected)
    case["threshold_policy"] = replace(
        case["threshold_policy"], minimum_expected_portions=D(0)
    )
    observed(case, observed_count)
    with localcontext() as ctx:
        ctx.prec = 5
        result = run(case)
    assert result.complete
    assert result.material_change is material
    assert chicken(result).threshold == D(threshold)


def test_small_batches_accumulate(case):
    batches(case)[0]["sales"]["chicken-rice"] = 13
    batches(case)[1]["sales"]["chicken-rice"] = 13
    result = run(case)
    assert result.complete and result.material_change is True
    assert chicken(result).deviation == D(
        6
    )  # +3 in each, neither individually reaches 5
    assert len(result.compared_intervals) == 2


def test_sparse_exposure_and_known_breach(case):
    case["threshold_policy"] = replace(
        case["threshold_policy"], minimum_expected_portions=D(21)
    )
    result = run(case)
    assert result.material_change is None and "INSUFFICIENT_EXPOSURE" in codes(result)
    assert chicken(result).adequate_exposure is False
    set_stock(case, D(0))
    result = run(case)
    assert result.material_change is True and not result.complete
    assert result.first_stockout_interval is not None
    assert result.first_stockout_interval.start == dt("2026-02-16T12:00+08:00")


@pytest.mark.parametrize("minimum", ["0", "20"])
def test_zero_expected_without_percentage_division(case, minimum):
    set_expected(case, "0")
    case["threshold_policy"] = replace(
        case["threshold_policy"], minimum_expected_portions=D(minimum)
    )
    batches(case)[0]["sales"].pop("chicken-rice")
    batches(case)[1]["sales"].pop("chicken-rice")
    result = run(case)
    assert chicken(result).expected == 0 and chicken(result).observed == 0
    assert chicken(result).threshold == 5
    assert chicken(result).material is (False if minimum == "0" else None)


def test_complete_observed_zero_vs_absent_batch(case):
    for row in batches(case):
        row["sales"].pop("chicken-rice")
    result = run(case)
    assert result.complete and result.material_change is True
    assert chicken(result).observed == 0 and chicken(result).deviation == -20
    batches(case).pop()
    result = run(case)
    assert not result.complete and chicken(result).observed is None
    assert result.remainder is None and len(result.missing_intervals) == 1


def test_corrections_replace_and_late_recordings_do_not_leak(case):
    observed(case, 25)
    first = batches(case)[1]
    correction = copy.deepcopy(first) | {
        "id": "correction-2",
        "revision": 2,
        "replaces_id": first["id"],
        "recorded_at": case["contract"].known_at.isoformat(),
    }
    correction["sales"]["chicken-rice"] = 10
    batches(case).append(correction)
    result = run(case)
    assert result.complete and result.material_change is False
    assert chicken(result).observed == 20
    assert result.remainder is not None
    assert result.remainder.actuals[1].batch_id == "correction-2"
    assert len(result.remainder.actuals) == 2
    correction["recorded_at"] = (
        case["contract"].known_at + timedelta(seconds=1)
    ).isoformat()
    assert run(case).material_change is True


def test_backend_selected_correction_does_not_require_old_rows(case):
    row = batches(case)[1]
    row.update(id="corrected-selected", revision=3, replaces_id="prior-not-selected")
    result = run(case)
    assert result.complete and result.remainder is not None
    assert result.remainder.actuals[1].revision == 3


def test_idempotent_retry_has_one_effect(case):
    batches(case).append(copy.deepcopy(batches(case)[0]))
    result = run(case)
    assert result.complete and chicken(result).observed == 20


@pytest.mark.parametrize(
    "change", ["duplicate", "overlap", "identity", "interval", "unknown", "negative"]
)
def test_structurally_invalid_batches(case, change):
    row = copy.deepcopy(batches(case)[0])
    if change == "duplicate":
        row["sales"]["chicken-rice"] = 15
    elif change == "overlap":
        row.update(id="other", batch_id="other")
    elif change == "identity":
        row.update(
            id="correction",
            batch_id="different",
            revision=2,
            replaces_id=batches(case)[0]["id"],
        )
    elif change == "interval":
        row.update(
            id="correction",
            revision=2,
            replaces_id=batches(case)[0]["id"],
            period_end="2026-02-16T11:45:00+08:00",
        )
    elif change == "unknown":
        row["sales"]["unknown-dish"] = 1
    else:
        row["sales"]["chicken-rice"] = -1
    batches(case).append(row)
    with pytest.raises(ValueError):
        run(case)


def test_partial_and_multi_bucket_reports_are_not_prorated(case):
    batches(case)[0]["period_end"] = "2026-02-16T11:15:00+08:00"
    result = run(case)
    assert not result.complete and result.remainder is None
    assert "UNSUPPORTED_SALES_INTERVAL" in codes(result)
    batches(case)[0]["period_end"] = "2026-02-16T12:00:00+08:00"
    batches(case).pop()
    assert "UNSUPPORTED_SALES_INTERVAL" in codes(run(case))


def test_partial_assessment_boundary_incomplete(case):
    case["contract"].as_of = dt("2026-02-16T11:45:00+08:00")
    result = run(case)
    assert not result.complete and result.remainder is None
    assert "UNSUPPORTED_PARTIAL_INTERVAL" in codes(result)


def test_future_operational_sales_excluded(case):
    future = copy.deepcopy(batches(case)[0])
    future.update(
        id="future",
        batch_id="future",
        period_start="2026-02-16T12:00:00+08:00",
        period_end="2026-02-16T12:30:00+08:00",
        sales={"chicken-rice": 999},
    )
    batches(case).append(future)
    assert run(case).complete and chicken(run(case)).observed == 20


@pytest.mark.parametrize(
    "missing",
    [
        "policy",
        "version",
        "minimum_expected_portions",
        "minimum_complete_buckets",
        "evidence",
    ],
)
def test_missing_policy_is_incomplete(case, missing):
    case["threshold_policy"] = (
        None
        if missing == "policy"
        else replace(case["threshold_policy"], **{missing: None})
    )
    result = run(case)
    assert not result.complete and result.material_change is None
    assert chicken(result).material is None
    assert result.remainder is not None  # policy does not alter future forecast


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("absolute_floor", D(-1)),
        ("relative_threshold", D("NaN")),
        ("minimum_expected_portions", D("Infinity")),
        ("minimum_complete_buckets", 0),
    ],
)
def test_malformed_threshold_policy(case, field, value):
    with pytest.raises((ValueError, TypeError)):
        run(case, threshold_policy=replace(case["threshold_policy"], **{field: value}))


def test_unapproved_rule_values_not_silently_applied(case):
    assert "UNSUPPORTED_THRESHOLD_POLICY" in codes(
        run(
            case,
            threshold_policy=replace(case["threshold_policy"], absolute_floor=D(4)),
        )
    )


@pytest.mark.parametrize(
    "kind",
    [
        "capture",
        "profile",
        "input",
        "history_ref",
        "catalogue",
        "unadjusted",
        "late_forecast",
    ],
)
def test_incompatible_provenance(case, kind):
    if kind == "capture":
        case["snapshot_evidence"] = replace(
            case["snapshot_evidence"], captured_revision="different"
        )
    elif kind == "profile":
        c = case["contract"]
        c.policy.payload.service_profile[0].weight = D("0.5")
        c.policy.payload.service_profile[1].weight = D("0.5")
    elif kind == "input":
        case["contract"].forecast_input.payload.history[0].portions["chicken-rice"] = (
            999
        )
    elif kind == "history_ref":
        issued = case["issued_forecast"]
        case["issued_forecast"] = replace(
            issued,
            sources=tuple(
                (k, replace(v, reference="wrong") if k == "history" else v)
                for k, v in issued.sources
            ),
        )
    elif kind == "catalogue":
        case["contract"].frozen_state["recipes"][0]["quantity"] = "0.999"
    elif kind == "unadjusted":
        issued = case["issued_forecast"]
        case["issued_forecast"] = replace(
            issued, promotion_state="EXCLUDED", base_reference=issued.reference
        )
    else:
        case["issued_forecast"] = replace(
            case["issued_forecast"],
            known_at=case["contract"].known_at + timedelta(seconds=1),
        )
    result = run(case)
    assert not result.complete and result.material_change is None
    assert result.remainder is None


def test_promotion_aware_expectation_and_no_second_uplift(case):
    issued = case["issued_forecast"]
    base = replace(
        issued,
        reference=issued.base_reference,
        promotion_state="EXCLUDED",
        context_evidence=None,
    )
    event = PromotionEvent.model_validate(
        {
            "id": "synthetic-promo",
            "type": "PROMOTION_CREATED",
            "timestamp": (issued.known_at - timedelta(minutes=5)).isoformat(),
            "source": "synthetic-manager",
            "payload": {
                "promotion_id": "campaign",
                "name": "test",
                "revision": 1,
                "active": True,
                "effective_at": issued.as_of.isoformat(),
                "start_date": "2026-02-16",
                "end_date": "2026-02-16",
                "menu_item_ids": ["chicken-rice"],
                "demand_multiplier": "2",
                "assumption_source": "EXPLICIT_SYNTHETIC_TEST",
            },
        }
    )
    applied = apply_promotions(
        base,
        case["issued_catalogue"].menu_items,
        events=[event],
        context_evidence=issued.context_evidence,
        context_complete=True,
        as_of=issued.as_of,
        known_at=issued.known_at,
        result_reference="synthetic/promotion-issued",
    )
    assert applied.forecast
    case["issued_forecast"] = applied.forecast
    inv = case["risk"].inventory
    inv["buckets"] = tuple(
        b for b in applied.forecast.buckets if b.start >= case["contract"].as_of
    )
    inv["evidence"]["forecast"] = replace(
        inv["evidence"]["forecast"], reference=applied.forecast.reference
    )
    observed(case, 40)
    result = run(case)
    assert result.complete and result.material_change is False
    assert result.remainder is not None
    assert chicken(result).expected == 40
    assert (
        sum(
            b.expected_portions["chicken-rice"] for b in result.remainder.future_buckets
        )
        == 260
    )
    assert result.remainder.baseline_reference == "synthetic/normal"


def set_stock(case, quantity):
    inv = case["risk"].inventory
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": quantity, "initial_quantity": quantity})
        if l.ingredient_id == "chicken"
        else l
        for l in inv["opening_lots"]
    ]
    case["contract"].frozen_state["inventory"] = [
        l.model_dump(mode="json") for l in inv["opening_lots"]
    ]


def test_actual_and_future_only_independent_recipe_oracles(case):
    result = run(case)
    assert result.complete and result.remainder and result.projection
    assert sum(dict(a.portions)["chicken-rice"] for a in result.remainder.actuals) == 20
    assert (
        sum(
            b.expected_portions["chicken-rice"] for b in result.remainder.future_buckets
        )
        == 130
    )
    assert len(result.remainder.future_buckets) == 12
    assert result.projection.ingredients is not None
    assert {r.ingredient_id: r.required for r in result.projection.ingredients} == {
        "chicken": D("35.1"),
        "rice": D(39),
        "noodles": D(39),
        "eggs": D(130),
        "tofu": D("19.5"),
        "vegetables": D("35.1"),
        "oil": D("2.6"),
        "soy-sauce": D("2.6"),
    }
    assert json.loads(result.remainder.frozen_input_json) == case[
        "issued_input"
    ].model_dump(mode="json")
    case["risk"].inventory["buckets"] = case["issued_forecast"].buckets
    bad = run(case)
    assert "REMAINING_FORECAST_MISMATCH" in codes(bad) and bad.projection is None


def test_safety_risk_overrides_nonmaterial_sales(case):
    set_stock(case, D("35.1"))
    case["contract"].policy.payload.safety_stock["chicken"] = D(1)
    case["risk"].safety["chicken"] = D(1)
    result = run(case)
    assert result.complete and result.material_change is True
    assert chicken(result).material is False
    assert result.first_stockout_interval is None
    assert result.first_safety_breach_at == dt("2026-02-16T21:00:00+08:00")
    assert result.safety_breaches[-1].deficit == 1
    assert result.inventory_feasible is False


@pytest.mark.parametrize(
    "kind", ["risk", "plan", "supply", "opening_coverage", "snapshot"]
)
def test_missing_risk_cannot_certify_nonmaterial_or_keep(case, kind):
    if kind == "risk":
        case["risk"] = None
    elif kind == "plan":
        case["risk"] = replace(case["risk"], plan_evidence=None)
    elif kind == "supply":
        case["contract"].commitment_projection = None
    elif kind == "opening_coverage":
        inv = case["risk"].inventory
        inv["opening_lots"][0] = inv["opening_lots"][0].model_copy(
            update={"coverage_complete": False}
        )
        case["contract"].frozen_state["inventory"] = [
            l.model_dump(mode="json") for l in inv["opening_lots"]
        ]
    else:
        case["snapshot_evidence"] = None
    result = run(case)
    assert not result.complete and result.material_change is None
    assert result.feasible_under_observed_state is None
    assert "RESOLVE_INCOMPLETE_EVIDENCE" in result.required_follow_up


def test_no_prior_forecast_is_explicit(case):
    result = run(case, issued_forecast=None, issued_input=None)
    assert (
        not result.complete
        and result.material_change is None
        and result.remainder is None
    )
    assert "NO_ISSUED_FORECAST_OR_INPUT" in codes(result)


def daily(case, revision, total, recorded=None):
    return DailyRevision(
        id=f"day-r{revision}",
        day=date(2026, 2, 15),
        revision=revision,
        cutoff=dt("2026-02-15T21:00:00+08:00"),
        recorded_at=recorded or case["contract"].known_at,
        actor="synthetic-manager",
        counts={},
        sales={m.id: total for m in case["issued_catalogue"].menu_items},
        reconciliation=SalesReconciliation.model_validate(
            {
                "period_start": "2026-02-15T00:00:00+08:00",
                "period_end": "2026-02-15T21:00:00+08:00",
                "batch_ids": ["prior-batch"],
                "status": "RECONCILIATION_DISCREPANCY",
                "dishes": [
                    {
                        "menu_item_id": m.id,
                        "daily_total": total,
                        "batch_total": 20,
                        "difference": total - 20,
                    }
                    for m in case["issued_catalogue"].menu_items
                ],
            }
        ),
    )


def test_final_daily_revision_supersedes_never_adds_batches_or_frozen_history(case):
    c = case["contract"]
    a, b = daily(case, 1, 20), daily(case, 2, 21)
    c.frozen_state["daily_history"] = [
        frozen_daily(a),
        frozen_daily(b),
    ]
    c.frozen_state["authoritative_daily_sales"] = [
        {
            "day": b.day.isoformat(),
            "revision_id": b.id,
            "cutoff": b.cutoff.isoformat(),
            "sales": b.sales,
            "source": "DAILY_FINAL",
        }
    ]
    result = run(case)
    assert (
        result.complete
        and result.daily_history is not None
        and result.remainder is not None
    )
    assert len(result.daily_history) == 1
    day = result.daily_history[0]
    assert dict(day.portions)["chicken-rice"] == 21  # not 20+21+20 elapsed
    assert day.reconciliation_json is not None
    assert json.loads(day.reconciliation_json)["dishes"][0]["difference"] == 1
    assert (
        json.loads(result.remainder.frozen_input_json)["payload"]["history"][0][
            "portions"
        ]["chicken-rice"]
        == 150
    )
    future = daily(case, 3, 999, c.known_at + timedelta(seconds=1))
    selected = select_daily_history(
        [a, b, future],
        case["issued_catalogue"].menu_items,
        as_of=c.as_of,
        known_at=c.known_at,
    )
    assert selected == result.daily_history


def frozen_daily(revision):
    """Exact planning._snapshot daily_revisions shape, not the daily GET shape."""
    raw = revision.model_dump(mode="json")
    raw["payload"] = {
        "cutoff": raw["cutoff"],
        "counts": raw.pop("counts"),
        "sales": raw.pop("sales"),
    }
    return raw


def test_conflicting_frozen_daily_payload_is_invalid(case):
    row = frozen_daily(daily(case, 1, 20))
    row["payload"]["cutoff"] = "2026-02-15T22:00:00+08:00"
    case["contract"].frozen_state["daily_history"] = [row]
    with pytest.raises(ValueError, match="payload cutoff"):
        run(case)


def test_mismatched_authoritative_summary_incomplete(case):
    case["contract"].frozen_state["daily_history"] = [
        daily(case, 1, 20).model_dump(mode="json")
    ]
    result = run(case)
    assert not result.complete and result.daily_history is None
    assert "AUTHORITATIVE_DAILY_MISMATCH" in codes(result)


def test_immutability_determinism_and_timezone_equivalence(case):
    before = repr(case)
    first = run(case)
    assert first == run(case) and repr(case) == before
    case["contract"].as_of = case["contract"].as_of.astimezone(UTC)
    case["contract"].known_at = case["contract"].known_at.astimezone(UTC)
    for row in batches(case):
        for key in ("period_start", "period_end", "recorded_at"):
            row[key] = dt(row[key]).astimezone(UTC).isoformat()
    assert run(case) == first
    batches(case)[0]["sales"]["chicken-rice"] = 999
    assert first.remainder is not None
    assert dict(first.remainder.actuals[0].portions)["chicken-rice"] == 10


def test_context_only_reliability_changes_do_not_change_materiality(case):
    before = run(case)
    for row in case["contract"].domain.offers:
        row.offer.recent_on_time_rate = D("0.1")
    assert run(case) == before


def test_canonical_snapshot_prior_day_batches_do_not_pollute_today(case):
    before = run(case)
    row = copy.deepcopy(batches(case)[0])
    row.update(
        id="yesterday",
        batch_id="yesterday",
        period_start="2026-02-15T11:00:00+08:00",
        period_end="2026-02-15T11:30:00+08:00",
        sales={"chicken-rice": 200},
    )
    batches(case).insert(0, row)
    assert run(case) == before


def test_remaining_profile_still_requires_every_future_bucket(case):
    case["risk"].inventory["buckets"] = case["risk"].inventory["buckets"][1:]
    result = run(case)
    assert not result.complete and result.projection is None
    assert "REMAINING_FORECAST_MISMATCH" in codes(result)


@pytest.mark.parametrize("mode", ["on_time", "late", "cancelled"])
def test_frozen_partial_receipt_and_cancellation_count_once(case, mode):
    # 40 arranged = 6 received + 34 remaining. Six is counted opening stock.
    c = case["contract"]
    set_stock(case, D(6))
    inv = case["risk"].inventory
    lot = next(l for l in inv["opening_lots"] if l.ingredient_id == "chicken")
    received_at = lot.received_at
    delivery = Delivery(
        id="fixed-chicken",
        supplier_id="fresh",
        ingredient_id="chicken",
        kind="NORMAL",
        ordered_at=received_at - timedelta(hours=1),
        expected_at=dt("2026-02-16T12:30:00+08:00")
        if mode == "on_time"
        else dt("2026-02-16T17:00:00+08:00"),
        expected_quantity=D(40),
        received_quantity=D(6),
        cancelled_quantity=D(34) if mode == "cancelled" else D(0),
        outstanding_quantity=D(0) if mode == "cancelled" else D(34),
        receipts=[
            Receipt(
                id="receipt-six",
                delivery_id="fixed-chicken",
                lot_id=lot.id,
                request_id="slip-six",
                quantity=D(6),
                received_at=received_at,
                expiry_date=lot.expiry_date,
                remainder="EXPECTED",
                closing_counts={},
            )
        ],
    )
    c.frozen_state["commitments"] = [delivery.model_dump(mode="json")]
    case["contract"] = c = ProcurementContract.model_validate(
        freeze_operational_activity(c.model_dump(mode="json"), c.frozen_state)
    )
    assert c.commitment_projection
    supplied = c.commitment_projection.supplies[0]
    expiry = supplied.expiry_evidence
    inv["supplies"] = [
        ExpectedSupply(
            supplied.delivery,
            supplied.expiry_date,
            SourceEvidence(
                expiry.reference, expiry.available_at, c.captured_state_revision
            )
            if expiry
            else None,
            supplied.projected_lot_id,
        )
    ]
    inv["supply_manifest"] = c.commitment_projection.supply_manifest
    result = run(case)
    assert result.complete and result.projection and result.projection.ingredients
    row = next(r for r in result.projection.ingredients if r.ingredient_id == "chicken")
    if mode == "on_time":
        assert row.unmet == 0 and row.closing == D("4.9")
        assert result.material_change is False
    elif mode == "late":
        # Four remaining lunch buckets need 10.8: 4.8 unmet before dinner receipt.
        assert row.unmet == D("4.8") and row.closing == D("9.7")
        assert result.material_change is True and result.first_stockout_interval
        assert result.first_stockout_interval.start == dt("2026-02-16T13:00:00+08:00")
    else:
        assert row.unmet == D("29.1") and row.closing == 0
        assert result.material_change is True


@pytest.mark.parametrize(
    "change", ["manifest", "capture", "complete", "opening", "expiry_policy"]
)
def test_inconsistent_fixed_supply_or_opening_is_incomplete(case, change):
    c = case["contract"]
    if change == "manifest":
        c.frozen_state["commitments"] = [{"id": "omitted-fixed-commitment"}]
    elif change == "capture":
        c.commitment_projection.captured_state_revision = "wrong"
    elif change == "complete":
        c.commitment_projection.complete = False
    elif change == "expiry_policy":
        c.commitment_projection = c.commitment_projection.model_copy(
            update={"expiry_policy": "unknown"}
        )
    else:
        c.frozen_state["inventory"][0]["quantity"] = "0"
    if change == "expiry_policy":
        with pytest.raises(ValueError):
            run(case)
    else:
        result = run(case)
        assert (
            not result.complete
            and result.material_change is None
            and result.inventory_feasible is None
        )


def test_missing_recording_metadata_remains_incomplete(case):
    batches(case)[0].pop("recorded_at")
    result = run(case)
    assert (
        not result.complete
        and result.remainder is None
        and result.inventory_feasible is None
    )
    assert "MISSING_SALES_RECORDING_TIME" in codes(result)


def test_known_stockout_survives_missing_threshold_and_plan(case):
    set_stock(case, D(0))
    case["threshold_policy"] = None
    case["risk"] = replace(case["risk"], plan_evidence=None)
    result = run(case)
    assert result.material_change is True and not result.complete
    assert (
        result.feasible_under_observed_state is False
        and result.inventory_feasible is False
    )
    assert "MISSING_THRESHOLD_OR_EXPOSURE_POLICY" in codes(result)


def test_closed_zero_intervals_do_not_add_exposure(case):
    row = copy.deepcopy(batches(case)[0])
    row.update(
        id="closed-zero",
        batch_id="closed-zero",
        period_start="2026-02-16T00:00:00+08:00",
        period_end="2026-02-16T11:00:00+08:00",
        sales={},
    )
    batches(case).insert(0, row)
    result = run(case)
    assert result.complete and len(result.compared_intervals) == 2
    row["sales"] = {"chicken-rice": 1}
    assert "UNSUPPORTED_SALES_INTERVAL" in codes(run(case))


def test_current_active_flag_does_not_rewrite_earlier_capture(case):
    before = run(case)
    for row in batches(case):
        row["active"] = False
    assert run(case) == before


@pytest.mark.parametrize(
    "kind", ["cutoff", "identity", "duplicate", "missing_dish", "late"]
)
def test_daily_history_invalid_or_late_evidence(case, kind):
    a, b = daily(case, 1, 20), daily(case, 2, 21)
    if kind == "cutoff":
        b.cutoff += timedelta(minutes=1)
    elif kind == "identity":
        b.id = a.id
    elif kind == "duplicate":
        b.revision = 1
    elif kind == "missing_dish":
        b.sales.pop("chicken-rice")
    else:
        b.recorded_at += timedelta(minutes=1)
    if kind == "late":
        selected = select_daily_history(
            [a, b],
            case["issued_catalogue"].menu_items,
            as_of=case["contract"].as_of,
            known_at=case["contract"].known_at,
        )
        assert len(selected) == 1 and selected[0].revision == 1
    else:
        with pytest.raises(ValueError):
            select_daily_history(
                [a, b],
                case["issued_catalogue"].menu_items,
                as_of=case["contract"].as_of,
                known_at=case["contract"].known_at,
            )

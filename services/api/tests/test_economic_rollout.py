"""Canonical recipes, hand-derived 21-day stock/cost/shortage oracles."""

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from src.contingency import Addition, MultiDayInputs, ShipmentCharge
from src.coverage import CoverageResult, ProtectedWindow
from src.economic_ledger import LEDGER_POLICY, MONEY_POLICY
from src.economic_rollout import (
    FULFILMENT_POLICY,
    HORIZON_POLICY,
    AssetTerms,
    DishTerms,
    HypotheticalPurchase,
    RolloutInputs,
    rollout_economics,
    scoring_end,
)
from src.inventory_projection import (
    FEFO_POLICY,
    SOURCE_NAMES,
    ExpectedSupply,
    SourceEvidence,
)
from src.multiday_projection import CONSTRAINT_POLICY
from src.operations_schemas import Delivery, Receipt
from src.promotion_forecasting import SOURCES, ForecastVersion
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import ServicePeriod, allocate_service_buckets

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
F = json.loads((FIXTURES / "economic_rollout_v1.json").read_text())
ISSUE = datetime.fromisoformat(F["issue_time"])
END = datetime.fromisoformat(F["horizon_end"])
EV = SourceEvidence(F["fixture_id"], ISSUE, "synthetic-economics-1")


@pytest.fixture
def inputs():
    catalogue = json.loads((FIXTURES / F["catalogue_fixture"]).read_text())
    ingredients = [Ingredient.model_validate(r) for r in catalogue["ingredients"]]
    menu = [MenuItem.model_validate(r) for r in catalogue["menu_items"]]
    recipes = [RecipeItem.model_validate(r) for r in catalogue["recipes"]]
    windows = tuple(
        ProtectedWindow(
            i.id,
            ISSUE,
            ISSUE + timedelta(days=F["protected_days"][i.id]),
            ISSUE.date(),
            (ISSUE + timedelta(days=F["protected_days"][i.id])).date(),
            "synthetic-next-" + i.id,
        )
        for i in ingredients
    )
    coverage = CoverageResult(
        ISSUE,
        ISSUE,
        "synthetic-economics-1",
        tuple(i.id for i in ingredients),
        True,
        windows,
        max(w.end for w in windows),
        (),
        (),
        (("catalogue", EV),),
        21,
        "FIXTURE_OPEN_AT_DECISION_PROTECT_NEXT_V1",
        "ARRIVAL_SHELF_LIFE_INCLUSIVE_V1",
    )
    forecasts = []
    prices = {}
    for offset in range(21):
        day = (ISSUE + timedelta(days=offset)).date()
        start = datetime.combine(day, time(11), ISSUE.tzinfo)
        profile = (ServicePeriod(start, start + timedelta(minutes=30), D(1)),)
        buckets = allocate_service_buckets(
            {d: D(q) for d, q in F["daily_portions"].items()},
            menu,
            target_date=day,
            profile=profile,
        )
        forecasts.append(
            ForecastVersion(
                "synthetic-forecast:" + str(day),
                ISSUE,
                ISSUE,
                day,
                profile,
                tuple((s, EV) for s in sorted(SOURCES)),
                buckets,
                "EXCLUDED",
                "synthetic-forecast:" + str(day),
            )
        )
        for dish in menu:
            prices[start, dish.id] = DishTerms(
                D(F["effective_net_price"]), D(F["noningredient_variable_cost"]), EV
            )
    lots = [
        EstimatedInventoryLot(
            id=i.id,
            ingredient_id=i.id,
            unit=i.unit,
            received_at=ISSUE - timedelta(days=1),
            counted_at=ISSUE,
            expiry_date=date.fromisoformat(
                F["chicken_expiry"] if i.id == "chicken" else F["other_expiry"]
            ),
            initial_quantity=D(F["opening"][i.id]),
            quantity=D(F["opening"][i.id]),
            as_of=ISSUE,
            coverage_start=ISSUE,
            coverage_complete=True,
            status="ACTIVE",
        )
        for i in ingredients
    ]
    inv: MultiDayInputs = {
        "coverage": coverage,
        "forecasts": forecasts,
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "opening_lots": lots,
        "supplies": [],
        "opening_manifest": {i.id: [i.id] for i in ingredients},
        "supply_manifest": [],
        "recipe_manifest": [(r.menu_item_id, r.ingredient_id) for r in recipes],
        "evidence": {s: EV for s in SOURCE_NAMES | {"constraints"}},
        "safety": {i.id: D(0) for i in ingredients},
        "storage": {i.id: D(1000) for i in ingredients},
        "assessment_end": {i.id: END for i in ingredients},
        "constraint_policy": CONSTRAINT_POLICY,
        "fefo_policy": FEFO_POLICY,
    }
    return RolloutInputs(
        inv,
        END,
        {
            "opening:" + i.id: AssetTerms(
                D(2) if i.id == "chicken" else D(0),
                D(1) if i.id == "chicken" else D(0),
                EV,
            )
            for i in ingredients
        },
        prices,
        (),
        (),
        {
            s: EV
            for s in (
                "assets",
                "service",
                "shipments",
                "valuation",
                "policy",
                "catalogue",
            )
        },
        LEDGER_POLICY,
        "ZERO_TERMINAL_V1",
        MONEY_POLICY,
        FULFILMENT_POLICY,
        HORIZON_POLICY,
        100000,
    )


def buy(inputs, *, arrival=None, quantity="30", expiry=date(2026, 3, 10)):
    arrival = arrival or ISSUE + timedelta(days=1, hours=10)
    addition = Addition(
        "chicken-topup",
        "chicken-offer",
        "fresh",
        "chicken",
        "shipment-1",
        D(quantity),
        "kg",
        ISSUE,
        arrival,
        ISSUE,
        expiry,
        "NORMAL",
    )
    return replace(
        inputs,
        purchases=(HypotheticalPurchase(addition, D(2), D(1), "NEW_PURCHASE", EV),),
        shipments=(ShipmentCharge("shipment-1", "fresh", arrival, D(0), D(0)),),
    )


def result(inputs):
    actual = rollout_economics(inputs)
    assert actual.complete, actual.findings
    assert actual.ledger is not None and actual.ledger.components is not None
    assert actual.assets is not None and actual.service is not None
    return actual


def test_21_days_zero_other_dishes_preserves_canonical_recipe_and_unmet_cost(inputs):
    actual = result(inputs)
    assert actual.service is not None and actual.assets is not None
    assert actual.ledger is not None and actual.ledger.components is not None
    assert len(actual.service) == 105
    assert sum(s.required for s in actual.service) == 210
    assert sum(s.served for s in actual.service) == 10
    chicken = next(a for a in actual.assets if a.ingredient_id == "chicken")
    assert chicken.allocated == D("1.5") and chicken.expired == D("1.5")
    assert actual.ledger.components.primary_sgd == D("1607.50")
    assert {b.ingredient_id for b in actual.breaches if b.kind == "SHORTAGE"} == {
        "chicken"
    }
    # Rice/soy are not consumed for the 200 portions that lack chicken.
    assert next(a for a in actual.assets if a.ingredient_id == "rice").allocated == 1
    assert next(
        a for a in actual.assets if a.ingredient_id == "soy-sauce"
    ).allocated == D("0.1")


def test_timely_purchase_covers_21_days_without_buying_all_21_days_twice(inputs):
    actual = result(buy(inputs))
    assert (
        actual.service is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    assert sum(s.served for s in actual.service) == 210
    assert actual.ledger.components.acquisition == 60
    assert actual.ledger.components.primary_sgd == D("67.50")
    assert not [b for b in actual.breaches if b.kind == "SHORTAGE"]
    assert inputs.inventory["opening_lots"][0].quantity == 3


def test_bucket_end_arrival_never_repairs_earlier_shortage(inputs):
    actual = result(
        buy(inputs, arrival=ISSUE + timedelta(days=1, hours=11, minutes=30))
    )
    assert (
        actual.service is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    assert sum(s.served for s in actual.service) == 200
    assert actual.ledger.components.primary_sgd == D("147.50")
    assert actual.ledger.components.book_terminal_total == D("144.50")
    assert actual.ledger.components.terminal_usable_book == 3
    first = next(
        b
        for b in actual.breaches
        if b.kind == "SHORTAGE" and b.ingredient_id == "chicken"
    )
    assert first.start == ISSUE + timedelta(days=1, hours=11)


def test_bucket_start_arrival_is_usable_but_mid_bucket_is_incomplete(inputs):
    at_start = result(buy(inputs, arrival=ISSUE + timedelta(days=1, hours=11)))
    assert at_start.service is not None
    assert sum(s.served for s in at_start.service) == 210
    middle = rollout_economics(
        buy(inputs, arrival=ISSUE + timedelta(days=1, hours=11, minutes=15))
    )
    assert not middle.complete and middle.ledger is None
    assert "UNSUPPORTED_MID_BUCKET_ARRIVAL" in {f.code for f in middle.findings}


def test_fixed_commitment_is_not_new_purchase(inputs):
    arrival = ISSUE + timedelta(days=1, hours=10)
    d = Delivery(
        id="fixed",
        supplier_id="fresh",
        ingredient_id="chicken",
        kind="NORMAL",
        expected_quantity=D("30"),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D("30"),
        ordered_at=ISSUE - timedelta(days=1),
        expected_at=arrival,
        receipts=[],
    )
    inv = inputs.inventory.copy()
    inv["supplies"] = [ExpectedSupply(d, date(2026, 3, 8), EV, "fixed-projected-lot")]
    inv["supply_manifest"] = ["fixed"]
    actual = result(
        replace(
            inputs,
            inventory=inv,
            asset_terms={
                **inputs.asset_terms,
                "supply:fixed": AssetTerms(D(2), D(1), EV),
            },
        )
    )
    assert actual.ledger is not None and actual.ledger.components is not None
    assert actual.ledger.components.acquisition == 0
    assert actual.ledger.components.opening_assets == 66
    assert actual.ledger.components.primary_sgd == D("67.50")
    assert d.outstanding_quantity == D("30")


def test_terminal_boundary_expiry_is_not_usable_credit(inputs):
    actual = result(buy(inputs, quantity="31.5", expiry=date(2026, 3, 8)))
    assert (
        actual.assets is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    purchased = next(a for a in actual.assets if a.origin == "NEW_PURCHASE")
    assert purchased.expired == D("1.5") and purchased.ending_usable == 0
    assert actual.ledger.components.primary_sgd == D(
        "72.00"
    )  # opening6 + purchase63 + disposal3


@pytest.mark.parametrize(
    "change,code",
    [
        ({"asset_terms": {}}, "MISSING_ASSET_VALUATION"),
        ({"dish_terms": {}}, "MISSING_DISH_ECONOMICS"),
        ({"fulfilment_policy": None}, "UNRESOLVED_FULFILMENT_POLICY"),
        ({"horizon_end": END - timedelta(days=1)}, "UNSUPPORTED_ECONOMIC_HORIZON"),
    ],
)
def test_unknown_is_not_cash_only_or_zero_demand(inputs, change, code):
    actual = rollout_economics(replace(inputs, **change))
    assert not actual.complete and actual.ledger is None and actual.service is None
    assert code in {f.code for f in actual.findings}


def test_missing_day_retains_projection_evidence_but_has_no_economic_total(inputs):
    inv = inputs.inventory.copy()
    inv["forecasts"] = inv["forecasts"][:-1]
    prices = {
        k: v for k, v in inputs.dish_terms.items() if k[0].date() != date(2026, 3, 8)
    }
    actual = rollout_economics(replace(inputs, inventory=inv, dish_terms=prices))
    assert not actual.complete and actual.ledger is None
    assert actual.fixed_projection is not None
    assert any(b.kind == "SHORTAGE" for b in actual.fixed_projection.breaches)


def test_work_limit_is_incomplete_and_does_not_return_a_partial_score(inputs):
    actual = rollout_economics(replace(inputs, work_limit=1))
    assert not actual.complete and actual.ledger is None
    assert actual.findings[0].code == "SEARCH_LIMIT_REACHED"
    assert actual.work_used == 1


def test_calendar_end_counts_issue_date_and_decimal_context_does_not_change_result(
    inputs,
):
    assert scoring_end(ISSUE + timedelta(hours=10), has_remaining_service=True) == END
    assert scoring_end(
        ISSUE + timedelta(hours=22), has_remaining_service=False
    ) == END + timedelta(days=1)
    expected = result(inputs)
    with localcontext() as ctx:
        ctx.prec = 3
        actual = result(inputs)
    assert actual == expected


def test_fractional_fulfilment_requires_all_recipe_ingredients(inputs):
    inv = inputs.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": D("0.075")}) if l.id == "chicken" else l
        for l in inv["opening_lots"]
    ]
    actual = result(replace(inputs, inventory=inv))
    assert actual.service is not None and actual.assets is not None
    assert sum(s.served for s in actual.service) == D("0.5")
    assert next(a for a in actual.assets if a.ingredient_id == "rice").allocated == D(
        "0.05"
    )
    assert next(
        a for a in actual.assets if a.ingredient_id == "soy-sauce"
    ).allocated == D("0.005")
    assert not actual.warnings


def test_recurring_served_fraction_rounds_down_with_explicit_residual(inputs):
    inv = inputs.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": D("0.1")}) if l.id == "chicken" else l
        for l in inv["opening_lots"]
    ]
    actual = result(replace(inputs, inventory=inv))
    assert actual.service is not None and actual.assets is not None
    first = next(s for s in actual.service if s.menu_item_id == "chicken-rice")
    assert first.served == D("0.6666666666666666666666666666")
    chicken = next(a for a in actual.assets if a.ingredient_id == "chicken")
    assert chicken.allocated == D("0.09999999999999999999999999999")
    assert chicken.expired == D("0.00000000000000000000000000001")
    assert any(w.code == "FRACTIONAL_REPRESENTATION_RESIDUAL" for w in actual.warnings)


def test_fefo_preserves_longer_lived_stock_and_order_is_immutable(inputs):
    inv = inputs.inventory.copy()
    chicken = next(l for l in inv["opening_lots"] if l.id == "chicken")
    late = chicken.model_copy(
        update={
            "id": "long-lived",
            "expiry_date": date(2026, 3, 10),
            "quantity": D(3),
            "initial_quantity": D(3),
        }
    )
    inv["opening_lots"] = [late, *inv["opening_lots"]]
    inv["opening_manifest"] = {
        **inv["opening_manifest"],
        "chicken": ["long-lived", "chicken"],
    }
    terms = {**inputs.asset_terms, "opening:long-lived": AssetTerms(D(2), D(1), EV)}
    actual = result(replace(inputs, inventory=inv, asset_terms=terms))
    assert actual.assets is not None and actual.service is not None
    short = next(a for a in actual.assets if a.reference == "opening:chicken")
    long = next(a for a in actual.assets if a.reference == "opening:long-lived")
    assert short.allocated == D("1.5") and short.expired == D("1.5")
    assert long.allocated == 3 and long.expired == 0
    assert sum(s.served for s in actual.service) == 30
    reversed_inv = inv.copy()
    reversed_inv["opening_lots"] = list(reversed(inv["opening_lots"]))
    assert result(replace(inputs, inventory=reversed_inv, asset_terms=terms)) == actual
    assert late.quantity == 3 and chicken.quantity == 3


def test_partial_receipts_and_cancellation_conserve_only_remaining_fixed_supply(inputs):
    inv = inputs.inventory.copy()
    received_at = ISSUE - timedelta(days=1)
    chicken = next(l for l in inv["opening_lots"] if l.id == "chicken")
    inv["opening_lots"] = [
        l.model_copy(update={"initial_quantity": D(6)}) if l.id == "chicken" else l
        for l in inv["opening_lots"]
    ]
    receipt = Receipt(
        id="receipt-6",
        delivery_id="original-37",
        lot_id="chicken",
        request_id="fixture-receipt",
        quantity=D(6),
        received_at=received_at,
        expiry_date=chicken.expiry_date,
        remainder="EXPECTED",
    )
    d = Delivery(
        id="original-37",
        supplier_id="fresh",
        ingredient_id="chicken",
        kind="NORMAL",
        expected_quantity=D(37),
        received_quantity=D(6),
        cancelled_quantity=D(1),
        outstanding_quantity=D(30),
        ordered_at=received_at - timedelta(hours=1),
        expected_at=ISSUE + timedelta(days=1, hours=10),
        receipts=[receipt],
    )
    inv["supplies"] = [
        ExpectedSupply(d, date(2026, 3, 10), EV, "projected-remaining-30")
    ]
    inv["supply_manifest"] = [d.id]
    terms = {**inputs.asset_terms, "supply:" + d.id: AssetTerms(D(2), D(1), EV)}
    actual = result(replace(inputs, inventory=inv, asset_terms=terms))
    assert (
        actual.assets is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    assert sum(a.quantity for a in actual.assets if a.ingredient_id == "chicken") == 33
    assert actual.ledger.components.opening_assets == 66
    assert actual.ledger.components.acquisition == 0
    assert actual.ledger.components.primary_sgd == D("67.50")
    assert d.received_quantity == 6 and d.cancelled_quantity == 1


def test_documented_fixed_incoming_after_horizon_is_terminal_not_consumption(inputs):
    inv = inputs.inventory.copy()
    d = Delivery(
        id="after-end",
        supplier_id="fresh",
        ingredient_id="chicken",
        kind="NORMAL",
        expected_quantity=D(4),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D(4),
        ordered_at=ISSUE,
        expected_at=END + timedelta(days=1),
        receipts=[],
    )
    inv["supplies"] = [ExpectedSupply(d, date(2026, 3, 12), EV, "projected-after-end")]
    inv["supply_manifest"] = [d.id]
    terms = {**inputs.asset_terms, "supply:" + d.id: AssetTerms(D(2), D(1), EV)}
    actual = result(replace(inputs, inventory=inv, asset_terms=terms))
    assert (
        actual.ledger is not None
        and actual.ledger.components is not None
        and actual.assets is not None
    )
    assert actual.fixed_projection is not None and not actual.fixed_projection.complete
    assert any(
        w.code == "DELAYED_COMMITMENT_BEYOND_ASSESSMENT" for w in actual.warnings
    )
    incoming = next(a for a in actual.assets if a.reference == "supply:after-end")
    assert incoming.ending_incoming == 4 and incoming.allocated == 0
    assert actual.ledger.components.zero_terminal_total == D("1615.5")
    assert actual.ledger.components.book_terminal_total == D("1607.5")


def test_storage_and_safety_breaches_remain_distinct_from_calculation_completion(
    inputs,
):
    inv = inputs.inventory.copy()
    inv["storage"] = {**inv["storage"], "chicken": D(2)}
    inv["safety"] = {**inv["safety"], "chicken": D(2)}
    actual = result(replace(inputs, inventory=inv))
    assert any(b.kind == "STORAGE" and b.start == ISSUE for b in actual.breaches)
    assert any(b.kind == "SAFETY" and b.scope == "PROTECTED" for b in actual.breaches)
    assert any(
        b.kind == "SHORTAGE" and b.scope == "ASSESSMENT" for b in actual.breaches
    )


def test_late_economic_evidence_cannot_certify_economics(inputs):
    future = buy(inputs)
    late = SourceEvidence(
        "unknown-at-issue", ISSUE + timedelta(hours=1), EV.captured_revision
    )
    invalid = replace(future, purchases=(replace(future.purchases[0], evidence=late),))
    actual = rollout_economics(invalid)
    assert not actual.complete and actual.ledger is None
    assert "NOT_YET_AVAILABLE" in {f.code for f in actual.findings}


def test_shared_shipment_is_once_and_unknown_shipment_not_silently_free(inputs):
    p = buy(inputs)
    first = p.purchases[0]
    a = replace(first.addition, opportunity_id="split-other", quantity=D(15))
    p = replace(
        p,
        purchases=(
            replace(first, addition=replace(first.addition, quantity=D(15))),
            replace(first, addition=a),
        ),
        shipments=(replace(p.shipments[0], delivery=D(3), emergency=D(4)),),
    )
    actual = result(p)
    assert actual.ledger is not None and actual.ledger.components is not None
    assert actual.ledger.components.primary_sgd == D("74.50")
    missing = rollout_economics(replace(p, shipments=()))
    assert not missing.complete and missing.ledger is None
    assert "SHIPMENT_COVERAGE_MISMATCH" in {f.code for f in missing.findings}


def test_after_closing_origin_counts_21_future_service_dates(inputs):
    issue = ISSUE + timedelta(hours=22)
    end = END + timedelta(days=1)
    inv = inputs.inventory.copy()
    c = inv["coverage"]
    inv["coverage"] = replace(
        c,
        issue_time=issue,
        known_at=issue,
        windows=tuple(replace(w, start=issue) for w in c.windows),
        max_horizon_days=22,
    )
    inv["assessment_end"] = {i.id: end for i in inv["ingredients"]}
    inv["opening_lots"] = [
        l.model_copy(update={"as_of": issue}) for l in inv["opening_lots"]
    ]
    forecasts = [
        replace(
            f,
            as_of=issue,
            known_at=issue,
            buckets=tuple(b for b in f.buckets if b.start >= issue),
        )
        for f in inv["forecasts"]
    ]
    last = forecasts[-1]
    day = date(2026, 3, 9)
    start = datetime.combine(day, time(11), ISSUE.tzinfo)
    profile = (ServicePeriod(start, start + timedelta(minutes=30), D(1)),)
    extra = replace(
        last,
        reference="synthetic-last-day",
        base_reference="synthetic-last-day",
        target_date=day,
        profile=profile,
        buckets=allocate_service_buckets(
            {d: D(q) for d, q in F["daily_portions"].items()},
            inv["menu_items"],
            target_date=day,
            profile=profile,
        ),
    )
    inv["forecasts"] = [*forecasts, extra]
    prices = {k: v for k, v in inputs.dish_terms.items() if k[0] >= issue}
    prices.update(
        {(start, d.id): DishTerms(D(10), D(2), EV) for d in inv["menu_items"]}
    )
    actual = result(replace(inputs, inventory=inv, horizon_end=end, dish_terms=prices))
    assert (
        actual.service is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    assert len(actual.service) == 105
    assert sum(s.required for s in actual.service) == 210
    assert sum(s.served for s in actual.service) == 0
    assert actual.ledger.components.primary_sgd == D("1689.00")


def test_zero_demand_service_still_counts_issue_day(inputs):
    inv = inputs.inventory.copy()
    forecasts = []
    for f in inv["forecasts"]:
        buckets = allocate_service_buckets(
            {d.id: D(0) for d in inv["menu_items"]},
            inv["menu_items"],
            target_date=f.target_date,
            profile=f.profile,
        )
        forecasts.append(replace(f, buckets=buckets))
    inv["forecasts"] = forecasts
    actual = result(replace(inputs, inventory=inv))
    assert (
        actual.service is not None
        and actual.ledger is not None
        and actual.ledger.components is not None
    )
    assert sum(s.required for s in actual.service) == 0
    assert actual.context.horizon_end == END
    assert (
        actual.ledger.components.primary_sgd == 9
    )  # opening6 + disposal3; no stockout cost

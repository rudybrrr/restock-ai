"""Independent stock-conservation and timing oracles, using current recipes."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.inventory_projection import ExpectedSupply, SourceEvidence, project_inventory
from src.operations_schemas import Delivery, Receipt
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal


def dt(value):
    return datetime.fromisoformat(value)


@pytest.fixture
def inputs():
    f = json.loads((FIXTURES / "inventory_projection_v1.json").read_text())
    cat = json.loads((FIXTURES / f["catalogue_fixture"]).read_text())
    ingredients = [Ingredient.model_validate(r) for r in cat["ingredients"]]
    as_of = dt(f["as_of"])
    lots = [
        EstimatedInventoryLot(
            id=i.id + "-opening",
            ingredient_id=i.id,
            unit=i.unit,
            received_at=dt(f["opening_received_at"]),
            expiry_date=date.fromisoformat(f["opening_expiry"]),
            initial_quantity=D(f["opening_quantities"][i.id]),
            quantity=D(f["opening_quantities"][i.id]),
            counted_at=as_of,
            as_of=as_of,
            coverage_start=as_of,
            coverage_complete=True,
            status="ACTIVE",
            unallocated_consumption=D(0),
        )
        for i in ingredients
    ]
    evidence = SourceEvidence(
        f["fixture_id"], dt(f["available_at"]), f["captured_revision"]
    )
    return {
        "opening_lots": lots,
        "buckets": [
            ProjectedDemandBucket(
                dt(b["start"]),
                dt(b["end"]),
                {d: D(q) for d, q in b["portions"].items()},
            )
            for b in f["buckets"]
        ],
        "menu_items": [MenuItem.model_validate(r) for r in cat["menu_items"]],
        "ingredients": ingredients,
        "recipes": [RecipeItem.model_validate(r) for r in cat["recipes"]],
        "supplies": f["outstanding_supply"],
        "as_of": as_of,
        "target_date": date.fromisoformat(f["target_date"]),
        "horizon_end": dt(f["horizon_end"]),
        "known_at": dt(f["known_at"]),
        "captured_revision": f["captured_revision"],
        "opening_manifest": {i.id: [i.id + "-opening"] for i in ingredients},
        "supply_manifest": [],
        "recipe_manifest": [
            (r["menu_item_id"], r["ingredient_id"]) for r in cat["recipes"]
        ],
        "service_profile": [
            ServicePeriod(dt(p["start"]), dt(p["end"]), D(p["weight"]))
            for p in f["profile"]
        ],
        "evidence": {
            name: evidence
            for name in (
                "snapshot",
                "opening",
                "supply",
                "catalogue",
                "recipe",
                "forecast",
                "profile",
            )
        },
        "fixture_fefo": f["fixture_fefo"],
    }


def vegetable(rows):
    return next(r for r in rows if r.ingredient_id == "vegetables")


def change_lot(inputs, **changes):
    inputs["opening_lots"] = [
        l.model_copy(update=changes) if l.ingredient_id == "vegetables" else l
        for l in inputs["opening_lots"]
    ]


def add_supply(
    inputs, arrival="2026-02-16T11:30:00+08:00", quantity="0.500", **changes
):
    delivery = Delivery(
        id="fixed-vegetables",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(quantity),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D(quantity),
        ordered_at=inputs["as_of"] - timedelta(hours=1),
        expected_at=dt(arrival),
        receipts=[],
    ).model_copy(update=changes)
    inputs["supplies"] = [
        ExpectedSupply(delivery, date(2026, 2, 18), inputs["evidence"]["supply"])
    ]
    inputs["supply_manifest"] = [delivery.id]
    return delivery


def assert_conserved(result):
    assert result.complete and result.provenance == "PROJECTED"
    for rows in [result.lots, *(b.lots for b in result.buckets)]:
        for r in rows:
            assert Fraction(r.opening) + Fraction(r.admitted) == Fraction(
                r.allocated
            ) + Fraction(r.expired) + Fraction(r.closing)
            assert all(
                q >= 0
                for q in (r.opening, r.admitted, r.allocated, r.expired, r.closing)
            )
    for rows in [result.ingredients, *(b.ingredients for b in result.buckets)]:
        for r in rows:
            assert Fraction(r.opening) + Fraction(r.admitted) == Fraction(
                r.allocated
            ) + Fraction(r.expired) + Fraction(r.closing)
            assert Fraction(r.required) == Fraction(r.allocated) + Fraction(r.unmet)


def assert_incomplete(result, code):
    assert result.complete is False
    assert code in {f.code for f in result.findings}
    assert all(
        getattr(result, field) is None
        for field in ("buckets", "lots", "ingredients", "expiries", "first_shortages")
    )


def test_two_bucket_independent_oracle(inputs):
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert [vegetable(b.ingredients).required for b in result.buckets] == [
        D("1.5"),
        D("1"),
    ]
    assert [vegetable(b.ingredients).closing for b in result.buckets] == [
        D(".5"),
        D("0"),
    ]
    assert [vegetable(b.ingredients).unmet for b in result.buckets] == [D("0"), D(".5")]
    assert [(s.ingredient_id, s.start, s.end) for s in result.first_shortages] == [
        ("vegetables", dt("2026-02-16T11:30:00+08:00"), dt("2026-02-16T12:00:00+08:00"))
    ]
    assert len(result.ingredients) == 8
    assert vegetable(result.ingredients).allocated == D(2)


@pytest.mark.parametrize(
    ("arrival", "unmet", "closing"),
    [
        ("2026-02-16T11:00:00+08:00", "0", "0"),
        ("2026-02-16T11:30:00+08:00", "0", "0"),
        ("2026-02-16T12:00:00+08:00", ".5", ".5"),
        ("2026-02-16T17:00:00+08:00", ".5", ".5"),
        ("2026-02-17T00:00:00+08:00", ".5", ".5"),
        ("2026-02-17T00:30:00+08:00", ".5", "0"),
    ],
)
def test_arrival_boundaries_and_no_retroactive_fulfilment(
    inputs, arrival, unmet, closing
):
    add_supply(inputs, arrival)
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    row = vegetable(result.ingredients)
    assert row.unmet == D(unmet) and row.closing == D(closing)
    assert bool(result.first_shortages) == bool(D(unmet))


@pytest.mark.parametrize(
    "arrival", ["2026-02-16T11:15:00+08:00", "2026-02-16T11:45:00+08:00"]
)
def test_mid_bucket_arrival_incomplete(inputs, arrival):
    add_supply(inputs, arrival)
    assert_incomplete(project_inventory(**inputs), "UNSUPPORTED_MID_BUCKET_ARRIVAL")


def test_overdue_unreceived_supply_is_not_stock(inputs):
    add_supply(inputs, "2026-02-16T09:30:00+08:00")
    assert_incomplete(project_inventory(**inputs), "OVERDUE_EXPECTED_SUPPLY")


@pytest.mark.parametrize(
    "arrival", ["2026-02-16T11:15:00+08:00", "2026-02-16T09:30:00+08:00"]
)
def test_cancelled_zero_remainder_has_no_arrival_or_expiry_effect(inputs, arrival):
    add_supply(
        inputs,
        arrival,
        expected_quantity=D(".5"),
        cancelled_quantity=D(".5"),
        outstanding_quantity=D(0),
    )
    inputs["supplies"] = [
        replace(inputs["supplies"][0], expiry_date=None, expiry_evidence=None)
    ]
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert vegetable(result.ingredients).unmet == D(".5")


def test_expiry_at_horizon_and_before_first_service(inputs):
    change_lot(
        inputs, quantity=D(3), initial_quantity=D(3), expiry_date=date(2026, 2, 16)
    )
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert vegetable(result.ingredients).expired == D(".5")
    assert vegetable(result.ingredients).closing == 0
    assert result.expiries[0].at == inputs["horizon_end"]
    assert vegetable(result.buckets[-1].ingredients).closing == D(".5")
    # A previous-day opening remains usable only until midnight, before service.
    before = dt("2026-02-15T22:00:00+08:00")
    inputs["as_of"] = before
    inputs["opening_lots"] = [
        l.model_copy(
            update={"as_of": before, "counted_at": before, "coverage_start": before}
        )
        for l in inputs["opening_lots"]
    ]
    change_lot(inputs, expiry_date=date(2026, 2, 15))
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert vegetable(result.ingredients).expired == D(3)
    assert vegetable(result.ingredients).unmet == D("2.5")
    assert result.expiries[0].at == dt("2026-02-16T00:00:00+08:00")


def test_expected_supply_expires_in_gap_without_being_consumed(inputs):
    # Opening previous evening; expected stock arrives and expires before service.
    before = dt("2026-02-15T21:00:00+08:00")
    inputs["as_of"] = before
    inputs["opening_lots"] = [
        l.model_copy(
            update={"as_of": before, "counted_at": before, "coverage_start": before}
        )
        for l in inputs["opening_lots"]
    ]
    add_supply(inputs, "2026-02-15T22:00:00+08:00")
    inputs["supplies"] = [replace(inputs["supplies"][0], expiry_date=date(2026, 2, 15))]
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert vegetable(result.ingredients).expired == D(".5")
    assert vegetable(result.ingredients).unmet == D(".5")


@pytest.mark.parametrize(
    ("tie", "policy", "early_id"),
    [
        (False, "EXPIRY_ID", "z-early"),
        (False, "EXPIRY_RECEIVED_ID", "z-early"),
        (True, "EXPIRY_RECEIVED_ID", "z-early"),
        (True, "EXPIRY_ID", "a-later"),
    ],
)
def test_fefo_and_explicit_fixture_ties_without_shared_parity(
    inputs, tie, policy, early_id
):
    old = next(l for l in inputs["opening_lots"] if l.ingredient_id == "vegetables")
    early = old.model_copy(
        update={
            "id": "z-early",
            "quantity": D(1),
            "initial_quantity": D(1),
            "expiry_date": date(2026, 2, 17),
        }
    )
    later = old.model_copy(
        update={
            "id": "a-later",
            "quantity": D(1),
            "initial_quantity": D(1),
            "received_at": old.received_at + timedelta(hours=1),
            "expiry_date": date(2026, 2, 17 if tie else 18),
        }
    )
    inputs["opening_lots"] = [l for l in inputs["opening_lots"] if l != old] + [
        later,
        early,
    ]
    inputs["opening_manifest"]["vegetables"] = ["z-early", "a-later"]
    inputs["fixture_fefo"] = policy
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    first = {r.key: r for r in result.buckets[0].lots}
    assert first["opening:" + early_id].allocated == D(1)
    assert sum(
        r.allocated for r in first.values() if r.ingredient_id == "vegetables"
    ) == D("1.5")


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_receipt_opening_and_remaining_supply_counted_once(inputs, cancelled):
    receipt_at = inputs["as_of"] - timedelta(hours=1)
    change_lot(inputs, quantity=D(6), initial_quantity=D(6), received_at=receipt_at)
    receipt = Receipt(
        id="receipt-6",
        delivery_id="fixed-vegetables",
        lot_id="vegetables-opening",
        request_id="slip-6",
        quantity=D(6),
        received_at=receipt_at,
        expiry_date=date(2026, 2, 18),
        remainder="EXPECTED",
        closing_counts={},
    )
    add_supply(
        inputs,
        quantity="10",
        received_quantity=D(6),
        receipts=[receipt],
        cancelled_quantity=D(4 if cancelled else 0),
        outstanding_quantity=D(0 if cancelled else 4),
    )
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    row = vegetable(result.ingredients)
    assert row.opening == D(6)
    assert row.admitted == D(0 if cancelled else 4)
    assert row.closing == D("3.5" if cancelled else "7.5")


def test_zero_opening_and_fractional_zero_demand(inputs):
    inputs["opening_lots"] = []
    inputs["opening_manifest"] = {i.id: [] for i in inputs["ingredients"]}
    inputs["buckets"] = [
        replace(b, expected_portions={d.id: D(0) for d in inputs["menu_items"]})
        for b in inputs["buckets"]
    ]
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert result.first_shortages == ()
    assert all(r.closing == r.required == 0 for r in result.ingredients)
    values = dict(inputs["buckets"][0].expected_portions)
    values["fried-rice"] = D(".000000000000000001")
    inputs["buckets"][0] = replace(inputs["buckets"][0], expected_portions=values)
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    eggs = next(r for r in result.ingredients if r.ingredient_id == "eggs")
    assert eggs.required == eggs.unmet == D(".000000000000000001")
    assert vegetable(result.ingredients).unmet == D(".00000000000000000005")


def test_full_baseline_profile_recipe_composition(inputs):
    f = json.loads((FIXTURES / "seasonal_baseline_v3.json").read_text())
    history = [
        DailySalesObservation(
            date.fromisoformat(r["service_date"]),
            dt(r["available_at"]),
            r["revision"],
            r["portions"],
            r["promotion"],
            r["censored"],
        )
        for r in f["history"]
    ]
    baseline = seasonal_baseline(
        history,
        inputs["menu_items"],
        issue_time=dt(f["issue_time"]),
        target_date=inputs["target_date"],
    )
    daily = {}
    for dish, row in baseline.items():
        assert row.expected_portions is not None
        daily[dish] = row.expected_portions
    profile = json.loads((FIXTURES / "service_profile_v2.json").read_text())
    inputs["service_profile"] = [
        ServicePeriod(dt(p["start"]), dt(p["end"]), D(p["weight"]))
        for p in profile["periods"]
    ]
    inputs["buckets"] = allocate_service_buckets(
        daily,
        inputs["menu_items"],
        target_date=inputs["target_date"],
        profile=inputs["service_profile"],
    )
    change_lot(inputs, quantity=D(1000), initial_quantity=D(1000))
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None and result.ingredients is not None
    assert result.first_shortages is not None and result.expiries is not None
    assert {r.ingredient_id: r.required for r in result.ingredients} == {
        "chicken": D("24.600"),
        "rice": D("20.000"),
        "noodles": D("18.000"),
        "eggs": D(60),
        "tofu": D("6.000"),
        "vegetables": D("11.800"),
        "oil": D("1.000"),
        "soy-sauce": D("1.800"),
    }
    chicken = next(
        r for r in result.buckets[0].ingredients if r.ingredient_id == "chicken"
    )
    assert chicken.required == D("1.640000130")  # 6.666667*.150 + 5.333334*.120
    assert result.first_shortages == ()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("missing_opening_manifest", "OPENING_COVERAGE_MISMATCH"),
        ("missing_lot", "OPENING_COVERAGE_MISMATCH"),
        ("missing_bucket", "DEMAND_COVERAGE_MISMATCH"),
        ("recipe_line", "RECIPE_MANIFEST_MISMATCH"),
        ("missing_evidence", "MISSING_EVIDENCE"),
        ("missing_availability", "MISSING_AVAILABILITY"),
        ("later_evidence", "NOT_YET_AVAILABLE"),
        ("wrong_revision", "REVISION_MISMATCH"),
        ("missing_coverage", "MISSING_OBSERVED_COVERAGE"),
        ("deficit", "HISTORICAL_UNALLOCATED_CONSUMPTION"),
        ("wrong_as_of", "OPENING_AS_OF_MISMATCH"),
        ("inside_opening", "UNSUPPORTED_OPENING_CUTOFF"),
        ("missing_supply", "SUPPLY_COVERAGE_MISMATCH"),
        ("missing_expiry", "MISSING_EXPECTED_EXPIRY"),
        ("missing_expiry_evidence", "MISSING_EVIDENCE"),
    ],
)
def test_missing_or_inconsistent_evidence_is_not_a_complete_projection(
    inputs, change, code
):
    if change == "missing_opening_manifest":
        del inputs["opening_manifest"]["vegetables"]
    elif change == "missing_lot":
        inputs["opening_lots"].pop()
    elif change == "missing_bucket":
        inputs["buckets"].pop()
    elif change == "recipe_line":
        inputs["recipes"].pop()
    elif change == "missing_evidence":
        del inputs["evidence"]["recipe"]
    elif change in ("missing_availability", "later_evidence", "wrong_revision"):
        kw = (
            {"available_at": None}
            if change == "missing_availability"
            else (
                {"available_at": inputs["known_at"] + timedelta(seconds=1)}
                if change == "later_evidence"
                else {"captured_revision": "later"}
            )
        )
        inputs["evidence"]["opening"] = replace(inputs["evidence"]["opening"], **kw)
    elif change == "missing_coverage":
        change_lot(inputs, coverage_complete=False)
    elif change == "deficit":
        change_lot(inputs, unallocated_consumption=D(".5"))
    elif change == "wrong_as_of":
        change_lot(inputs, as_of=inputs["as_of"] - timedelta(seconds=1))
    elif change == "inside_opening":
        inputs["as_of"] = dt("2026-02-16T11:15:00+08:00")
    elif change == "missing_supply":
        inputs["supply_manifest"] = ["omitted-delivery"]
    else:
        add_supply(inputs)
        inputs["supplies"] = [
            replace(
                inputs["supplies"][0],
                **(
                    {"expiry_date": None}
                    if change == "missing_expiry"
                    else {"expiry_evidence": None}
                ),
            )
        ]
    assert_incomplete(project_inventory(**inputs), code)


@pytest.mark.parametrize("value", [D("-1"), D("NaN"), D("Infinity"), 0.5])
def test_invalid_demand_quantities(inputs, value):
    values = dict(inputs["buckets"][0].expected_portions)
    values["tofu-bowl"] = value
    inputs["buckets"][0] = replace(inputs["buckets"][0], expected_portions=values)
    with pytest.raises(ValueError):
        project_inventory(**inputs)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_dish",
        "unknown_lot",
        "unit",
        "naive",
        "overlap",
        "negative_stock",
        "infinite_stock",
        "expired_status",
        "future_count",
        "duplicate_lot",
        "duplicate_manifest",
        "bad_fefo",
        "two_days",
        "duplicate_supply",
        "supply_arithmetic",
        "future_receipt",
        "duplicate_receipt",
        "bad_receipt_link",
        "expiry_before_arrival",
    ],
)
def test_structural_invalid_inputs(inputs, change):
    if change == "unknown_dish":
        inputs["buckets"][0] = replace(
            inputs["buckets"][0], expected_portions={"unknown": D(1)}
        )
    elif change == "unknown_lot":
        change_lot(inputs, ingredient_id="unknown")
    elif change == "unit":
        change_lot(inputs, unit="litres")
    elif change == "naive":
        inputs["as_of"] = inputs["as_of"].replace(tzinfo=None)
    elif change == "overlap":
        inputs["buckets"].append(inputs["buckets"][0])
    elif change in ("negative_stock", "infinite_stock"):
        change_lot(
            inputs, quantity=D("-1" if change == "negative_stock" else "Infinity")
        )
    elif change == "expired_status":
        change_lot(inputs, status="EXPIRED")
    elif change == "future_count":
        change_lot(inputs, counted_at=inputs["as_of"] + timedelta(seconds=1))
    elif change == "duplicate_lot":
        inputs["opening_lots"].append(inputs["opening_lots"][0])
    elif change == "duplicate_manifest":
        inputs["opening_manifest"]["vegetables"] *= 2
    elif change == "bad_fefo":
        inputs["fixture_fefo"] = None
    elif change == "two_days":
        inputs["horizon_end"] += timedelta(days=1)
    else:
        add_supply(inputs)
        if change == "duplicate_supply":
            inputs["supplies"] *= 2
        elif change == "supply_arithmetic":
            inputs["supplies"] = [
                replace(
                    inputs["supplies"][0],
                    delivery=inputs["supplies"][0].delivery.model_copy(
                        update={"outstanding_quantity": D(1)}
                    ),
                )
            ]
        elif change == "expiry_before_arrival":
            inputs["supplies"] = [
                replace(inputs["supplies"][0], expiry_date=date(2026, 2, 15))
            ]
        else:
            receipt = Receipt(
                id="r",
                delivery_id="wrong"
                if change == "bad_receipt_link"
                else "fixed-vegetables",
                lot_id="vegetables-opening",
                request_id="r",
                quantity=D(2),
                received_at=inputs["as_of"] + timedelta(hours=1)
                if change == "future_receipt"
                else inputs["as_of"],
                expiry_date=date(2026, 2, 18),
                remainder="EXPECTED",
                closing_counts={},
            )
            receipts = (
                [receipt, receipt] if change == "duplicate_receipt" else [receipt]
            )
            d = inputs["supplies"][0].delivery.model_copy(update={"receipts": receipts})
            inputs["supplies"] = [replace(inputs["supplies"][0], delivery=d)]
    with pytest.raises(ValueError):
        project_inventory(**inputs)


def test_deterministic_context_order_and_no_mutation(inputs):
    add_supply(inputs)
    before = repr(inputs)
    result = project_inventory(**inputs)
    assert repr(inputs) == before
    with localcontext() as ctx:
        ctx.prec = 2
        repeated = project_inventory(**inputs)
    assert result == repeated
    assert repr(inputs) == before
    for key in (
        "opening_lots",
        "buckets",
        "recipes",
        "ingredients",
        "menu_items",
        "service_profile",
        "supplies",
        "recipe_manifest",
        "supply_manifest",
    ):
        inputs[key] = list(reversed(inputs[key]))
    inputs["evidence"] = dict(reversed(list(inputs["evidence"].items())))
    assert result == project_inventory(**inputs)


@pytest.mark.parametrize(
    "field", ["quantity", "initial_quantity", "unallocated_consumption"]
)
def test_opening_model_cannot_coerce_float_into_exact_input(inputs, field):
    change_lot(inputs, **{field: 0.5})
    with pytest.raises(ValueError):
        project_inventory(**inputs)


def test_supply_model_cannot_coerce_float(inputs):
    add_supply(inputs, outstanding_quantity=0.5)
    with pytest.raises(ValueError):
        project_inventory(**inputs)


def test_missing_received_lot_is_incomplete_not_new_supply(inputs):
    receipt = Receipt(
        id="missing-lot-receipt",
        delivery_id="fixed-vegetables",
        lot_id="missing-lot",
        request_id="slip",
        quantity=D(6),
        received_at=inputs["as_of"],
        expiry_date=date(2026, 2, 18),
        remainder="EXPECTED",
        closing_counts={},
    )
    add_supply(
        inputs,
        quantity="10",
        received_quantity=D(6),
        outstanding_quantity=D(4),
        receipts=[receipt],
    )
    assert_incomplete(project_inventory(**inputs), "RECEIPT_OPENING_LINK_MISSING")


def test_historical_deficit_is_not_summed_across_lots(inputs):
    old = next(l for l in inputs["opening_lots"] if l.ingredient_id == "vegetables")
    change_lot(inputs, unallocated_consumption=D(".7"))
    inputs["opening_lots"].append(
        old.model_copy(
            update={"id": "vegetables-extra", "unallocated_consumption": D(".7")}
        )
    )
    inputs["opening_manifest"]["vegetables"].append("vegetables-extra")
    result = project_inventory(**inputs)
    assert_incomplete(result, "HISTORICAL_UNALLOCATED_CONSUMPTION")
    assert (
        len(
            [
                f
                for f in result.findings
                if f.code == "HISTORICAL_UNALLOCATED_CONSUMPTION"
            ]
        )
        == 1
    )
    inputs["opening_lots"][-1] = inputs["opening_lots"][-1].model_copy(
        update={"unallocated_consumption": D(".8")}
    )
    with pytest.raises(ValueError):
        project_inventory(**inputs)


def test_first_bucket_shortage_survives_sufficient_second_bucket_supply(inputs):
    change_lot(inputs, quantity=D(".5"), initial_quantity=D(".5"))
    add_supply(inputs, quantity="10")
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.first_shortages is not None and result.buckets is not None
    assert result.first_shortages[0].start == inputs["buckets"][0].start
    assert vegetable(result.buckets[0].ingredients).unmet == D(1)
    assert vegetable(result.buckets[1].ingredients).unmet == 0
    assert vegetable(result.ingredients).closing == D(9)


def test_incomplete_return_also_preserves_inputs_and_is_deterministic(inputs):
    add_supply(inputs, "2026-02-16T11:15:00+08:00")
    del inputs["evidence"]["opening"]
    before = repr(inputs)
    result = project_inventory(**inputs)
    assert_incomplete(result, "MISSING_EVIDENCE")
    assert repr(inputs) == before and project_inventory(**inputs) == result


@pytest.mark.parametrize(
    "opening", ["0", ".001", "1.4999999999999999999", "2.5", "1000"]
)
@pytest.mark.parametrize(
    "arrival",
    [
        "2026-02-16T11:00:00+08:00",
        "2026-02-16T11:30:00+08:00",
        "2026-02-16T12:00:00+08:00",
    ],
)
def test_fraction_reference_across_stock_and_arrival_cases(inputs, opening, arrival):
    change_lot(inputs, quantity=D(opening), initial_quantity=D(opening))
    add_supply(inputs, arrival, quantity=".123")
    result = project_inventory(**inputs)
    assert_conserved(result)
    assert result.buckets is not None
    # Independent rational oracle, not production Decimal arithmetic.
    balance = Fraction(opening)
    outstanding = Fraction(123, 1000)
    expected = []
    for bucket, need in zip(
        inputs["buckets"], [Fraction(3, 2), Fraction(1)], strict=True
    ):
        if dt(arrival) <= bucket.start and outstanding:
            balance += outstanding
            outstanding = Fraction(0)
        unmet = max(need - balance, Fraction(0))
        balance = max(balance - need, Fraction(0))
        expected.append((balance, unmet))
    assert [
        (
            Fraction(vegetable(b.ingredients).closing),
            Fraction(vegetable(b.ingredients).unmet),
        )
        for b in result.buckets
    ] == expected
    assert Fraction(vegetable(result.ingredients).closing) == balance + outstanding

    inputs["known_at"] = inputs["known_at"].astimezone(UTC)
    inputs["as_of"] = inputs["as_of"].astimezone(UTC)
    assert result == project_inventory(**inputs)

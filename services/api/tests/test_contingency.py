"""Independent current-catalogue oracles; no backend/Agent activation implied."""

import copy
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from src.contingency import (
    EVIDENCE,
    POLICIES,
    ContingencyCandidate,
    ContingencyInputs,
    MultiDayInputs,
    search_contingency,
    validate_contingency,
)
from src.coverage import CoverageResult, ProtectedWindow
from src.inventory_projection import (
    FEFO_POLICY,
    SOURCE_NAMES,
    ExpectedSupply,
    SourceEvidence,
)
from src.multiday_projection import CONSTRAINT_POLICY
from src.operations_schemas import Delivery, Receipt
from src.procurement import Cash, OrderingOpportunity, PurchaseCandidate, PurchaseLine
from src.promotion_forecasting import SOURCES, ForecastVersion
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    LocalCutoff,
    MenuItem,
    NoCutoff,
    RecipeItem,
    Supplier,
    SupplierOffer,
)
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
F = json.loads((FIXTURES / "contingency_v1.json").read_text())


def present[T](value: T | None) -> T:
    assert value is not None
    return value


@pytest.fixture
def p():
    cat = json.loads((FIXTURES / F["catalogue_fixture"]).read_text())
    menu = [MenuItem.model_validate(x) for x in cat["menu_items"]]
    ingredients = [Ingredient.model_validate(x) for x in cat["ingredients"]]
    recipes = [RecipeItem.model_validate(x) for x in cat["recipes"]]
    issue, known = (
        datetime.fromisoformat(F["as_of"]),
        datetime.fromisoformat(F["known_at"]),
    )
    end, assess = (
        datetime.fromisoformat(F["protected_end"]),
        datetime.fromisoformat(F["assessment_end"]),
    )
    ev = SourceEvidence("synthetic:version-1", known, F["revision"])
    coverage = CoverageResult(
        issue,
        known,
        F["revision"],
        tuple(i.id for i in ingredients),
        True,
        tuple(
            ProtectedWindow(
                i.id, issue, end, None, end.date(), "explicit-fixture-boundary"
            )
            for i in ingredients
        ),
        end,
        (),
        (),
        (("catalogue", ev), ("policy", ev)),
        2,
        "EXPLICIT_TEST_WINDOWS",
        POLICIES["expiry"],
    )
    forecasts = []
    for offset in (0, 1):
        day = issue.date() + timedelta(days=offset)
        profile = tuple(
            ServicePeriod(
                datetime.combine(day, time.fromisoformat(s), issue.tzinfo),
                datetime.combine(day, time.fromisoformat(e), issue.tzinfo),
                D(w),
            )
            for s, e, w in F["profile"]
        )
        buckets = allocate_service_buckets(
            {k: D(v) if offset == 0 else D(0) for k, v in F["portions"].items()},
            menu,
            target_date=day,
            profile=profile,
        )
        forecasts.append(
            ForecastVersion(
                "synthetic-forecast:" + str(day),
                issue,
                known,
                day,
                profile,
                tuple((k, ev) for k in sorted(SOURCES)),
                buckets,
                "EXCLUDED",
                "synthetic-forecast:" + str(day),
            )
        )
    lots = [
        EstimatedInventoryLot(
            id=i.id + "-opening",
            ingredient_id=i.id,
            unit=i.unit,
            received_at=issue - timedelta(hours=1),
            expiry_date=date(2026, 2, 20),
            initial_quantity=D(F["opening"][i.id]),
            quantity=D(F["opening"][i.id]),
            counted_at=issue,
            as_of=issue,
            coverage_start=issue,
            coverage_complete=True,
            status="ACTIVE",
        )
        for i in ingredients
    ]
    receipt = Receipt(
        id="receipt-six",
        delivery_id="fixed-original",
        request_id="receipt-six",
        lot_id="vegetables-opening",
        quantity=D(6),
        received_at=issue - timedelta(hours=1),
        expiry_date=date(2026, 2, 20),
        remainder="EXPECTED",
    )
    original = Delivery(
        id="fixed-original",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(10),
        received_quantity=D(6),
        cancelled_quantity=D(0),
        outstanding_quantity=D(4),
        ordered_at=issue - timedelta(days=1),
        expected_at=issue + timedelta(hours=23),
        receipts=[receipt],
    )
    inventory: MultiDayInputs = {
        "coverage": coverage,
        "forecasts": forecasts,
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "opening_lots": lots,
        "supplies": [
            ExpectedSupply(original, date(2026, 2, 20), ev, "fixed-future-lot")
        ],
        "opening_manifest": {i.id: [i.id + "-opening"] for i in ingredients},
        "supply_manifest": [original.id],
        "recipe_manifest": [(r.menu_item_id, r.ingredient_id) for r in recipes],
        "evidence": {k: ev for k in SOURCE_NAMES | {"constraints"}},
        "safety": {i.id: D(F["safety_each_base_unit"]) for i in ingredients},
        "storage": {i.id: D(F["storage_each_base_unit"]) for i in ingredients},
        "assessment_end": {
            i.id: assess if i.id == "vegetables" else end for i in ingredients
        },
        "constraint_policy": CONSTRAINT_POLICY,
        "fefo_policy": FEFO_POLICY,
    }
    arrival = issue + timedelta(hours=1)
    offer = SupplierOffer(
        id="market-vegetables",
        supplier_id="market",
        ingredient_id="vegetables",
        unit_price=D(F["new_offer"]["unit_price"]),
        available_quantity=D(F["new_offer"]["available_quantity"]),
        moq=D(F["new_offer"]["moq"]),
        pack_size=D(F["new_offer"]["pack_size"]),
        delivery_fee_sgd=D(F["new_offer"]["delivery_fee_sgd"]),
        emergency_fee_sgd=D(F["new_offer"]["emergency_fee_sgd"]),
        lead_time_minutes=60,
        order_cutoff=NoCutoff(kind="NONE"),
        feasible_delivery_at=[arrival],
        current_status="AVAILABLE",
        recent_on_time_rate=D("0.5"),
        shelf_life_days_on_arrival=2,
        observed_at=known,
    )
    op = OrderingOpportunity(
        "rescue", offer.id, issue, arrival, "EMERGENCY", date(2026, 2, 17), ev
    )
    return ContingencyInputs(
        inventory,
        [Supplier(id=k, name=k) for k in ("fresh", "market", "pantry")],
        [offer],
        [(offer.id, offer.supplier_id, offer.ingredient_id)],
        [op],
        [op.id],
        {op.id: "new-rescue-shipment"},
        {op.id: 6},
        D(F["budget_sgd"]),
        dict(POLICIES),
        {k: ev for k in EVIDENCE},
        {offer.id: ev},
        10000,
    )


def row(projection, ingredient="vegetables"):
    assert projection is not None and projection.complete
    out = next(
        r.projection for r in projection.ingredients if r.ingredient_id == ingredient
    )
    assert out is not None and out.ingredients is not None
    return out.ingredients[0]


def candidate(q="4", op="rescue"):
    return ContingencyCandidate(PurchaseCandidate((PurchaseLine(op, D(q), "kg"),)))


def fixed(p, **changes):
    inv = p.inventory.copy()
    s = inv["supplies"][0]
    inv["supplies"] = [replace(s, delivery=s.delivery.model_copy(update=changes))]
    return replace(p, inventory=inv)


def offer(p, **changes):
    o = p.offers[0].model_copy(update=changes)
    bounds = dict(p.max_packs)
    if o.available_quantity is not None and o.pack_size:
        bounds = {
            op.id: int(Fraction(o.available_quantity) // Fraction(o.pack_size))
            for op in p.opportunities
        }
    return replace(p, offers=[o], max_packs=bounds)


def test_worked_late_original_rescue_and_conservation(p):
    before = repr(p)
    r = search_contingency(p)
    assert r.status == "OPTIMAL_IN_DOMAIN" and r.search_complete and r.optimal_in_domain
    assert r.domain_size == r.evaluated == 7
    assert r.candidate is not None and r.validation is not None
    assert present(r.candidate).purchase.lines == (PurchaseLine("rescue", D(4), "kg"),)
    assert present(r.validation).cash == Cash(D(8), D(3), D(4), D(15))
    assert row(present(r.validation).projection).closing == 4
    assert (
        row(present(r.validation).projection).admitted == 8
    )  # Rescue 4 + old remainder 4.
    assert r.no_purchase is not None and not present(r.no_purchase).actionable
    assert row(present(r.no_purchase).projection).unmet == 4
    assert row(present(r.no_purchase).projection).closing == 4
    assert (
        present(r.no_purchase).lost_dish_portions
        is present(r.no_purchase).economic_score
        is None
    )
    assert present(r.no_purchase).fixed_supply_ids == ("fixed-original",)
    assert (
        present(r.validation).additions[0].latest_placement_at
        == p.inventory["coverage"].issue_time
    )
    for ingredient in present(present(r.validation).projection).ingredients:
        for lot in present(present(ingredient.projection).lots):
            assert Fraction(lot.opening) + Fraction(lot.admitted) == Fraction(
                lot.allocated
            ) + Fraction(lot.expired) + Fraction(lot.closing)
    assert validate_contingency(p, r.candidate).feasible
    assert repr(p) == before and search_contingency(p) == r


def test_partial_receipt_on_time_zero_addition(p):
    p = fixed(p, expected_at=p.opportunities[0].arrival_at)
    r = search_contingency(p)
    assert present(r.candidate).purchase.lines == ()
    assert present(present(r.validation).cash).total == 0
    b = row(present(r.validation).projection)
    assert (b.opening, b.admitted, b.allocated, b.unmet, b.closing) == (6, 4, 10, 0, 0)


def test_short_and_cancelled_remainders(p):
    for remaining, cancelled, want in ((D(2), D(2), D(2)), (D(0), D(4), D(4))):
        q = fixed(
            p,
            outstanding_quantity=remaining,
            cancelled_quantity=cancelled,
            expected_at=p.opportunities[0].arrival_at,
        )
        r = search_contingency(q)
        assert present(r.candidate).purchase.lines[0].quantity == want
        assert row(present(r.validation).projection).allocated == 10


def test_packs_and_moq_excess(p):
    p = offer(p, pack_size=D(3), moq=D(3))
    r = search_contingency(p)
    assert present(r.candidate).purchase.lines[0].quantity == 6
    assert present(present(r.validation).cash).total == 19  # 6*2 + 3 + 4.
    assert (
        row(present(r.validation).projection).closing == 6
    )  # Two surplus + original four.


def test_approval_is_no_supply_recorded_contingency_prevents_duplicate(p):
    r = search_contingency(p)
    assert search_contingency(p) == r  # Reviewing/approving mutates no numerical facts.
    a = present(r.validation).additions[0]
    d = Delivery(
        id="recorded-emergency",
        supplier_id=a.supplier_id,
        ingredient_id=a.ingredient_id,
        kind="EMERGENCY",
        expected_quantity=a.quantity,
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=a.quantity,
        ordered_at=a.ordered_at,
        expected_at=a.arrival_at,
        receipts=[],
    )
    inv = p.inventory.copy()
    inv["supplies"] = [
        *inv["supplies"],
        ExpectedSupply(
            d, a.expiry_date, p.evidence["domain"], "recorded-emergency-lot"
        ),
    ]
    inv["supply_manifest"] = [*inv["supply_manifest"], d.id]
    again = search_contingency(replace(p, inventory=inv))
    assert present(again.candidate).purchase.lines == ()
    assert present(present(again.validation).cash).total == 0
    assert row(present(again.validation).projection).admitted == 8
    assert d.received_quantity == 0 and d.receipts == []  # Actual receipt still later.


def two_offers(p):
    base = p.offers[0]
    ops, offers = [], []
    for supplier in ("fresh", "market"):
        o = base.model_copy(
            update={
                "id": supplier + "-vegetables",
                "supplier_id": supplier,
                "available_quantity": D(2),
            }
        )
        offers.append(o)
        ops.append(replace(p.opportunities[0], id=supplier + "-op", offer_id=o.id))
    return replace(
        p,
        offers=offers,
        opportunities=ops,
        opportunity_manifest=[o.id for o in ops],
        approved_offer_manifest=[
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ],
        offer_evidence={o.id: p.evidence["domain"] for o in offers},
        shipment_groups={o.id: o.id + "-shipment" for o in ops},
        max_packs={o.id: 2 for o in ops},
    )


def test_supplier_split_independent_tiny_exhaustive(p):
    p = two_offers(p)
    expected = [
        (a + b) * 2 + 7 * ((a > 0) + (b > 0))
        for a in range(3)
        for b in range(3)
        if a + b >= 4
    ]
    assert expected == [22]
    r = search_contingency(p)
    assert r.domain_size == r.evaluated == 9
    assert [l.quantity for l in present(r.candidate).purchase.lines] == [D(2), D(2)]
    assert present(present(r.validation).cash).total == min(expected)


def test_shared_capacity_and_distinct_shipments(p):
    op = replace(p.opportunities[0], id="second")
    p = replace(
        p,
        opportunities=[*p.opportunities, op],
        opportunity_manifest=["rescue", "second"],
        shipment_groups={"rescue": "one", "second": "two"},
        max_packs={"rescue": 6, "second": 6},
    )
    c = ContingencyCandidate(
        PurchaseCandidate(
            (PurchaseLine("rescue", D(2), "kg"), PurchaseLine("second", D(2), "kg"))
        )
    )
    v = validate_contingency(p, c)
    assert v.feasible and v.cash == Cash(D(8), D(6), D(8), D(22))
    v = validate_contingency(
        p,
        replace(
            c,
            purchase=PurchaseCandidate(
                (PurchaseLine("rescue", D(4), "kg"), PurchaseLine("second", D(4), "kg"))
            ),
        ),
    )
    assert "SHARED_OFFER_CAPACITY" in {f.code for f in v.violations}


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("lead_time_minutes", 61, "LEAD_TIME"),
        (
            "order_cutoff",
            LocalCutoff(kind="LOCAL_TIME", local_time=time(9, 59)),
            "ORDER_CUTOFF",
        ),
        ("current_status", "UNAVAILABLE", "OFFER_UNAVAILABLE"),
        ("feasible_delivery_at", [], "DELIVERY_SLOT"),
        ("shelf_life_days_on_arrival", 0, "EXPECTED_EXPIRY_POLICY"),
    ],
)
def test_complete_supplier_exclusions(p, field, value, code):
    p = offer(p, **{field: value})
    r = search_contingency(p)
    assert (
        r.status == "INFEASIBLE_IN_DOMAIN" and r.reason == "NO_TIMELY_SUPPLY_IN_DOMAIN"
    )
    assert code in {e.code for e in r.exclusions}
    assert r.candidate is None


def test_arrival_at_end_cannot_backfill_first_shortage(p):
    arrival = p.opportunities[0].arrival_at + timedelta(minutes=30)
    p = offer(p, feasible_delivery_at=[arrival])
    p = replace(p, opportunities=[replace(p.opportunities[0], arrival_at=arrival)])
    r = search_contingency(p)
    assert r.reason == "NO_TIMELY_SUPPLY_IN_DOMAIN"
    assert present(r.no_purchase).projection.breaches[0].start.hour == 11


@pytest.mark.parametrize("constraint", ["budget", "storage", "safety"])
def test_policy_infeasibility_not_supplier_failure(p, constraint):
    inv = p.inventory.copy()
    if constraint == "budget":
        p = replace(p, budget=D(14))
    elif constraint == "storage":
        inv["storage"] = {**inv["storage"], "vegetables": D(9)}
    else:
        inv["safety"] = {**inv["safety"], "vegetables": D(3)}
    r = search_contingency(replace(p, inventory=inv))
    assert r.reason == "POLICY_CONSTRAINT_INFEASIBLE"
    assert constraint.upper() in dict(r.rejection_counts)


@pytest.mark.parametrize(
    "missing",
    [
        "expiry",
        "coverage",
        "policy",
        "domain",
        "unit_price",
        "budget",
        "shipment",
        "forecast",
        "opening",
    ],
)
def test_missing_is_incomplete(p, missing):
    inv = p.inventory.copy()
    if missing == "expiry":
        inv["supplies"] = [replace(inv["supplies"][0], expiry_date=None)]
    elif missing == "coverage":
        inv["coverage"] = replace(inv["coverage"], complete=False)
    elif missing == "policy":
        p = replace(p, policies={**p.policies, "contingency": None})
    elif missing == "domain":
        p = replace(p, opportunity_manifest=None)
    elif missing == "unit_price":
        p = offer(p, unit_price=None)
    elif missing == "budget":
        p = replace(p, budget=None)
    elif missing == "shipment":
        p = replace(p, shipment_groups={})
    elif missing == "forecast":
        inv["forecasts"] = inv["forecasts"][:1]
    else:
        inv["opening_manifest"] = {
            k: v for k, v in inv["opening_manifest"].items() if k != "vegetables"
        }
    r = search_contingency(replace(p, inventory=inv))
    assert r.status == "INCOMPLETE" and r.candidate is None and r.findings


def test_work_limit_counts_construction_and_incumbent_is_diagnostic(p):
    full = search_contingency(p)
    # Seven evaluations cost two work units each; stop after five (zero..four).
    limited = search_contingency(replace(p, work_limit=full.work_used - 4))
    assert limited.evaluated == 5
    assert limited.reason == "SEARCH_LIMIT_REACHED" and not limited.search_complete
    assert limited.candidate is limited.validation is None
    assert present(limited.diagnostic_incumbent).purchase.lines[0].quantity == 4
    tiny = search_contingency(replace(p, work_limit=1))
    assert tiny.work_used == 1 and tiny.evaluated == 0 and tiny.candidate is None


def test_late_original_storage_and_expiry_not_hidden(p):
    # Rescue pack 6 leaves 2; late original 10 then exceeds limit 10.
    p = fixed(p, expected_quantity=D(16), outstanding_quantity=D(10))
    p = offer(p, pack_size=D(6), moq=D(6))
    inv = p.inventory.copy()
    inv["storage"] = {**inv["storage"], "vegetables": D(10)}
    v = validate_contingency(replace(p, inventory=inv), candidate("6"))
    assert any(
        f.code == "STORAGE" and "2026-02-17T09" in f.source for f in v.violations
    )
    inv["storage"] = {**inv["storage"], "vegetables": D(30)}
    inv["opening_lots"] = [
        l.model_copy(update={"expiry_date": date(2026, 2, 16)})
        if l.ingredient_id == "vegetables"
        else l
        for l in inv["opening_lots"]
    ]
    old = inv["supplies"][0]
    inv["supplies"] = [
        replace(
            old,
            delivery=old.delivery.model_copy(
                update={
                    "receipts": [
                        r.model_copy(update={"expiry_date": date(2026, 2, 16)})
                        for r in old.delivery.receipts
                    ]
                }
            ),
        )
    ]
    p = replace(p, inventory=inv)
    p = offer(p, shelf_life_days_on_arrival=1)
    p = replace(
        p, opportunities=[replace(p.opportunities[0], expiry_date=date(2026, 2, 16))]
    )
    v = validate_contingency(p, candidate("6"))
    assert v.feasible and row(v.projection).expired == 2
    assert row(v.projection).closing == 10


def test_semantic_ties_rename_and_reliability_invariance(p):
    p = two_offers(p)
    p = replace(
        p,
        offers=[o.model_copy(update={"available_quantity": D(4)}) for o in p.offers],
        max_packs={op.id: 4 for op in p.opportunities},
    )
    first = search_contingency(p)
    assert present(first.validation).additions[0].supplier_id == "fresh"
    ops = [
        replace(op, id="z" if op.id.startswith("fresh") else "a")
        for op in reversed(p.opportunities)
    ]
    q = replace(
        p,
        opportunities=ops,
        opportunity_manifest=[o.id for o in ops],
        shipment_groups={o.id: "shipment-" + o.offer_id for o in ops},
        max_packs={o.id: 4 for o in ops},
        offers=[
            o.model_copy(
                update={
                    "recent_on_time_rate": D(0) if o.supplier_id == "fresh" else D(1)
                }
            )
            for o in reversed(p.offers)
        ],
    )
    other = search_contingency(q)
    assert present(other.validation).additions[0].supplier_id == "fresh"
    assert present(other.validation).cash == present(first.validation).cash


@pytest.mark.parametrize("tamper", ["quantity", "arrival", "cash", "unit", "unknown"])
def test_independent_validation_rejects_tampering(p, tamper, monkeypatch):
    r = search_contingency(p)
    c = r.candidate
    assert c is not None
    monkeypatch.setattr(
        "src.contingency.search_contingency",
        lambda _: pytest.fail("validator called optimiser"),
    )
    if tamper == "arrival":
        c = replace(
            c,
            claimed_additions=(
                replace(
                    present(c.claimed_additions)[0],
                    arrival_at=present(c.claimed_additions)[0].arrival_at
                    + timedelta(hours=1),
                ),
            ),
        )
    elif tamper == "cash":
        c = replace(
            c, purchase=replace(c.purchase, claimed_cash=Cash(D(0), D(0), D(0), D(0)))
        )
    else:
        line = c.purchase.lines[0]
        line = replace(
            line,
            **(
                {"quantity": D("0.5")}
                if tamper == "quantity"
                else {"unit": "litres"}
                if tamper == "unit"
                else {"opportunity_id": "unknown"}
            ),
        )
        c = replace(c, purchase=replace(c.purchase, lines=(line,)))
    v = validate_contingency(p, c)
    assert v.complete and not v.feasible and v.violations


def test_normal_reduction_not_silently_enabled(p):
    r = search_contingency(
        replace(p, policies={**p.policies, "search": "COMPLETE_PRUNED_DOMAIN_V1"})
    )
    assert r.status == "INCOMPLETE"
    assert "MISSING_OR_UNSUPPORTED_POLICY" in {f.code for f in r.findings}


def test_elapsed_actuals_not_consumed_twice(p):
    inv = p.inventory.copy()
    f = inv["forecasts"][0]
    prior = ProjectedDemandBucket(
        f.as_of - timedelta(minutes=30), f.as_of, {k: D(100) for k in F["portions"]}
    )
    # Complete past actuals may be retained as evidence; only future buckets used.
    inv["forecasts"] = [replace(f, actuals=(prior,)), *inv["forecasts"][1:]]
    assert (
        present(
            present(search_contingency(replace(p, inventory=inv)).validation).cash
        ).total
        == 15
    )
    inv["forecasts"] = [replace(f, buckets=(prior, *f.buckets)), *inv["forecasts"][1:]]
    with pytest.raises(ValueError, match="elapsed"):
        search_contingency(replace(p, inventory=inv))


def test_residual_next_day_coverage_and_expiry_boundary(p):
    inv = p.inventory.copy()
    inv["coverage"] = replace(
        inv["coverage"],
        windows=tuple(
            replace(w, end=inv["assessment_end"]["vegetables"])
            if w.ingredient_id == "vegetables"
            else w
            for w in inv["coverage"].windows
        ),
    )
    f = inv["forecasts"][1]
    inv["forecasts"] = [
        inv["forecasts"][0],
        replace(
            f,
            buckets=allocate_service_buckets(
                {k: D(20) if k == "tofu-bowl" else D(0) for k in F["portions"]},
                inv["menu_items"],
                target_date=f.target_date,
                profile=f.profile,
            ),
        ),
    ]
    p = replace(p, inventory=inv)
    v = present(search_contingency(p).validation)
    assert row(v.projection).required == 12 and row(v.projection).closing == 2


def test_invalid_bound_not_false_infeasibility(p):
    with pytest.raises(ValueError, match="every pack"):
        search_contingency(replace(p, max_packs={"rescue": 3}))


def test_exact_arithmetic_independent_of_ambient_context(p):
    expected = search_contingency(p)
    with localcontext() as ctx:
        ctx.prec = 3
        assert search_contingency(p) == expected


def test_input_models_unchanged(p):
    offers = copy.deepcopy(p.offers)
    deliveries = copy.deepcopy(p.inventory["supplies"])
    validate_contingency(p, candidate())
    assert p.offers == offers and p.inventory["supplies"] == deliveries


def test_full_on_time_commitment_and_explicit_zero_opening(p):
    p = fixed(
        p,
        received_quantity=D(0),
        outstanding_quantity=D(10),
        receipts=[],
        expected_at=p.opportunities[0].arrival_at,
    )
    inv = p.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": D(0), "initial_quantity": D(0)})
        if l.ingredient_id == "vegetables"
        else l
        for l in inv["opening_lots"]
    ]
    r = search_contingency(replace(p, inventory=inv))
    assert present(r.candidate).purchase.lines == ()
    assert row(present(r.validation).projection).admitted == 10


def test_two_ingredients_share_new_shipment_fee_and_exclusive_emergency_once(p):
    inv = p.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": D(6), "initial_quantity": D(6)})
        if l.ingredient_id == "rice"
        else l
        for l in inv["opening_lots"]
    ]
    o = p.offers[0].model_copy(
        update={
            "id": "market-rice",
            "ingredient_id": "rice",
            "available_quantity": D(4),
        }
    )
    op = replace(p.opportunities[0], id="rescue-rice", offer_id=o.id, kind="NORMAL")
    p = replace(
        p,
        inventory=inv,
        offers=[*p.offers, o],
        opportunities=[*p.opportunities, op],
        approved_offer_manifest=[
            *p.approved_offer_manifest,
            (o.id, o.supplier_id, o.ingredient_id),
        ],
        opportunity_manifest=["rescue", op.id],
        offer_evidence={**p.offer_evidence, o.id: p.evidence["domain"]},
        shipment_groups={**p.shipment_groups, op.id: "new-rescue-shipment"},
        max_packs={**p.max_packs, op.id: 4},
    )
    r = search_contingency(p)
    assert present(r.validation).cash == Cash(D(16), D(3), D(4), D(23))
    assert len(present(r.validation).shipments) == 1
    assert [a.quantity for a in present(r.validation).additions] == [D(4), D(4)]


def test_equal_expiry_uses_receipt_time_before_lot_id(p):
    inv = p.inventory.copy()
    original = next(l for l in inv["opening_lots"] if l.ingredient_id == "vegetables")
    inv["supplies"], inv["supply_manifest"] = [], []
    older = original.model_copy(
        update={
            "id": "z-older",
            "quantity": D(4),
            "initial_quantity": D(4),
            "received_at": original.received_at - timedelta(hours=1),
            "expiry_date": date(2026, 2, 17),
        }
    )
    newer = original.model_copy(
        update={
            "id": "a-newer",
            "quantity": D(2),
            "initial_quantity": D(2),
            "expiry_date": date(2026, 2, 17),
        }
    )
    inv["opening_lots"] = [
        l for l in inv["opening_lots"] if l.ingredient_id != "vegetables"
    ] + [newer, older]
    inv["opening_manifest"] = {
        **inv["opening_manifest"],
        "vegetables": ["a-newer", "z-older"],
    }
    # Demand first bucket .7 kg makes the deliberately reversed ordering observable.
    f = inv["forecasts"][0]
    inv["forecasts"] = [
        replace(
            f,
            buckets=allocate_service_buckets(
                {k: D(10) if k == "tofu-bowl" else D(0) for k in F["portions"]},
                inv["menu_items"],
                target_date=f.target_date,
                profile=f.profile,
            ),
        ),
        *inv["forecasts"][1:],
    ]
    r = search_contingency(replace(p, inventory=inv))
    proj = present(present(r.validation).projection)
    veg = present(
        next(i.projection for i in proj.ingredients if i.ingredient_id == "vegetables")
    )
    allocations = {l.key: l.allocated for l in present(veg.buckets)[0].lots}
    assert allocations["opening:z-older"] == D("0.7")
    assert allocations["opening:a-newer"] == 0


@pytest.mark.parametrize("q", [D(-1), D("NaN"), D("Infinity"), 1.0])
def test_invalid_candidate_quantities(p, q):
    v = validate_contingency(
        p, ContingencyCandidate(PurchaseCandidate((PurchaseLine("rescue", q, "kg"),)))
    )
    assert not v.feasible and "INVALID_QUANTITY" in {f.code for f in v.violations}


def test_unavailable_future_evidence_and_midbucket_are_incomplete(p):
    ev = p.evidence["domain"]
    future = replace(ev, available_at=ev.available_at + timedelta(seconds=1))
    r = search_contingency(replace(p, evidence={**p.evidence, "domain": future}))
    assert r.status == "INCOMPLETE" and "NOT_YET_AVAILABLE" in {
        f.code for f in r.findings
    }
    arrival = p.opportunities[0].arrival_at + timedelta(minutes=15)
    p = offer(p, feasible_delivery_at=[arrival])
    r = search_contingency(
        replace(p, opportunities=[replace(p.opportunities[0], arrival_at=arrival)])
    )
    assert r.status == "INCOMPLETE" and "UNSUPPORTED_MID_BUCKET_ARRIVAL" in {
        f.code for f in r.findings
    }


def test_protected_next_day_shortage_not_erased_by_expired_supply(p):
    inv = p.inventory.copy()
    inv["coverage"] = replace(
        inv["coverage"],
        windows=tuple(
            replace(w, end=inv["assessment_end"]["vegetables"])
            if w.ingredient_id == "vegetables"
            else w
            for w in inv["coverage"].windows
        ),
    )
    inv["supplies"], inv["supply_manifest"] = [], []
    f = inv["forecasts"][1]
    inv["forecasts"] = [
        inv["forecasts"][0],
        replace(
            f,
            buckets=allocate_service_buckets(
                {k: D(20) if k == "tofu-bowl" else D(0) for k in F["portions"]},
                inv["menu_items"],
                target_date=f.target_date,
                profile=f.profile,
            ),
        ),
    ]
    # All opening and rescue vegetables expire at the intervening midnight.
    inv["opening_lots"] = [
        l.model_copy(update={"expiry_date": date(2026, 2, 16)})
        if l.ingredient_id == "vegetables"
        else l
        for l in inv["opening_lots"]
    ]
    p = offer(replace(p, inventory=inv), shelf_life_days_on_arrival=1)
    p = replace(
        p, opportunities=[replace(p.opportunities[0], expiry_date=date(2026, 2, 16))]
    )
    r = search_contingency(p)
    assert r.reason == "NO_TIMELY_SUPPLY_IN_DOMAIN"
    v = validate_contingency(p, candidate("6"))
    assert row(v.projection).expired == 2 and row(v.projection).unmet == 2

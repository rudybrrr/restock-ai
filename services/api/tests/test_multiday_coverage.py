"""Independent dated oracles; future opportunities are never stock receipts."""

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from src.coverage import (
    OCCASION_POLICY,
    Occasion,
    OpportunityDomain,
    calculate_coverage,
)
from src.inventory_projection import (
    FEFO_POLICY,
    SOURCE_NAMES,
    BucketProjection,
    ExpectedSupply,
    ExpiryQuantity,
    IngredientBalance,
    InventoryProjection,
    LotBalance,
    ShortageInterval,
    SourceEvidence,
    project_inventory,
)
from src.multiday_projection import CONSTRAINT_POLICY, project_multiday
from src.operations_schemas import Delivery, Receipt
from src.procurement import EXPIRY_POLICY, OrderingOpportunity
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
F = json.loads((FIXTURES / "multiday_coverage_v1.json").read_text())


@pytest.fixture
def data():
    cat = json.loads((FIXTURES / F["catalogue_fixture"]).read_text())
    ingredients = [Ingredient.model_validate(i) for i in cat["ingredients"]]
    menu = [MenuItem.model_validate(i) for i in cat["menu_items"]]
    recipes = [RecipeItem.model_validate(i) for i in cat["recipes"]]
    issue = datetime.fromisoformat(F["issue_time"])
    ev = SourceEvidence("synthetic-explicit-input", issue, F["captured_revision"])
    offers, domains, occasions = [], [], []
    for i in ingredients:
        next_day = i.starting_date + timedelta(days=i.interval_days)
        order = datetime.combine(next_day, time(22), issue.tzinfo)
        arrival = order + timedelta(hours=12)
        offer = SupplierOffer(
            id=i.id + "-offer",
            supplier_id="fresh",
            ingredient_id=i.id,
            unit_price=D(1),
            available_quantity=D(100),
            moq=D(1),
            pack_size=D(1),
            lead_time_minutes=60,
            order_cutoff=NoCutoff(kind="NONE"),
            feasible_delivery_at=[arrival],
            current_status="AVAILABLE",
            recent_on_time_rate=D("0.9"),
            shelf_life_days_on_arrival=30,
            delivery_fee_sgd=D(0),
            emergency_fee_sgd=D(0),
            observed_at=issue,
        )
        offers.append(offer)
        op = OrderingOpportunity(
            i.id + "-op",
            offer.id,
            order,
            arrival,
            "NORMAL",
            arrival.date() + timedelta(days=29),
            ev,
        )
        domains.append(OpportunityDomain(i.id, next_day, (op,), ev))
        occasions.extend(
            Occasion(i.id, day, "OPEN", issue, ev)
            for day in (i.starting_date, next_day)
        )
    coverage_inputs = {
        "ingredients": ingredients,
        "suppliers": [Supplier(id="fresh", name="Fixture supplier")],
        "offers": offers,
        "domains": domains,
        "occasions": occasions,
        "issue_time": issue,
        "known_at": issue,
        "captured_revision": ev.captured_revision,
        "decision_time": time.fromisoformat(F["decision_time"]),
        "approved_offer_manifest": [
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ],
        "evidence": {k: ev for k in ("catalogue", "schedule", "policy", "domain")},
        "offer_evidence": {o.id: ev for o in offers},
        "occasion_policy": OCCASION_POLICY,
        "expiry_policy": EXPIRY_POLICY,
        "max_horizon_days": F["max_horizon_days"],
    }
    coverage = calculate_coverage(**coverage_inputs)
    forecasts = []
    for offset in range(16):
        day = issue.date() + timedelta(days=offset)
        start = datetime.combine(day, time(11), issue.tzinfo)
        profile = (ServicePeriod(start, start + timedelta(minutes=30), D(1)),)
        buckets = allocate_service_buckets(
            {d: D(q) for d, q in F["daily_portions"].items()},
            menu,
            target_date=day,
            profile=profile,
        )
        forecasts.append(
            ForecastVersion(
                "forecast:" + str(day),
                issue,
                issue,
                day,
                profile,
                tuple((k, ev) for k in sorted(SOURCES)),
                tuple(b for b in buckets if b.start >= issue),
                "EXCLUDED",
                "forecast:" + str(day),
            )
        )
    lots = [
        EstimatedInventoryLot(
            id=i.id + "-opening",
            ingredient_id=i.id,
            unit=i.unit,
            received_at=issue - timedelta(days=1),
            expiry_date=date(2026, 3, 10),
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
    projection_inputs = {
        "coverage": coverage,
        "forecasts": forecasts,
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "opening_lots": lots,
        "supplies": [],
        "opening_manifest": {i.id: [i.id + "-opening"] for i in ingredients},
        "supply_manifest": [],
        "recipe_manifest": [(r.menu_item_id, r.ingredient_id) for r in recipes],
        "evidence": {k: ev for k in SOURCE_NAMES | {"constraints"}},
        "safety": {i.id: D(0) for i in ingredients},
        "storage": {i.id: D(100) for i in ingredients},
        "assessment_end": {w.ingredient_id: w.end for w in coverage.windows},
        "constraint_policy": CONSTRAINT_POLICY,
        "fefo_policy": FEFO_POLICY,
    }
    return coverage_inputs, projection_inputs


def result_row(result, ingredient="rice"):
    return next(r for r in result.ingredients if r.ingredient_id == ingredient)


def set_lot(p, ingredient, **changes):
    p["opening_lots"] = [
        l.model_copy(update=changes) if l.ingredient_id == ingredient else l
        for l in p["opening_lots"]
    ]


def supply(p, arrival, quantity="4", cancelled="0", received="0", receipts=()):
    issue = p["coverage"].issue_time
    total = D(quantity) + D(cancelled) + D(received)
    d = Delivery(
        id="fixed-rice",
        supplier_id="fresh",
        ingredient_id="rice",
        kind="NORMAL",
        expected_quantity=total,
        received_quantity=D(received),
        cancelled_quantity=D(cancelled),
        outstanding_quantity=D(quantity),
        ordered_at=issue - timedelta(days=1),
        expected_at=arrival,
        receipts=list(receipts),
    )
    p["supplies"] = [
        ExpectedSupply(d, date(2026, 3, 10), p["evidence"]["supply"], "future-rice-lot")
    ]
    p["supply_manifest"] = [d.id]


@dataclass(frozen=True)
class Numbers:
    ingredients: tuple[IngredientBalance, ...]
    lots: tuple[LotBalance, ...]
    buckets: tuple[BucketProjection, ...]
    expiries: tuple[ExpiryQuantity, ...]
    first_shortages: tuple[ShortageInterval, ...]


def numbers(p: InventoryProjection | None) -> Numbers:
    assert p is not None and p.complete
    assert p.ingredients is not None and p.lots is not None
    assert p.buckets is not None and p.expiries is not None
    assert p.first_shortages is not None
    return Numbers(p.ingredients, p.lots, p.buckets, p.expiries, p.first_shortages)


def test_hand_derived_daily_weekly_fortnightly_conservation(data):
    _c, p = data
    result = project_multiday(**p)
    assert result.complete and not result.breaches
    for i, value in F["expected_end"].items():
        assert result_row(result, i).protected_end == datetime.fromisoformat(value)
    assert p["coverage"].forecast_end == datetime.fromisoformat(
        "2026-03-02T10:00:00+08:00"
    )
    for row in result.ingredients:
        totals = numbers(row.projection).ingredients[0]
        assert totals.required == D(F["expected_required"][row.ingredient_id])
        assert totals.closing == totals.unmet == totals.admitted == 0
        for lot in numbers(row.projection).lots:
            assert Fraction(lot.opening) + Fraction(lot.admitted) == Fraction(
                lot.allocated
            ) + Fraction(lot.expired) + Fraction(lot.closing)
    # Daily chicken stops after one service; its zero stock is not assessed for 14 days.
    assert len(numbers(result_row(result, "chicken").projection).buckets) == 1


def test_one_day_exact_parity(data):
    _, p = data
    issue = p["coverage"].issue_time
    end = issue + timedelta(hours=14)
    p["coverage"] = replace(
        p["coverage"],
        windows=tuple(replace(w, end=end) for w in p["coverage"].windows),
        forecast_end=end,
    )
    p["assessment_end"] = {i.id: end for i in p["ingredients"]}
    f = p["forecasts"][1]
    original = project_inventory(
        p["opening_lots"],
        f.buckets,
        p["menu_items"],
        p["ingredients"],
        p["recipes"],
        [],
        as_of=issue,
        target_date=f.target_date,
        horizon_end=end,
        known_at=issue,
        captured_revision=p["coverage"].captured_revision,
        opening_manifest=p["opening_manifest"],
        supply_manifest=[],
        recipe_manifest=p["recipe_manifest"],
        service_profile=f.profile,
        evidence={k: p["evidence"][k] for k in SOURCE_NAMES},
        fixture_fefo=FEFO_POLICY,
    )
    result = project_multiday(**p)
    assert result.complete
    assert (
        tuple(
            numbers(result_row(result, r.ingredient_id).projection).ingredients[0]
            for r in numbers(original).ingredients
        )
        == original.ingredients
    )
    assert (
        tuple(l for r in result.ingredients for l in numbers(r.projection).lots)
        == original.lots
    )


@pytest.mark.parametrize("state", ["ORDERED", "SKIPPED"])
def test_after_disposed_occasion_does_not_shift_anchor(data, state):
    c, _ = data
    c["issue_time"] += timedelta(minutes=1)
    c["occasions"] = [
        replace(o, status=state) if o.scheduled_date == date(2026, 2, 15) else o
        for o in c["occasions"]
    ]
    r = calculate_coverage(**c)
    assert r.complete
    assert next(
        w for w in r.windows if w.ingredient_id == "rice"
    ).next_occasion == date(2026, 3, 1)


def test_past_open_is_incomplete_not_assumed_skipped(data):
    c, _ = data
    c["issue_time"] += timedelta(seconds=1)
    r = calculate_coverage(**c)
    assert not r.complete and not r.windows
    assert "UNRESOLVED_PAST_OPEN_OCCASION" in {f.code for f in r.findings}


def test_before_decision_current_open_is_next(data):
    c, _ = data
    c["issue_time"] -= timedelta(minutes=1)
    # State was explicitly captured before the new issue, not a future fact.
    c["occasions"] = [replace(o, effective_at=c["issue_time"]) for o in c["occasions"]]
    c["domains"] = [
        replace(
            d,
            scheduled_date=date(2026, 2, 15),
            opportunities=tuple(
                replace(op, ordered_at=op.ordered_at - timedelta(days=i.interval_days))
                for op in d.opportunities
            ),
        )
        for d, i in zip(c["domains"], c["ingredients"], strict=True)
    ]
    r = calculate_coverage(**c)
    assert r.complete and all(w.next_occasion == date(2026, 2, 15) for w in r.windows)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("occasion_policy", None, "UNRESOLVED_OCCASION_POLICY"),
        ("expiry_policy", "unknown", "UNSUPPORTED_EXPIRY_POLICY"),
        ("max_horizon_days", 7, "UNSUPPORTED_HORIZON"),
    ],
)
def test_policy_and_explicit_cap(data, field, value, code):
    c, p = data
    c[field] = value
    r = calculate_coverage(**c)
    assert not r.complete and code in {f.code for f in r.findings}
    if field == "max_horizon_days":
        assert r.forecast_end is not None
        assert r.forecast_end.date() == date(2026, 3, 2)
        p["coverage"] = r
        assert result_row(project_multiday(**p)).projection is None


@pytest.mark.parametrize(
    "mode,code",
    [
        ("empty", "NO_FEASIBLE_RECEIPT_IN_COMPLETE_DOMAIN"),
        ("missing", "MISSING_OPPORTUNITY_DOMAIN"),
        ("evidence", "MISSING_EVIDENCE"),
    ],
)
def test_empty_complete_domain_distinct_from_missing(data, mode, code):
    c, _ = data
    c["domains"][0] = replace(
        c["domains"][0],
        **(
            {"opportunities": ()}
            if mode == "empty"
            else {"opportunities": None}
            if mode == "missing"
            else {"evidence": None}
        ),
    )
    r = calculate_coverage(**c)
    assert not r.complete and code in {f.code for f in r.findings}


@pytest.mark.parametrize(
    "cutoff,lead,complete",
    [("22:00", 720, True), ("21:59", 720, False), ("22:00", 721, False)],
)
def test_cutoff_lead_equality(data, cutoff, lead, complete):
    c, _ = data
    c["offers"][0] = c["offers"][0].model_copy(
        update={
            "order_cutoff": LocalCutoff(
                kind="LOCAL_TIME", local_time=time.fromisoformat(cutoff)
            ),
            "lead_time_minutes": lead,
        }
    )
    r = calculate_coverage(**c)
    assert r.complete is complete


def test_infeasible_first_slot_and_reliability_are_not_selection_rules(data):
    c, _ = data
    domain = c["domains"][0]
    op = domain.opportunities[0]
    bad = replace(
        op,
        id="too-early",
        arrival_at=op.ordered_at + timedelta(minutes=30),
        expiry_date=op.ordered_at.date() + timedelta(days=29),
    )
    c["domains"][0] = replace(domain, opportunities=(bad, op))
    c["offers"][0] = c["offers"][0].model_copy(
        update={"feasible_delivery_at": [bad.arrival_at, op.arrival_at]}
    )
    r = calculate_coverage(**c)
    assert r.complete and any(f.code == "MINIMUM_LEAD_TIME" for f in r.exclusions)
    c["offers"] = [
        o.model_copy(update={"recent_on_time_rate": D("0.1")}) for o in c["offers"]
    ]
    assert calculate_coverage(**c) == r


@pytest.mark.parametrize(
    "mode", ["day", "profile", "bucket", "dish", "late", "revision"]
)
def test_missing_later_data_retains_known_shortage(data, mode):
    _, p = data
    set_lot(p, "rice", quantity=D(0))
    f = p["forecasts"][2]
    if mode == "day":
        p["forecasts"].pop(2)
    elif mode == "profile":
        p["forecasts"][2] = replace(f, profile=())
    elif mode == "bucket":
        p["forecasts"][2] = replace(f, buckets=())
    elif mode == "dish":
        b = f.buckets[0]
        p["forecasts"][2] = replace(
            f, buckets=(ProjectedDemandBucket(b.start, b.end, {"chicken-rice": D(10)}),)
        )
    else:
        p["forecasts"][2] = replace(
            f,
            sources=tuple(
                (
                    k,
                    replace(
                        e,
                        **(
                            {"available_at": f.known_at + timedelta(days=1)}
                            if mode == "late"
                            else {"captured_revision": "other"}
                        ),
                    ),
                )
                for k, e in f.sources
            ),
        )
    r = project_multiday(**p)
    assert not r.complete
    assert any(
        b.kind == "SHORTAGE"
        and b.ingredient_id == "rice"
        and b.start.date() == date(2026, 2, 16)
        and b.quantity == 2
        for b in r.breaches
    )
    verified_until = result_row(r).verified_until
    assert verified_until is not None and verified_until.date() == date(2026, 2, 17)


def test_missing_ingredient_opening_does_not_erase_other_risk(data):
    _, p = data
    del p["opening_manifest"]["oil"]
    set_lot(p, "rice", quantity=D(0))
    r = project_multiday(**p)
    assert not r.complete and result_row(r, "oil").projection is None
    assert any(b.kind == "SHORTAGE" and b.ingredient_id == "rice" for b in r.breaches)


def test_partial_receipt_and_later_arrival_never_erase_shortage(data):
    _, p = data
    issue = p["coverage"].issue_time
    rice = next(l for l in p["opening_lots"] if l.ingredient_id == "rice")
    set_lot(p, "rice", initial_quantity=D(6), quantity=D(6))
    receipt = Receipt(
        id="receipt",
        delivery_id="fixed-rice",
        lot_id=rice.id,
        request_id="slip",
        quantity=D(6),
        received_at=rice.received_at,
        expiry_date=rice.expiry_date,
        remainder="EXPECTED",
        closing_counts={},
    )
    supply(p, issue + timedelta(days=5), received="6", receipts=[receipt])
    r = project_multiday(**p)
    assert r.complete
    totals = numbers(result_row(r).projection).ingredients[0]
    assert (
        totals.opening,
        totals.admitted,
        totals.allocated,
        totals.unmet,
        totals.closing,
    ) == (6, 4, 10, 18, 0)
    first = numbers(result_row(r).projection).first_shortages[0]
    assert first.start.date() == date(2026, 2, 19)
    assert any(b.start == first.start and b.quantity == 2 for b in r.breaches)


def test_cancelled_quantity_never_admitted(data):
    _, p = data
    supply(p, p["coverage"].issue_time + timedelta(days=2), quantity="0", cancelled="4")
    r = project_multiday(**p)
    assert r.complete and numbers(result_row(r).projection).ingredients[0].admitted == 0


def test_delayed_extra_assessment_storage_and_expiry(data):
    _, p = data
    arrival = p["coverage"].forecast_end + timedelta(hours=2)
    supply(p, arrival, quantity="5")
    r = project_multiday(**p)
    assert not r.complete and any(
        f.code == "DELAYED_COMMITMENT_BEYOND_ASSESSMENT" for f in r.findings
    )
    p["assessment_end"]["rice"] = arrival + timedelta(hours=1)
    p["storage"]["rice"] = D(4)
    r = project_multiday(**p)
    assert r.complete
    assert any(
        b.kind == "STORAGE"
        and b.start == arrival
        and b.quantity == 5
        and b.scope == "ASSESSMENT"
        for b in r.breaches
    )


def test_safety_and_receipt_storage(data):
    _, p = data
    p["safety"]["rice"] = D(1)
    p["storage"]["rice"] = D(28)
    arrival = datetime.fromisoformat("2026-02-16T10:00:00+08:00")
    supply(p, arrival)
    r = project_multiday(**p)
    assert r.complete and any(
        b.kind == "STORAGE" and b.quantity == 32 and b.start == arrival
        for b in r.breaches
    )
    p["supplies"] = []
    p["supply_manifest"] = []
    r = project_multiday(**p)
    assert any(
        b.kind == "SAFETY" and b.quantity == 0 and b.end.date() == date(2026, 3, 1)
        for b in r.breaches
    )


def test_midnight_expiry_and_fefo_id_tie(data):
    _, p = data
    rice = next(l for l in p["opening_lots"] if l.ingredient_id == "rice")
    p["opening_lots"] = [l for l in p["opening_lots"] if l.ingredient_id != "rice"] + [
        rice.model_copy(
            update={
                "id": key,
                "quantity": D(3),
                "initial_quantity": D(3),
                "expiry_date": date(2026, 2, 16),
            }
        )
        for key in ("z", "a")
    ]
    p["opening_manifest"]["rice"] = ["z", "a"]
    r = project_multiday(**p)
    assert r.complete
    row = numbers(result_row(r).projection)
    assert next(l for l in row.lots if l.key == "opening:a").allocated == 2
    assert next(l for l in row.lots if l.key == "opening:z").allocated == 0
    assert sum(e.quantity for e in row.expiries) == 4
    assert all(e.at.isoformat() == "2026-02-17T00:00:00+08:00" for e in row.expiries)
    assert row.ingredients[0].unmet == 26


@pytest.mark.parametrize(
    "at,complete",
    [
        ("2026-02-16T11:00:00+08:00", True),
        ("2026-02-16T11:15:00+08:00", False),
        ("2026-02-16T11:30:00+08:00", True),
    ],
)
def test_arrival_service_boundaries(data, at, complete):
    _, p = data
    set_lot(p, "rice", quantity=D(0))
    supply(p, datetime.fromisoformat(at))
    r = project_multiday(**p)
    assert r.complete is complete
    if complete:
        first = numbers(result_row(r).projection).buckets[0].ingredients[0]
        assert first.unmet == (0 if "11:00" in at else 2)


@pytest.mark.parametrize("name", ["safety", "storage", "opening_manifest"])
def test_explicit_zero_versus_missing(data, name):
    _, p = data
    del p[name]["rice"]
    assert not project_multiday(**p).complete


@pytest.mark.parametrize("kind", ["missing", "late", "mixed"])
def test_common_evidence_incomplete_not_safe(data, kind):
    _, p = data
    ev = p["evidence"]["supply"]
    if kind == "missing":
        del p["evidence"]["supply"]
    else:
        p["evidence"]["supply"] = replace(
            ev,
            **(
                {"available_at": ev.available_at + timedelta(days=1)}
                if kind == "late"
                else {"captured_revision": "other"}
            ),
        )
    r = project_multiday(**p)
    assert not r.complete and all(i.projection is None for i in r.ingredients)


def test_deterministic_order_immutability_and_decimal_context(data):
    c, p = data
    before = repr((c, p))
    expected = project_multiday(**p)
    assert repr((c, p)) == before
    for key in ("ingredients", "offers", "domains", "occasions", "suppliers"):
        c[key] = list(reversed(c[key]))
    assert calculate_coverage(**c) == p["coverage"]
    for key in ("forecasts", "ingredients", "menu_items", "recipes", "opening_lots"):
        p[key] = list(reversed(p[key]))
    with localcontext() as ctx:
        ctx.prec = 3
        assert project_multiday(**p) == expected


@pytest.mark.parametrize(
    "field,value", [("constraint_policy", None), ("fefo_policy", "EXPIRY_ID")]
)
def test_unknown_policy_incomplete(data, field, value):
    _, p = data
    p[field] = value
    assert not project_multiday(**p).complete


@pytest.mark.parametrize("quantity", [D(-1), D("NaN"), D("Infinity"), 1.5])
def test_invalid_quantity_rejected(data, quantity):
    _, p = data
    p["safety"]["rice"] = quantity
    with pytest.raises(ValueError):
        project_multiday(**p)


@pytest.mark.parametrize("mode", ["expiry", "midbucket", "lot_id"])
def test_unresolved_later_supply_retains_verified_earlier_shortage(data, mode):
    _, p = data
    set_lot(p, "rice", quantity=D(0))
    at = datetime.fromisoformat(
        "2026-02-18T11:15:00+08:00"
        if mode == "midbucket"
        else "2026-02-18T10:00:00+08:00"
    )
    supply(p, at)
    if mode != "midbucket":
        p["supplies"][0] = replace(
            p["supplies"][0],
            **(
                {"expiry_evidence": None}
                if mode == "expiry"
                else {"projected_lot_id": None}
            ),
        )
    r = project_multiday(**p)
    assert not r.complete
    assert any(
        b.kind == "SHORTAGE" and b.start.date() == date(2026, 2, 16) and b.quantity == 2
        for b in r.breaches
    )
    assert numbers(result_row(r).projection).ingredients[0].admitted == 0


def test_missing_constraint_does_not_hide_demonstrated_stock_shortage(data):
    _, p = data
    set_lot(p, "rice", quantity=D(0))
    del p["safety"]["rice"]
    r = project_multiday(**p)
    assert not r.complete and any(
        b.kind == "SHORTAGE" and b.ingredient_id == "rice" for b in r.breaches
    )


@pytest.mark.parametrize(
    "field,value",
    [("lead_time_minutes", -1), ("pack_size", D(0)), ("available_quantity", D("NaN"))],
)
def test_malformed_offer_rejected(data, field, value):
    c, _ = data
    c["offers"][0] = c["offers"][0].model_copy(update={field: value})
    with pytest.raises(ValueError):
        calculate_coverage(**c)


def test_complete_exclusion_of_unavailable_offer_with_unknown_terms(data):
    c, _ = data
    c["offers"][0] = c["offers"][0].model_copy(
        update={"current_status": "UNAVAILABLE", "pack_size": None}
    )
    r = calculate_coverage(**c)
    assert "NO_FEASIBLE_RECEIPT_IN_COMPLETE_DOMAIN" in {f.code for f in r.findings}
    assert "MISSING_OFFER_TERMS" not in {f.code for f in r.findings}


def test_midnight_bucket_consumes_before_expiry(data):
    _, p = data
    f = p["forecasts"][1]
    start = f.profile[0].start.replace(hour=23, minute=30)
    profile = (ServicePeriod(start, start + timedelta(minutes=30), D(1)),)
    buckets = allocate_service_buckets(
        {d: D(q) for d, q in F["daily_portions"].items()},
        p["menu_items"],
        target_date=f.target_date,
        profile=profile,
    )
    p["forecasts"][1] = replace(f, profile=profile, buckets=buckets)
    set_lot(
        p, "rice", quantity=D(3), initial_quantity=D(3), expiry_date=date(2026, 2, 16)
    )
    r = project_multiday(**p)
    n = numbers(result_row(r).projection)
    assert r.complete and n.buckets[0].ingredients[0].allocated == 2
    assert n.expiries[0].quantity == 1 and n.expiries[0].at == start + timedelta(
        minutes=30
    )


@pytest.mark.parametrize(
    "field", ["pack_size", "lead_time_minutes", "feasible_delivery_at"]
)
def test_missing_offer_terms_are_not_a_no_supplier_proof(data, field):
    c, _ = data
    c["offers"][0] = c["offers"][0].model_copy(update={field: None})
    r = calculate_coverage(**c)
    assert not r.complete and "MISSING_OFFER_TERMS" in {f.code for f in r.findings}
    assert not any(
        f.code == "NO_FEASIBLE_RECEIPT_IN_COMPLETE_DOMAIN" and f.source == "chicken"
        for f in r.findings
    )


@pytest.mark.parametrize("mode", ["late", "revision", "missing"])
def test_offer_provenance_does_not_certify_a_window(data, mode):
    c, _ = data
    ev = c["offer_evidence"]["chicken-offer"]
    if mode == "missing":
        del c["offer_evidence"]["chicken-offer"]
    else:
        c["offer_evidence"]["chicken-offer"] = replace(
            ev,
            **(
                {"available_at": ev.available_at + timedelta(seconds=1)}
                if mode == "late"
                else {"captured_revision": "different"}
            ),
        )
    r = calculate_coverage(**c)
    assert not r.complete and not any(w.ingredient_id == "chicken" for w in r.windows)


def test_unknown_supply_and_recipe_provenance_rejected(data):
    _, p = data
    p["supplies"] = []
    p["supply_manifest"] = ["unprovided"]
    assert not project_multiday(**p).complete
    p["supply_manifest"] = []
    p["recipe_manifest"].pop()
    r = project_multiday(**p)
    assert not r.complete and "RECIPE_MANIFEST_MISMATCH" in {f.code for f in r.findings}


def test_fractional_forecasts_never_round_to_packs(data):
    _, p = data
    for index, f in enumerate(p["forecasts"]):
        p["forecasts"][index] = replace(
            f,
            buckets=tuple(
                ProjectedDemandBucket(
                    b.start,
                    b.end,
                    {
                        i: D("0.123456789") if i == "chicken-rice" else D(0)
                        for i in b.expected_portions
                    },
                )
                for b in f.buckets
            ),
        )
    with localcontext() as ctx:
        ctx.prec = 2
        r = project_multiday(**p)
    # Fourteen services * 0.123456789 portions * 0.100 kg per portion.
    assert r.complete and numbers(result_row(r).projection).ingredients[
        0
    ].required == D("0.1728395046")


def test_equivalent_bucket_order_and_zero_stock_manifest(data):
    _, p = data
    p["opening_lots"] = [l for l in p["opening_lots"] if l.ingredient_id != "tofu"]
    p["opening_manifest"]["tofu"] = []
    r = project_multiday(**p)
    assert (
        r.complete
        and numbers(result_row(r, "tofu").projection).ingredients[0].opening == 0
    )
    f = p["forecasts"][1]
    start = f.profile[0].start
    profile = (ServicePeriod(start, start + timedelta(hours=1), D(1)),)
    buckets = allocate_service_buckets(
        {i: D(q) for i, q in F["daily_portions"].items()},
        p["menu_items"],
        target_date=f.target_date,
        profile=profile,
    )
    p["forecasts"][1] = replace(f, profile=profile, buckets=buckets)
    expected = project_multiday(**p)
    p["forecasts"][1] = replace(f, profile=profile, buckets=tuple(reversed(buckets)))
    assert project_multiday(**p) == expected


def test_receipt_boundary_ledger_has_exact_independent_balance(data):
    _, p = data
    arrival = datetime.fromisoformat("2026-02-16T10:00:00+08:00")
    supply(p, arrival)
    result = project_multiday(**p)
    movements = result_row(result).movements
    receipt = next(m for m in movements if m.at == arrival)
    assert (receipt.opening, receipt.admitted, receipt.closing) == (28, 4, 32)
    service = next(m for m in movements if m.at == arrival.replace(hour=11, minute=30))
    assert (service.opening, service.allocated, service.closing) == (32, 2, 30)
    for m in movements:
        assert Fraction(m.opening) + Fraction(m.admitted) == Fraction(
            m.allocated
        ) + Fraction(m.expired) + Fraction(m.closing)


def test_coverage_catalogue_reference_must_match_projection(data):
    _, p = data
    p["coverage"] = replace(
        p["coverage"],
        evidence=tuple(
            (k, replace(e, reference="other-catalogue") if k == "catalogue" else e)
            for k, e in p["coverage"].evidence
        ),
    )
    r = project_multiday(**p)
    assert not r.complete and any(
        f.code == "COVERAGE_CATALOGUE_MISMATCH" for f in r.findings
    )


def test_ambiguous_unadjusted_forecast_is_not_silently_accepted(data):
    _, p = data
    p["forecasts"][1] = replace(p["forecasts"][1], base_reference="already-adjusted")
    r = project_multiday(**p)
    assert not r.complete and "AMBIGUOUS_UNADJUSTED_FORECAST" in {
        f.code for f in r.findings
    }


@pytest.mark.parametrize(
    "field,value", [("available_quantity", 1.5), ("lead_time_minutes", True)]
)
def test_raw_offer_model_copy_cannot_coerce_invalid_numbers(data, field, value):
    c, _ = data
    c["offers"][0] = c["offers"][0].model_copy(update={field: value})
    with pytest.raises(ValueError):
        calculate_coverage(**c)

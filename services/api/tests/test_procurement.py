"""Independent cash/constraint oracles; no database fixture or optimiser oracle."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from src.inventory_projection import ExpectedSupply, SourceEvidence
from src.operations_schemas import Delivery, Receipt
from src.procurement import (
    EVIDENCE,
    Cash,
    DatedRequirement,
    OrderingOpportunity,
    ProcurementInputs,
    ProjectionInputs,
    PurchaseCandidate,
    PurchaseLine,
    search_procurement,
    validate_candidate,
)
from src.requirements import calculate_requirements
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
    SupplierOffer,
)
from src.service_buckets import ServicePeriod, allocate_service_buckets

D = Decimal
dt = datetime.fromisoformat
FIXTURES = Path(__file__).parent / "fixtures"


def needs(inv):
    return tuple(
        DatedRequirement(
            b.start,
            b.end,
            calculate_requirements(
                b.expected_portions,
                inv["menu_items"],
                inv["ingredients"],
                inv["recipes"],
            ),
        )
        for b in inv["buckets"]
    )


@pytest.fixture
def reference():
    f = json.loads((FIXTURES / "procurement_v1.json").read_text())
    cat = json.loads((FIXTURES / f["catalogue_fixture"]).read_text())
    menu = [MenuItem.model_validate(r) for r in cat["menu_items"]]
    ingredients = [Ingredient.model_validate(r) for r in cat["ingredients"]]
    recipes = [RecipeItem.model_validate(r) for r in cat["recipes"]]
    profile = [
        ServicePeriod(dt(r["start"]), dt(r["end"]), D(r["weight"]))
        for r in json.loads((FIXTURES / f["profile_fixture"]).read_text())["periods"]
    ]
    issue = dt(f["issue_time"])
    evidence = SourceEvidence(
        f["fixture_id"], dt(f["available_at"]), f["captured_revision"]
    )
    lots = [
        EstimatedInventoryLot(
            id=i.id,
            ingredient_id=i.id,
            unit=i.unit,
            received_at=dt(f["opening_received_at"]),
            expiry_date=date.fromisoformat(f["opening_expiry"]),
            initial_quantity=D(f["opening"][i.id]),
            quantity=D(f["opening"][i.id]),
            counted_at=issue,
            as_of=issue,
            coverage_start=issue,
            coverage_complete=True,
            status="ACTIVE",
            unallocated_consumption=D(0),
        )
        for i in ingredients
    ]
    inv: ProjectionInputs = {
        "opening_lots": lots,
        "buckets": allocate_service_buckets(
            {k: D(q) for k, q in f["daily_forecast"].items()},
            menu,
            target_date=date.fromisoformat(f["target_date"]),
            profile=profile,
        ),
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "supplies": [],
        "as_of": issue,
        "target_date": date.fromisoformat(f["target_date"]),
        "horizon_end": dt(f["horizon_end"]),
        "known_at": dt(f["known_at"]),
        "captured_revision": f["captured_revision"],
        "opening_manifest": {i.id: [i.id] for i in ingredients},
        "supply_manifest": [],
        "recipe_manifest": [(r.menu_item_id, r.ingredient_id) for r in recipes],
        "service_profile": profile,
        "evidence": {
            k: evidence
            for k in (
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
    offers = [
        SupplierOffer.model_validate(
            {
                **f["supplier_terms"],
                **o,
                "observed_at": issue,
                "feasible_delivery_at": [f["arrival_at"]],
            }
        )
        for o in f["offers"]
    ]
    return ProcurementInputs(
        inventory=inv,
        issue_time=issue,
        requirements=needs(inv),
        suppliers=[Supplier(id="fresh", name="Fresh Foods")],
        offers=offers,
        approved_offer_manifest=[
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ],
        opportunities=[
            OrderingOpportunity(
                o.id,
                o.id,
                issue,
                dt(f["arrival_at"]),
                "NORMAL",
                date.fromisoformat(f["expiry_date"]),
                evidence,
            )
            for o in offers
        ],
        safety={k: D(q) for k, q in f["safety"].items()},
        storage={k: D(q) for k, q in f["storage"].items()},
        budget=D(f["budget"]),
        fee_policy=f["fee_policy"],
        tie_policy=f["tie_policy"],
        expiry_policy=f["expiry_policy"],
        cash_policy=f["cash_policy"],
        policy_evidence={k: evidence for k in EVIDENCE},
        offer_evidence={o.id: evidence for o in offers},
        max_packs=f["max_packs"],
        work_limit=f["work_limit"],
    )


def with_offers(p, offers, opportunities=None):
    ev = p.inventory["evidence"]["supply"]
    if opportunities is None:
        opportunities = [
            OrderingOpportunity(
                o.id,
                o.id,
                p.issue_time,
                o.feasible_delivery_at[0],
                "NORMAL",
                o.feasible_delivery_at[0].date()
                + timedelta(days=o.shelf_life_days_on_arrival),
                ev,
            )
            for o in offers
        ]
    return replace(
        p,
        offers=offers,
        opportunities=opportunities,
        suppliers=[
            Supplier(id=s, name=s) for s in sorted({o.supplier_id for o in offers})
        ],
        approved_offer_manifest=[
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ],
        offer_evidence={o.id: ev for o in offers},
        max_packs={
            op.id: int(
                Fraction(
                    next(o for o in offers if o.id == op.offer_id).available_quantity
                )
                // Fraction(next(o for o in offers if o.id == op.offer_id).pack_size)
            )
            for op in opportunities
        },
        work_limit=10000,
    )


@pytest.fixture
def small(reference):
    p = reference
    inv = p.inventory.copy()
    profile = [
        ServicePeriod(
            dt("2026-02-16T11:00+08:00"), dt("2026-02-16T11:30+08:00"), D(".6")
        ),
        ServicePeriod(
            dt("2026-02-16T11:30+08:00"), dt("2026-02-16T12:00+08:00"), D(".4")
        ),
    ]
    inv["service_profile"] = profile
    inv["buckets"] = allocate_service_buckets(
        {d.id: D(25 if d.id == "tofu-bowl" else 0) for d in inv["menu_items"]},
        inv["menu_items"],
        target_date=inv["target_date"],
        profile=profile,
    )
    inv["opening_lots"] = [
        l.model_copy(
            update={
                "quantity": D(2 if l.ingredient_id == "vegetables" else 100),
                "initial_quantity": D(2 if l.ingredient_id == "vegetables" else 100),
            }
        )
        for l in inv["opening_lots"]
    ]
    offer = p.offers[0].model_copy(
        update={
            "id": "fresh-vegetables",
            "ingredient_id": "vegetables",
            "unit_price": D("9.50"),
            "available_quantity": D(2),
        }
    )
    return with_offers(
        replace(
            p,
            inventory=inv,
            requirements=needs(inv),
            storage={i.id: D(200) for i in inv["ingredients"]},
        ),
        [offer],
    )


def candidate(p, quantity="1", **changes):
    return PurchaseCandidate(
        (PurchaseLine(p.opportunities[0].id, D(quantity), "kg"),), **changes
    )


def codes(result):
    return {v.code for v in (*result.findings, *getattr(result, "violations", ()))}


def stock(p, quantity):
    inv = p.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"quantity": D(quantity)})
        if l.ingredient_id == "vegetables"
        else l
        for l in inv["opening_lots"]
    ]
    return replace(p, inventory=inv)


def test_reference_cash_and_all_ingredient_conservation(reference):
    r = search_procurement(reference)
    assert r.status == "OPTIMAL_IN_DOMAIN" and r.search_complete and r.optimal_in_domain
    assert r.evaluated == r.domain_size == 36
    assert r.candidate is not None
    assert [(l.opportunity_id, l.quantity) for l in r.candidate.lines] == [
        ("fresh-chicken", D(8)),
        ("fresh-noodles", D(3)),
    ]
    assert r.candidate.claimed_cash == Cash(D("55.50"), D(5), D(0), D("60.50"))
    v = validate_candidate(reference, r.candidate)
    assert v.feasible and v.complete
    assert v.projection is not None and v.projection.ingredients is not None
    totals = {r.ingredient_id: r for r in v.projection.ingredients}
    assert len(totals) == 8
    assert totals["chicken"].closing == D(".4") and totals["noodles"].closing == 0
    for row in v.projection.ingredients:
        assert Fraction(row.opening) + Fraction(row.admitted) == Fraction(
            row.allocated
        ) + Fraction(row.expired) + Fraction(row.closing)
        assert row.unmet == 0


def test_no_purchase_and_no_offer_domain(small):
    p = with_offers(stock(small, "2.5"), [])
    r = search_procurement(p)
    assert r.status == "OPTIMAL_IN_DOMAIN" and r.domain_size == r.evaluated == 1
    assert r.candidate is not None
    assert r.candidate.lines == () and r.candidate.claimed_cash == Cash(
        D(0), D(0), D(0), D(0)
    )


def test_pack_rounding_and_moq_independent(small):
    p = with_offers(
        small,
        [
            small.offers[0].model_copy(
                update={
                    "moq": D("1.1"),
                    "pack_size": D(".5"),
                    "available_quantity": D(2),
                }
            )
        ],
    )
    r = search_procurement(p)
    assert r.candidate is not None and r.candidate.claimed_cash is not None
    assert r.candidate.lines[0].quantity == D("1.5")
    assert r.candidate.claimed_cash.total == D("19.25")  # 1.5*9.5+5
    assert "MOQ" in codes(validate_candidate(p, candidate(p, "1")))
    assert "PACK_MULTIPLE" in codes(validate_candidate(p, candidate(p, "1.2")))


def test_split_and_shared_offer_capacity(small):
    p = stock(small, "0")
    a = p.offers[0].model_copy(update={"available_quantity": D(2), "unit_price": D(1)})
    b = a.model_copy(
        update={"id": "pantry-vegetables", "supplier_id": "pantry", "unit_price": D(2)}
    )
    p = with_offers(p, [a, b])
    r = search_procurement(p)
    assert r.candidate is not None and r.candidate.claimed_cash is not None
    assert [(l.opportunity_id, l.quantity) for l in r.candidate.lines] == [
        (a.id, D(2)),
        (b.id, D(1)),
    ]
    assert r.candidate.claimed_cash.total == 14  # 2*1+1*2+two shipments*5
    op = p.opportunities[0]
    second = replace(op, id="fresh-second", arrival_at=dt("2026-02-16T11:30+08:00"))
    a = a.model_copy(
        update={"feasible_delivery_at": [op.arrival_at, second.arrival_at]}
    )
    p = with_offers(p, [a], [op, second])
    v = validate_candidate(
        p,
        PurchaseCandidate(
            (PurchaseLine(op.id, D(2), "kg"), PurchaseLine(second.id, D(1), "kg"))
        ),
    )
    assert "SHARED_OFFER_CAPACITY" in codes(v)


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"order_cutoff": {"kind": "LOCAL_TIME", "local_time": "21:59:00"}},
            "ORDER_CUTOFF",
        ),
        ({"lead_time_minutes": 601}, "LEAD_TIME"),
        ({"feasible_delivery_at": []}, "DELIVERY_SLOT"),
        ({"current_status": "UNAVAILABLE"}, "OFFER_UNAVAILABLE"),
    ],
)
def test_known_supplier_constraints(small, change, code):
    o = SupplierOffer.model_validate({**small.offers[0].model_dump(), **change})
    p = replace(small, offers=[o])
    assert code in codes(validate_candidate(p, candidate(p)))
    r = search_procurement(p)
    assert r.status == "INFEASIBLE_IN_DOMAIN" and r.search_complete
    assert code in dict(r.rejection_counts)


@pytest.mark.parametrize(
    "arrival,feasible", [("11:00", True), ("11:30", False), ("12:00", False)]
)
def test_late_supply_never_erases_shortage(small, arrival, feasible):
    p = stock(small, "1")
    at = dt(f"2026-02-16T{arrival}+08:00")
    o = p.offers[0].model_copy(update={"feasible_delivery_at": [at]})
    p = with_offers(p, [o])
    v = validate_candidate(p, candidate(p, "2"))
    assert v.feasible is feasible
    if not feasible:
        assert "TIMELY_DEMAND_UNMET" in codes(v)
        assert v.projection is not None and v.projection.first_shortages is not None
        shortage = v.projection.first_shortages[0]
        assert shortage.start == dt("2026-02-16T11:00+08:00")


def test_expiry_before_service_and_explicit_expiry_policy(small):
    p = stock(small, "1")
    o = p.offers[0].model_copy(
        update={
            "feasible_delivery_at": [dt("2026-02-15T23:00+08:00")],
            "lead_time_minutes": 0,
            "shelf_life_days_on_arrival": 0,
        }
    )
    p = with_offers(p, [o])
    v = validate_candidate(p, candidate(p, "2"))
    assert not v.feasible and "TIMELY_DEMAND_UNMET" in codes(v)
    assert v.projection is not None and v.projection.expiries is not None
    assert sum(e.quantity for e in v.projection.expiries) == 2
    p = replace(
        p, opportunities=[replace(p.opportunities[0], expiry_date=date(2026, 2, 20))]
    )
    assert "EXPECTED_EXPIRY_POLICY" in codes(validate_candidate(p, candidate(p, "2")))


@pytest.mark.parametrize(
    "constraint,value,code",
    [
        ("budget", "14.49", "NEW_ORDER_BUDGET"),
        ("storage", "2.9", "STORAGE_CAPACITY"),
        ("safety", ".6", "SAFETY_SHORTFALL"),
    ],
)
def test_explicit_constraints(small, constraint, value, code):
    change = (
        D(value)
        if constraint == "budget"
        else {**getattr(small, constraint), "vegetables": D(value)}
    )
    p = replace(small, **{constraint: change})
    assert code in codes(validate_candidate(p, candidate(p)))


def test_storage_before_consumption_and_at_separate_gap_arrivals(small):
    p = replace(small, storage={**small.storage, "vegetables": D("2.9")})
    v = validate_candidate(p, candidate(p))
    assert "STORAGE_CAPACITY" in codes(v)  # peak3, although closing0.5
    assert v.projection is not None and v.projection.ingredients is not None
    at = dt("2026-02-16T11:30+08:00")
    p = with_offers(p, [p.offers[0].model_copy(update={"feasible_delivery_at": [at]})])
    assert validate_candidate(p, candidate(p)).feasible  # prior bucket consumed1.5


@pytest.mark.parametrize("cancelled,expected_new", [(False, "0"), (True, "1")])
def test_partial_receipt_and_cancellation_once(small, cancelled, expected_new):
    p = stock(small, "2")
    inv = p.inventory.copy()
    lot = next(l for l in inv["opening_lots"] if l.ingredient_id == "vegetables")
    lot = lot.model_copy(
        update={"initial_quantity": D(6)}
    )  # six received, four already used
    inv["opening_lots"] = [lot if l.id == lot.id else l for l in inv["opening_lots"]]
    receipt = Receipt(
        id="receipt6",
        delivery_id="fixed10",
        lot_id=lot.id,
        request_id="slip",
        quantity=D(6),
        received_at=lot.received_at,
        expiry_date=lot.expiry_date,
        remainder="EXPECTED",
        closing_counts={},
    )
    d = Delivery(
        id="fixed10",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(10),
        received_quantity=D(6),
        cancelled_quantity=D(4 if cancelled else 0),
        outstanding_quantity=D(0 if cancelled else 4),
        ordered_at=lot.received_at - timedelta(hours=1),
        expected_at=dt("2026-02-16T08:00+08:00"),
        receipts=[receipt],
    )
    inv["supplies"] = [ExpectedSupply(d, date(2026, 2, 18), inv["evidence"]["supply"])]
    inv["supply_manifest"] = [d.id]
    p = replace(p, inventory=inv)
    r = search_procurement(p)
    assert r.candidate is not None and r.validation is not None
    assert r.validation.projection is not None
    assert r.validation.projection.ingredients is not None
    assert sum((l.quantity for l in r.candidate.lines), D(0)) == D(expected_new)
    row = next(
        x
        for x in r.validation.projection.ingredients
        if x.ingredient_id == "vegetables"
    )
    assert row.opening == 2 and row.admitted == (1 if cancelled else 4)
    assert row.closing == D(".5" if cancelled else "3.5")


@pytest.mark.parametrize(
    "field",
    [
        "unit_price",
        "available_quantity",
        "moq",
        "pack_size",
        "lead_time_minutes",
        "feasible_delivery_at",
        "shelf_life_days_on_arrival",
        "delivery_fee_sgd",
        "emergency_fee_sgd",
    ],
)
def test_unknown_offer_fields_incomplete(small, field):
    p = replace(small, offers=[small.offers[0].model_copy(update={field: None})])
    r = search_procurement(p)
    assert r.status == "INCOMPLETE" and r.candidate is None and not r.search_complete
    assert "MISSING_REQUIRED_DATA" in codes(r)


@pytest.mark.parametrize(
    "field",
    [
        "fee_policy",
        "tie_policy",
        "expiry_policy",
        "cash_policy",
        "budget",
        "opportunities",
    ],
)
def test_unknown_policy_and_scope_incomplete(small, field):
    r = search_procurement(replace(small, **{field: None}))
    assert r.status == "INCOMPLETE" and r.candidate is None


def test_missing_coverage_and_provenance_not_zero(small):
    inv = small.inventory.copy()
    inv["opening_manifest"] = {
        k: v for k, v in inv["opening_manifest"].items() if k != "vegetables"
    }
    cases = [
        replace(small, inventory=inv),
        replace(small, policy_evidence={}),
        replace(small, offer_evidence={}),
        replace(small, requirements=[]),
        replace(small, safety={}),
        replace(small, approved_offer_manifest=[]),
        replace(
            small, opportunities=[replace(small.opportunities[0], expiry_evidence=None)]
        ),
    ]
    for p in cases:
        r = search_procurement(p)
        v = validate_candidate(p, PurchaseCandidate(()))
        assert r.status == "INCOMPLETE" and r.candidate is None
        assert not v.complete and v.feasible is v.cash is v.projection is None


def test_complete_infeasibility_and_search_limit_incumbent(small):
    r = search_procurement(replace(small, budget=D(0)))
    assert r.status == "INFEASIBLE_IN_DOMAIN" and r.evaluated == r.domain_size == 3
    assert r.search_complete and not r.optimal_in_domain and r.candidate is None
    assert "NEW_ORDER_BUDGET" in dict(r.rejection_counts)
    r = search_procurement(replace(small, work_limit=2))
    assert (
        r.status == "INCOMPLETE" and not r.search_complete and not r.optimal_in_domain
    )
    assert r.candidate is r.validation is None and r.diagnostic_incumbent is not None
    assert r.diagnostic_incumbent.claimed_cash is not None
    assert r.diagnostic_incumbent.claimed_cash.total == D("14.50")
    assert codes(r) == {"SEARCH_LIMIT_REACHED"}


def test_deterministic_ties_reliability_and_no_mutation(small):
    a = small.offers[0]
    b = a.model_copy(
        update={
            "id": "pantry-vegetables",
            "supplier_id": "pantry",
            "recent_on_time_rate": D(1),
        }
    )
    p = with_offers(small, [a, b])
    before = repr(p)
    expected = search_procurement(p)
    assert expected.candidate is not None
    assert expected.candidate.lines[0].opportunity_id == "fresh-vegetables"
    assert search_procurement(p) == expected and repr(p) == before
    p = replace(
        p,
        offers=[
            b.model_copy(update={"recent_on_time_rate": D(0)}),
            a.model_copy(update={"recent_on_time_rate": None}),
        ],
        opportunities=list(reversed(p.opportunities)),
    )
    with localcontext() as ctx:
        ctx.prec = 2
        assert search_procurement(p) == expected


@pytest.mark.parametrize(
    "line,code",
    [
        (PurchaseLine("not-an-offer", D(1), "kg"), "UNKNOWN_OPPORTUNITY"),
        (PurchaseLine("fresh-vegetables", D(-1), "kg"), "INVALID_QUANTITY"),
        (PurchaseLine("fresh-vegetables", D("NaN"), "kg"), "INVALID_QUANTITY"),
        (PurchaseLine("fresh-vegetables", D("Infinity"), "kg"), "INVALID_QUANTITY"),
        (PurchaseLine("fresh-vegetables", D(1), "pieces"), "UNIT_MISMATCH"),
        (PurchaseLine("fresh-vegetables", D(3), "kg"), "SHARED_OFFER_CAPACITY"),
    ],
)
def test_tampered_lines_independently_rejected(small, line, code):
    assert code in codes(validate_candidate(small, PurchaseCandidate((line,))))


def test_cash_tampering_duplicate_and_validator_does_not_search(small, monkeypatch):
    def forbidden(*args):
        pytest.fail("Independent validation invoked optimiser")

    monkeypatch.setattr("src.procurement.search_procurement", forbidden)
    c = candidate(small, claimed_cash=Cash(D(0), D(0), D(0), D(0)))
    assert "CASH_MISMATCH" in codes(validate_candidate(small, c))
    assert "DUPLICATE_LINE" in codes(
        validate_candidate(small, PurchaseCandidate(c.lines * 2))
    )
    assert validate_candidate(small, candidate(small)).feasible


def test_emergency_exclusive_once_per_group(reference):
    p = replace(
        reference,
        opportunities=[replace(o, kind="EMERGENCY") for o in reference.opportunities],
    )
    r = search_procurement(p)
    assert r.candidate is not None
    assert r.candidate.claimed_cash == Cash(D("55.5"), D(5), D(12), D("72.5"))
    mixed = replace(
        reference,
        opportunities=[
            replace(reference.opportunities[0], kind="EMERGENCY"),
            reference.opportunities[1],
        ],
    )
    mixed_result = search_procurement(mixed)
    assert mixed_result.candidate is not None
    assert mixed_result.candidate.claimed_cash == r.candidate.claimed_cash


@pytest.mark.parametrize(
    "arrival,code",
    [
        ("2026-02-16T11:15+08:00", "UNSUPPORTED_MID_BUCKET_ARRIVAL"),
        ("2026-02-15T22:00+08:00", "UNSUPPORTED_ARRIVAL_AT_OR_BEFORE_OPENING"),
    ],
)
def test_unsupported_timing_is_incomplete(small, arrival, code):
    p = with_offers(
        small,
        [small.offers[0].model_copy(update={"feasible_delivery_at": [dt(arrival)]})],
    )
    assert code in codes(search_procurement(p))


def test_invalid_domain_and_quantities(small):
    with pytest.raises(ValueError, match="every pack"):
        search_procurement(replace(small, max_packs={small.opportunities[0].id: 1}))
    for value in (D(-1), D("NaN"), D("Infinity"), 1.0):
        with pytest.raises(ValueError):
            search_procurement(replace(small, budget=value))
    for limit in (0, -1, True):
        with pytest.raises(ValueError):
            search_procurement(replace(small, work_limit=limit))


def test_conflicting_fees_and_expiry_evidence(reference):
    offers = [
        reference.offers[0],
        reference.offers[1].model_copy(update={"delivery_fee_sgd": D(6)}),
    ]
    assert "CONFLICTING_GROUP_FEES" in codes(
        search_procurement(replace(reference, offers=offers))
    )
    ops = [
        replace(reference.opportunities[0], expiry_date=None),
        reference.opportunities[1],
    ]
    assert "MISSING_EXPECTED_EXPIRY" in codes(
        search_procurement(replace(reference, opportunities=ops))
    )


def test_explicit_zero_opening_is_complete_but_missing_is_not(small):
    inv = small.inventory.copy()
    inv["opening_lots"] = []
    inv["opening_manifest"] = {i.id: [] for i in inv["ingredients"]}
    inv["buckets"] = allocate_service_buckets(
        {d.id: D(0) for d in inv["menu_items"]},
        inv["menu_items"],
        target_date=inv["target_date"],
        profile=inv["service_profile"],
    )
    p = replace(small, inventory=inv, requirements=needs(inv))
    result = search_procurement(p)
    assert result.candidate is not None and result.candidate.lines == ()
    inv["opening_manifest"] = {}
    assert search_procurement(p).status == "INCOMPLETE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", D("NaN")),
        ("available_quantity", D(-1)),
        ("pack_size", D(0)),
        ("moq", 1.0),
        ("lead_time_minutes", -1),
        ("shelf_life_days_on_arrival", -1),
        ("recent_on_time_rate", D("1.1")),
        ("ingredient_id", "UNKNOWN"),
        ("supplier_id", "unapproved"),
    ],
)
def test_invalid_offer_inputs(small, field, value):
    with pytest.raises(ValueError):
        search_procurement(
            replace(small, offers=[small.offers[0].model_copy(update={field: value})])
        )


@pytest.mark.parametrize("mode", ["late", "revision", "offer_clock"])
def test_frozen_evidence_checks(small, mode):
    p = small
    key = p.offers[0].id
    ev = p.offer_evidence[key]
    if mode == "late":
        p = replace(
            p,
            offer_evidence={
                key: replace(
                    ev, available_at=p.inventory["known_at"] + timedelta(seconds=1)
                )
            },
        )
    elif mode == "revision":
        p = replace(
            p, offer_evidence={key: replace(ev, captured_revision="another-capture")}
        )
    else:
        p = replace(
            p,
            offers=[
                p.offers[0].model_copy(
                    update={
                        "observed_at": p.inventory["known_at"] + timedelta(seconds=1)
                    }
                )
            ],
        )
    assert search_procurement(p).status == "INCOMPLETE"


def test_cutoff_and_lead_equality_supported(small):
    o = small.offers[0].model_copy(update={"lead_time_minutes": 600})
    data = o.model_dump()
    data["order_cutoff"] = {"kind": "LOCAL_TIME", "local_time": "22:00:00"}
    p = replace(small, offers=[SupplierOffer.model_validate(data)])
    assert validate_candidate(p, candidate(p)).feasible


def test_fractional_money_and_purchase_precision_boundary(small):
    o = small.offers[0].model_copy(
        update={
            "pack_size": D(".001"),
            "moq": D(0),
            "available_quantity": D(".001"),
            "unit_price": D("1.12345678901234567890123456789"),
        }
    )
    p = with_offers(stock(small, "2.499"), [o])
    with localcontext() as ctx:
        ctx.prec = 2
        v = validate_candidate(p, candidate(p, ".001"))
    assert v.feasible and v.cash is not None
    assert v.cash.acquisition == D(".00112345678901234567890123456789")
    assert v.cash.total == D("5.00112345678901234567890123456789")
    o = o.model_copy(update={"pack_size": D(".0001"), "available_quantity": D(".0001")})
    p = with_offers(stock(p, "2.4999"), [o])
    v = validate_candidate(p, candidate(p, ".0001"))
    assert not v.complete and v.feasible is None
    assert codes(v) == {"UNSUPPORTED_PURCHASE_PRECISION"}


def test_new_capacity_not_reduced_by_old_commitments(small):
    p = stock(small, "0")
    inv = p.inventory.copy()
    d = Delivery(
        id="old",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(1),
        outstanding_quantity=D(1),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        receipts=[],
        ordered_at=p.issue_time - timedelta(hours=1),
        expected_at=dt("2026-02-16T08:00+08:00"),
    )
    inv["supplies"] = [ExpectedSupply(d, date(2026, 2, 18), inv["evidence"]["supply"])]
    inv["supply_manifest"] = [d.id]
    p = replace(p, inventory=inv)
    r = search_procurement(p)
    assert r.candidate is not None
    assert r.candidate.lines[0].quantity == 2  # capacity2 is NEW, not 2 minus old1


def test_fee_charged_per_arrival_and_storage_gap_peak(small):
    o = small.offers[0]
    first = small.opportunities[0]
    second = replace(first, id="second-slot", arrival_at=dt("2026-02-16T09:00+08:00"))
    o = o.model_copy(
        update={"feasible_delivery_at": [first.arrival_at, second.arrival_at]}
    )
    p = with_offers(small, [o], [first, second])
    p = replace(p, storage={**p.storage, "vegetables": D("3.9")})
    v = validate_candidate(
        p,
        PurchaseCandidate(
            (PurchaseLine(first.id, D(1), "kg"), PurchaseLine(second.id, D(1), "kg"))
        ),
    )
    assert v.cash == Cash(D(19), D(10), D(0), D(29))
    assert "STORAGE_CAPACITY" in codes(v)  # both pre-service receipts peak at4


def test_large_domain_work_limit_without_materializing_pools(small):
    o = small.offers[0].model_copy(
        update={"available_quantity": D("100000000000000000000")}
    )
    p = replace(with_offers(small, [o]), work_limit=1)
    r = search_procurement(p)
    assert r.evaluated == 1 and r.domain_size == 100000000000000000001
    assert codes(r) == {"SEARCH_LIMIT_REACHED"}


def test_unsupported_future_order_and_missing_expiry(small):
    op = small.opportunities[0]
    p = replace(
        small,
        opportunities=[replace(op, ordered_at=op.ordered_at + timedelta(minutes=1))],
    )
    assert "UNSUPPORTED_ORDER_TIME" in codes(search_procurement(p))
    p = replace(small, issue_time=small.issue_time + timedelta(minutes=1))
    assert "UNSUPPORTED_ISSUE_OPENING" in codes(search_procurement(p))


def test_invalid_claimed_cash_never_raises_decimal_signal(small):
    v = validate_candidate(
        small, candidate(small, claimed_cash=Cash(D("sNaN"), D(0), D(0), D(0)))
    )
    assert "INVALID_CASH" in codes(v) and v.feasible is False

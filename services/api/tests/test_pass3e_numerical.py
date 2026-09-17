"""Pass 3E numerical checks using Backend-owned fixture records, without a DB."""

from dataclasses import replace
from datetime import UTC, date, timedelta
from decimal import Decimal
from itertools import product

import pytest
from test_procurement import candidate, codes, dt, needs, stock, with_offers
from test_procurement import (
    reference as reference,  # noqa: PLC0414 -- pytest fixture registration
)
from test_procurement import (
    small as small,  # noqa: PLC0414 -- pytest fixture registration
)

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.inventory_projection import (
    FEFO_POLICY,
    ExpectedSupply,
    SourceEvidence,
    _expiry,
    project_inventory,
)
from src.operations_schemas import Delivery
from src.procurement import (
    EVIDENCE,
    SEARCH_POLICY,
    TIE_POLICY,
    Cash,
    OrderingOpportunity,
    PurchaseCandidate,
    search_procurement,
    validate_candidate,
)
from src.procurement_contracts import _build, first_slice_seed_rows
from src.schemas import Supplier
from src.service_buckets import ServicePeriod, allocate_service_buckets

D = Decimal


@pytest.fixture
def full(reference):
    recorded = dt("2026-09-17T00:00+08:00")
    rows = first_slice_seed_rows(recorded)
    contract = _build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    )
    policy, domain = contract.policy.payload, contract.domain
    inv = reference.inventory.copy()
    ev = SourceEvidence(
        "synthetic/pass3e/" + contract.policy.id, recorded, domain.source_revision
    )
    inv.update(
        known_at=recorded,
        captured_revision=domain.source_revision,
        evidence={key: ev for key in inv["evidence"]},
        fixture_fefo=policy.fefo_policy,
        horizon_end=policy.horizon_end,
    )
    # Explicit historical v3 lots, not a claim that current live seed has these expiries.
    lots = [
        l.model_copy(
            update={
                "id": l.ingredient_id + "-01",
                "quantity": D(12) if l.ingredient_id == "chicken" else l.quantity,
                "initial_quantity": D(12)
                if l.ingredient_id == "chicken"
                else l.quantity,
            }
        )
        for l in inv["opening_lots"]
    ]
    lots.append(
        lots[0].model_copy(
            update={
                "id": "chicken-02",
                "quantity": D(5),
                "initial_quantity": D(5),
                "received_at": dt("2026-02-15T12:00+08:00"),
                "expiry_date": date(2026, 2, 20),
            }
        )
    )
    assert {l.id for l in lots} == set(domain.payload.opening_lot_ids)
    inv["opening_lots"] = lots
    inv["opening_manifest"] = {
        i.id: [l.id for l in lots if l.ingredient_id == i.id]
        for i in inv["ingredients"]
    }
    history = [
        DailySalesObservation(
            row.service_date,
            row.available_at,
            row.revision,
            row.portions,
            row.promotion,
            row.censored,
        )
        for row in contract.forecast_input.payload.history
    ]
    forecast = seasonal_baseline(
        history,
        inv["menu_items"],
        issue_time=policy.issue_time,
        target_date=policy.target_date,
    )
    inv["service_profile"] = [
        ServicePeriod(r.start, r.end, r.weight) for r in policy.service_profile
    ]
    forecast_quantities = {}
    for key, row in forecast.items():
        assert row.expected_portions is not None
        forecast_quantities[key] = row.expected_portions
    inv["buckets"] = allocate_service_buckets(
        forecast_quantities,
        inv["menu_items"],
        target_date=policy.target_date,
        profile=inv["service_profile"],
    )
    return replace(
        reference,
        inventory=inv,
        requirements=needs(inv),
        offers=[r.offer for r in domain.offers],
        suppliers=[Supplier(id=s, name=s) for s in policy.approved_supplier_ids],
        approved_offer_manifest=[
            (r.offer_id, r.supplier_id, r.ingredient_id) for r in domain.offers
        ],
        opportunities=[
            OrderingOpportunity(
                r.opportunity_id,
                r.offer_id,
                r.ordered_at,
                r.arrival_at,
                r.kind,
                r.expiry_date,
                SourceEvidence(r.source_revision, recorded, domain.source_revision),
            )
            for r in domain.opportunities
        ],
        safety=policy.safety_stock,
        storage=policy.storage_limits,
        budget=policy.new_order_budget_sgd,
        fee_policy=policy.fee_policy,
        tie_policy=policy.tie_break_policy,
        expiry_policy=policy.new_supply_expiry_policy,
        cash_policy=policy.objective_policy,
        search_policy=policy.search_policy,
        policy_evidence={key: ev for key in EVIDENCE},
        offer_evidence={
            r.offer_id: SourceEvidence(
                r.source_revision, recorded, domain.source_revision
            )
            for r in domain.offers
        },
        max_packs={r.opportunity_id: 200 for r in domain.opportunities},
        work_limit=10000,
    )


def semantic(p, c):
    ops = {o.id: o for o in p.opportunities}
    return sorted((ops[l.opportunity_id].offer_id, l.quantity) for l in c.lines)


def reduced(p):
    return replace(
        p,
        cash_policy="CASH_SLICE_V1",
        fee_policy="SUPPLIER_ARRIVAL_ONCE_V1",
        tie_policy=TIE_POLICY,
        search_policy=SEARCH_POLICY,
    )


def test_full_backend_domain(full):
    assert len(full.offers) == len(full.opportunities) == 24
    assert len(full.inventory["opening_lots"]) == 9
    assert all(o.available_quantity == 200 for o in full.offers)
    before = repr(full)
    result = search_procurement(full)
    assert result.status == "OPTIMAL_IN_DOMAIN", result
    assert result.domain_size == 201**24
    assert result.reduced_domain_size == result.evaluated == 450
    assert result.work_used > 450
    assert result.candidate and result.validation
    assert semantic(full, result.candidate) == [
        ("fresh-chicken", D(8)),
        ("fresh-noodles", D(3)),
    ]
    assert result.validation.cash == Cash(D("55.50"), D(5), D(0), D("60.50"))
    assert validate_candidate(full, result.candidate).feasible
    assert repr(full) == before


@pytest.mark.parametrize(
    "days,expected", [(1, date(2026, 2, 16)), (5, date(2026, 2, 20))]
)
def test_expiry_version_and_equivalent_instants(small, days, expected):
    offer = small.offers[0].model_copy(update={"shelf_life_days_on_arrival": days})
    p = with_offers(small, [offer])
    p = replace(
        p,
        opportunities=[
            replace(
                p.opportunities[0],
                expiry_date=expected,
                arrival_at=p.opportunities[0].arrival_at.astimezone(UTC),
            )
        ],
    )
    checked = validate_candidate(p, candidate(p))
    assert checked.feasible, checked
    assert _expiry(expected) == dt(str(expected + timedelta(days=1)) + "T00:00+08:00")
    wrong = replace(
        p,
        opportunities=[
            replace(p.opportunities[0], expiry_date=expected + timedelta(days=1))
        ],
    )
    assert "EXPECTED_EXPIRY_POLICY" in codes(
        validate_candidate(wrong, candidate(wrong))
    )
    assert "MISSING_OR_UNSUPPORTED_POLICY" in codes(
        search_procurement(
            replace(p, expiry_policy="USABLE_THROUGH_ARRIVAL_DATE_PLUS_DAYS")
        )
    )


def test_one_day_expiry_expires_at_midnight(small):
    inv = small.inventory.copy()
    inv["opening_lots"] = [
        l.model_copy(update={"expiry_date": date(2026, 2, 16)})
        if l.ingredient_id == "vegetables"
        else l
        for l in inv["opening_lots"]
    ]
    small = replace(small, inventory=inv)
    offer = small.offers[0].model_copy(update={"shelf_life_days_on_arrival": 1})
    p = with_offers(small, [offer])
    checked = validate_candidate(p, candidate(p, "2"))
    assert checked.feasible and checked.projection
    assert checked.projection.expiries is not None
    # 2 opening +2 receipt -2.5 demand =1.5 usable until local midnight.
    assert sum(e.quantity for e in checked.projection.expiries) == D("1.5")
    assert all(
        e.at == dt("2026-02-17T00:00+08:00") for e in checked.projection.expiries
    )


@pytest.mark.parametrize(
    "gap,cap_a,cap_b,price_a,price_b",
    [("0.5", 2, 2, 1, 2), ("2.2", 2, 2, 2, 1), ("3.1", 1, 2, 1, 1), ("0", 2, 2, 1, 1)],
)
def test_reduction_independent_exhaustive(small, gap, cap_a, cap_b, price_a, price_b):
    # Daily veg need 2.5. Stock and requirements independent of optimiser output.
    p = (
        stock(small, str(D("2.5") - D(gap)))
        if D(gap) <= D("2.5")
        else stock(small, "0")
    )
    if D(gap) > D("2.5"):
        gap = "2.5"
    offers = [
        p.offers[0].model_copy(
            update={
                "id": s + "-vegetables",
                "supplier_id": s,
                "available_quantity": D(cap),
                "unit_price": D(price),
            }
        )
        for s, cap, price in (("fresh", cap_a, price_a), ("pantry", cap_b, price_b))
    ]
    p = reduced(with_offers(p, offers))
    expected = []
    for a, b in product(range(cap_a + 1), range(cap_b + 1)):
        if D(a + b) < D(gap):
            continue
        cash = D(a * price_a + b * price_b + 5 * (bool(a) + bool(b)))
        lines = tuple(
            (s + "-vegetables", D(q)) for s, q in (("fresh", a), ("pantry", b)) if q
        )
        expected.append((cash, lines))
    r = search_procurement(p)
    if expected:
        cost, lines = min(expected)
        assert r.candidate and r.validation and r.validation.cash
        assert (r.validation.cash.total, tuple(semantic(p, r.candidate))) == (
            cost,
            lines,
        )
        exhaustive = search_procurement(
            replace(p, search_policy="COMPLETE_CARTESIAN_V1")
        )
        assert exhaustive.candidate and semantic(p, exhaustive.candidate) == list(lines)
    else:
        assert r.status == "INFEASIBLE_IN_DOMAIN"


@pytest.mark.parametrize(
    "mutation",
    [
        "pack",
        "moq",
        "expiry",
        "arrival",
        "safety",
        "commitments",
        "fee",
        "cash",
        "zero_price",
        "status",
        "cutoff",
        "lead",
        "opening_expiry",
    ],
)
def test_reduction_guards(small, mutation):
    p = reduced(small)
    o = p.offers[0]
    if mutation in ("pack", "moq", "zero_price", "status", "lead"):
        field, value = {
            "pack": ("pack_size", D(2)),
            "moq": ("moq", D(2)),
            "zero_price": ("unit_price", D(0)),
            "status": ("current_status", "UNAVAILABLE"),
            "lead": ("lead_time_minutes", 2000),
        }[mutation]
        p = reduced(with_offers(p, [o.model_copy(update={field: value})]))
    elif mutation == "cutoff":
        p = reduced(
            with_offers(
                p,
                [
                    o.model_copy(
                        update={
                            "order_cutoff": o.order_cutoff.model_copy(
                                update={"local_time": dt("2026-02-15T20:00").time()}
                            )
                        }
                    )
                ],
            )
        )
    elif mutation == "expiry":
        p = replace(
            p,
            opportunities=[replace(p.opportunities[0], expiry_date=date(2026, 2, 17))],
        )
    elif mutation == "arrival":
        p = reduced(
            with_offers(
                p,
                [
                    o.model_copy(
                        update={"feasible_delivery_at": [dt("2026-02-16T11:30+08:00")]}
                    )
                ],
            )
        )
    elif mutation == "safety":
        p = replace(p, safety={**p.safety, "vegetables": D(1)})
    elif mutation == "commitments":
        inv = p.inventory.copy()
        d = Delivery(
            id="cancelled",
            supplier_id="fresh",
            ingredient_id="vegetables",
            kind="NORMAL",
            expected_quantity=D(1),
            received_quantity=D(0),
            cancelled_quantity=D(1),
            outstanding_quantity=D(0),
            receipts=[],
            ordered_at=p.issue_time,
            expected_at=p.opportunities[0].arrival_at,
        )
        inv.update(supplies=[ExpectedSupply(d, None, None)], supply_manifest=[d.id])
        p = replace(p, inventory=inv)
    elif mutation == "opening_expiry":
        inv = p.inventory.copy()
        inv["opening_lots"] = [
            l.model_copy(update={"expiry_date": date(2026, 2, 15)})
            for l in inv["opening_lots"]
        ]
        p = replace(p, inventory=inv)
    elif mutation == "fee":
        p = replace(p, fee_policy="SUPPLIER_ARRIVAL_ONCE_PLUS_EMERGENCY_ONCE")
    else:
        p = replace(p, cash_policy="CASH_SLICE_V1_EXACT_SGD")
    r = search_procurement(p)
    assert r.status == "INCOMPLETE" and r.candidate is None
    assert "UNSUPPORTED_SEARCH_SCOPE" in codes(r)


def test_limits_generation_and_feasible_incumbent(small):
    p = reduced(small)
    complete = search_procurement(p)
    assert complete.evaluated == 1
    r = search_procurement(replace(p, work_limit=1))
    assert (
        r.evaluated == 0 and "SEARCH_LIMIT_REACHED" in codes(r) and r.candidate is None
    )
    # Two minimum allocations; stop after the first (feasible) candidate.
    p = reduced(
        with_offers(
            p,
            [
                p.offers[0],
                p.offers[0].model_copy(
                    update={"id": "pantry-vegetables", "supplier_id": "pantry"}
                ),
            ],
        )
    )
    complete = search_procurement(p)
    r = search_procurement(replace(p, work_limit=complete.work_used - 1))
    assert r.evaluated == 1 and r.diagnostic_incumbent is not None
    assert r.candidate is None and r.validation is None and not r.search_complete
    assert "SEARCH_LIMIT_REACHED" in codes(r)


def test_semantic_ties_ignore_ids_order_reliability(full):
    before = search_procurement(full)
    p = replace(
        full,
        opportunities=[
            replace(o, id=f"opaque-{i}")
            for i, o in enumerate(reversed(full.opportunities))
        ],
        offers=list(
            reversed(
                [
                    o.model_copy(
                        update={
                            "recent_on_time_rate": D(0)
                            if o.supplier_id == "fresh"
                            else D(1)
                        }
                    )
                    for o in full.offers
                ]
            )
        ),
    )
    p = replace(p, max_packs={o.id: 200 for o in p.opportunities})
    after = search_procurement(p)
    assert before.candidate and after.candidate
    assert semantic(full, before.candidate) == semantic(p, after.candidate)


@pytest.mark.parametrize(
    "constraint,code", [("budget", "NEW_ORDER_BUDGET"), ("storage", "STORAGE_CAPACITY")]
)
def test_policy_causes_not_supplier_failure(small, constraint, code):
    p = reduced(small)
    p = (
        replace(p, budget=D(1))
        if constraint == "budget"
        else replace(p, storage={**p.storage, "vegetables": D(2)})
    )
    r = search_procurement(p)
    assert r.status == "INFEASIBLE_IN_DOMAIN" and code in dict(r.rejection_counts)


def test_no_purchase_and_capacity_proof(small):
    r = search_procurement(reduced(stock(small, "3")))
    assert r.candidate == PurchaseCandidate((), Cash(D(0), D(0), D(0), D(0)))
    p = with_offers(
        stock(small, "0"),
        [small.offers[0].model_copy(update={"available_quantity": D(1)})],
    )
    r = search_procurement(reduced(p))
    assert r.status == "INFEASIBLE_IN_DOMAIN" and r.reduced_domain_size == 0
    assert "INSUFFICIENT_NEW_CAPACITY" in dict(r.rejection_counts)


def test_independent_tamper_validation(small, monkeypatch):
    p = reduced(small)
    r = search_procurement(p)
    assert r.candidate
    monkeypatch.setattr(
        "src.procurement.search_procurement",
        lambda *_: pytest.fail("validator called optimiser"),
    )
    assert validate_candidate(p, r.candidate).feasible
    assert "CASH_MISMATCH" in codes(
        validate_candidate(
            p, replace(r.candidate, claimed_cash=Cash(D(0), D(0), D(0), D(0)))
        )
    )
    assert "SHARED_OFFER_CAPACITY" in codes(validate_candidate(p, candidate(p, "3")))
    assert "PACK_MULTIPLE" in codes(validate_candidate(p, candidate(p, "1.1")))


@pytest.mark.parametrize("fixed_earlier", [False, True])
def test_cross_source_fefo_and_stable_projected_identity(small, fixed_earlier):
    p = stock(small, "1")
    inv = p.inventory.copy()
    inv["fixture_fefo"] = FEFO_POLICY
    # Opening expires with the expected supplies but is physically received first.
    inv["opening_lots"] = [
        l.model_copy(update={"expiry_date": date(2026, 2, 20)})
        for l in inv["opening_lots"]
    ]
    arrival = dt(
        "2026-02-16T07:00+08:00" if fixed_earlier else "2026-02-16T08:00+08:00"
    )
    d = Delivery(
        id="a-fixed",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(1),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D(1),
        ordered_at=p.issue_time,
        expected_at=arrival,
        receipts=[],
    )
    inv.update(
        supplies=[
            ExpectedSupply(
                d, date(2026, 2, 20), inv["evidence"]["supply"], "zz-projected-fixed"
            )
        ],
        supply_manifest=[d.id],
    )
    p = replace(p, inventory=inv)
    v = validate_candidate(p, candidate(p))
    assert v.feasible and v.projection and v.projection.lots
    rows = {l.key: l for l in v.projection.lots}
    assert rows["opening:vegetables"].allocated == 1
    assert rows["supply:a-fixed"].allocated == (D(1) if fixed_earlier else D(".5"))
    q = replace(
        p,
        opportunities=[replace(p.opportunities[0], id="renamed")],
        max_packs={"renamed": 2},
    )
    vv = validate_candidate(q, candidate(q))
    assert vv.feasible and vv.projection and vv.projection.lots
    assert (
        next(l for l in vv.projection.lots if l.key == "supply:a-fixed").allocated
        == rows["supply:a-fixed"].allocated
    )


def test_opening_equal_expiry_receipt_then_id(small):
    inv = small.inventory.copy()
    inv["fixture_fefo"] = FEFO_POLICY
    veg = next(l for l in inv["opening_lots"] if l.ingredient_id == "vegetables")
    variants = [
        veg.model_copy(
            update={
                "id": key,
                "quantity": D(1),
                "initial_quantity": D(1),
                "received_at": dt(at),
            }
        )
        for key, at in (
            ("z-early", "2026-02-15T07:00+08:00"),
            ("b-later", "2026-02-15T08:00+08:00"),
            ("a-later", "2026-02-15T08:00+08:00"),
        )
    ]
    inv["opening_lots"] = [
        l for l in inv["opening_lots"] if l.ingredient_id != "vegetables"
    ] + variants
    inv["opening_manifest"] = {
        **inv["opening_manifest"],
        "vegetables": [l.id for l in variants],
    }
    r = project_inventory(**inv)
    assert r.complete and r.lots
    assert {l.key: l.allocated for l in r.lots if l.ingredient_id == "vegetables"} == {
        "opening:z-early": D(1),
        "opening:a-later": D(1),
        "opening:b-later": D(".5"),
    }


def test_new_fefo_requires_unique_explicit_projected_identity(small):
    p = stock(small, "1")
    inv = p.inventory.copy()
    inv["fixture_fefo"] = FEFO_POLICY
    d = Delivery(
        id="fixed",
        supplier_id="fresh",
        ingredient_id="vegetables",
        kind="NORMAL",
        expected_quantity=D(1),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D(1),
        ordered_at=p.issue_time,
        expected_at=p.opportunities[0].arrival_at,
        receipts=[],
    )
    s = ExpectedSupply(d, date(2026, 2, 20), inv["evidence"]["supply"])
    inv.update(supplies=[s], supply_manifest=[d.id])
    assert "MISSING_PROJECTED_LOT_ID" in codes(project_inventory(**inv))
    inv["supplies"] = [replace(s, projected_lot_id="vegetables")]
    with pytest.raises(ValueError, match="unique across"):
        project_inventory(**inv)


def test_generation_is_bounded_even_with_enormous_need(small):
    p = reduced(stock(small, "0"))
    inv = p.inventory.copy()
    inv["buckets"] = [
        replace(
            b,
            expected_portions={
                d: D(10) ** 20 if d == "tofu-bowl" else D(0)
                for d in b.expected_portions
            },
        )
        for b in inv["buckets"]
    ]
    p = replace(p, inventory=inv, requirements=needs(inv))
    offers = [
        p.offers[0].model_copy(
            update={
                "id": s + "-vegetables",
                "supplier_id": s,
                "available_quantity": D(10) ** 20,
            }
        )
        for s in ("fresh", "pantry")
    ]
    p = reduced(with_offers(p, offers))
    r = search_procurement(replace(p, work_limit=15))
    assert r.status == "INCOMPLETE" and r.work_used == 15 and r.evaluated == 0
    assert "SEARCH_LIMIT_REACHED" in codes(r)


def test_zero_arrival_shelf_life_cannot_validate(small):
    p = with_offers(
        small, [small.offers[0].model_copy(update={"shelf_life_days_on_arrival": 0})]
    )
    assert "UNUSABLE_ARRIVAL_SHELF_LIFE" in codes(validate_candidate(p, candidate(p)))


def test_unknown_search_and_discount_policies_do_not_default(small):
    for p in (
        replace(small, search_policy="UNKNOWN"),
        replace(small, fee_policy="MINIMUM_SPEND_DISCOUNT"),
        replace(small, cash_policy="FUTURE_CREDIT"),
    ):
        r = search_procurement(p)
        assert r.status == "INCOMPLETE" and "MISSING_OR_UNSUPPORTED_POLICY" in codes(r)

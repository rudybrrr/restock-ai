"""Independent quantities/cash for explicit frozen future supply renewals."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from src.economic_supply import (
    FEE_POLICY,
    SOURCES,
    SUPPLY_POLICY,
    CapacityWindow,
    EconomicSupply,
    supply_findings,
    validate_economic_supply,
)
from src.inventory_projection import SourceEvidence
from src.procurement import Cash, OrderingOpportunity, PurchaseCandidate, PurchaseLine
from src.schemas import Ingredient, NoCutoff, Supplier, SupplierOffer

D = Decimal
ISSUE = datetime.fromisoformat("2026-02-16T00:00:00+08:00")
EV = SourceEvidence("synthetic:stable-supply-1", ISSUE, "synthetic-revision-1")


@pytest.fixture
def supply():
    arrivals = [ISSUE + timedelta(hours=10), ISSUE + timedelta(days=1, hours=10)]
    offer = SupplierOffer(
        id="chicken-offer",
        supplier_id="fresh",
        ingredient_id="chicken",
        unit_price=D(2),
        available_quantity=D(3),
        moq=D(1),
        pack_size=D("0.5"),
        lead_time_minutes=60,
        order_cutoff=NoCutoff(kind="NONE"),
        feasible_delivery_at=arrivals,
        current_status="AVAILABLE",
        recent_on_time_rate=None,
        shelf_life_days_on_arrival=2,
        delivery_fee_sgd=D(3),
        emergency_fee_sgd=D(4),
        observed_at=ISSUE,
    )
    ops = tuple(
        OrderingOpportunity(
            "op-" + str(n),
            offer.id,
            ISSUE + timedelta(days=n),
            arrival,
            "NORMAL",
            arrival.date() + timedelta(days=1),
            EV,
        )
        for n, arrival in enumerate(arrivals)
    )
    windows = tuple(
        CapacityWindow(
            "window-" + str(n),
            offer.id,
            ISSUE + timedelta(days=n),
            ISSUE + timedelta(days=n + 1),
            D(3),
            EV,
        )
        for n in range(2)
    )
    return EconomicSupply(
        ISSUE,
        ISSUE + timedelta(days=21),
        ISSUE,
        "synthetic-revision-1",
        (
            Ingredient(
                id="chicken",
                name="Chicken",
                unit="kg",
                interval_days=1,
                starting_date=date(2026, 2, 15),
            ),
        ),
        (Supplier(id="fresh", name="Fresh"),),
        (offer,),
        ((offer.id, offer.supplier_id, offer.ingredient_id),),
        ops,
        tuple(o.id for o in ops),
        windows,
        tuple(w.id for w in windows),
        {"op-0": "window-0", "op-1": "window-1"},
        {"op-0": "shipment-0", "op-1": "shipment-1"},
        {offer.id: D(1)},
        {offer.id: EV},
        {s: EV for s in SOURCES},
        SUPPLY_POLICY,
        FEE_POLICY,
        "CONTEXT_ONLY",
    )


def candidate(*quantities):
    return PurchaseCandidate(
        tuple(
            PurchaseLine("op-" + str(n), D(q), "kg") for n, q in enumerate(quantities)
        )
    )


def codes(result):
    return {f.code for f in (*result.findings, *result.violations)}


def test_renewal_is_explicit_new_capacity_and_current_cash_separate(supply):
    actual = validate_economic_supply(supply, candidate("3", "3"))
    assert actual.complete and actual.feasible
    # 6 kg x $2 + TWO distinct $3 shipments; current action is only $9.
    assert actual.cash == Cash(D(12), D(6), D(0), D(18))
    assert actual.immediate_cash == Cash(D(6), D(3), D(0), D(9))
    assert actual.capacity_used == (("window-0", D(3)), ("window-1", D(3)))
    assert [p.origin for p in actual.purchases] == ["NEW_PURCHASE", "CONTINUATION"]


def test_empty_candidate_requires_complete_domain_but_explicit_empty_domain_is_valid(
    supply,
):
    empty = PurchaseCandidate(())
    assert validate_economic_supply(supply, empty).cash == Cash(D(0), D(0), D(0), D(0))
    missing = replace(supply, windows=None, window_manifest=None, capacity_window={})
    result = validate_economic_supply(missing, empty)
    assert not result.complete and result.feasible is None and result.cash is None
    assert "MISSING_REQUIRED_DATA" in codes(result)
    explicit = replace(
        supply,
        opportunities=(),
        opportunity_manifest=(),
        windows=(),
        window_manifest=(),
        capacity_window={},
        shipment_groups={},
    )
    assert validate_economic_supply(explicit, empty).feasible


def test_multiple_orders_share_one_window_without_implicit_renewal(supply):
    assert supply.opportunities and supply.windows
    ops = (
        supply.opportunities[0],
        replace(supply.opportunities[1], ordered_at=ISSUE + timedelta(hours=1)),
    )
    p = replace(
        supply,
        opportunities=ops,
        windows=supply.windows[:1],
        window_manifest=("window-0",),
        capacity_window={o.id: "window-0" for o in ops},
    )
    result = validate_economic_supply(p, candidate("2", "2"))
    assert result.complete and result.feasible is False
    assert "SHARED_WINDOW_CAPACITY" in codes(result)


def test_window_cannot_resolve_suspended_offer(supply):
    p = replace(
        supply,
        offers=(supply.offers[0].model_copy(update={"current_status": "UNAVAILABLE"}),),
    )
    result = validate_economic_supply(p, candidate("1", "1"))
    assert result.complete and result.feasible is False
    assert "OFFER_UNAVAILABLE" in codes(result)


def test_non_sgd_frozen_offer_cannot_enter_sgd_ledger(supply):
    offer = supply.offers[0].model_copy(update={"currency": "USD"})
    with pytest.raises(ValueError, match="currency"):
        supply_findings(replace(supply, offers=(offer,)))


@pytest.mark.parametrize(
    "quantity,unit,code",
    [
        ("0", "kg", "INVALID_QUANTITY"),
        ("NaN", "kg", "INVALID_QUANTITY"),
        ("-1", "kg", "INVALID_QUANTITY"),
        ("0.5", "kg", "MOQ"),
        ("1.25", "kg", "PACK_MULTIPLE"),
        ("1", "litres", "UNIT_MISMATCH"),
        ("3.5", "kg", "SHARED_WINDOW_CAPACITY"),
    ],
)
def test_tampered_candidate(supply, quantity, unit, code):
    actual = validate_economic_supply(
        supply, PurchaseCandidate((PurchaseLine("op-0", D(quantity), unit),))
    )
    assert actual.feasible is False and code in codes(actual)


def test_cash_claim_and_duplicate_or_unknown_lines_rejected(supply):
    bad = replace(candidate("1"), claimed_cash=Cash(D(0), D(0), D(0), D(0)))
    assert "CASH_MISMATCH" in codes(validate_economic_supply(supply, bad))
    line = candidate("1").lines[0]
    assert "DUPLICATE_LINE" in codes(
        validate_economic_supply(supply, PurchaseCandidate((line, line)))
    )
    assert "UNKNOWN_OPPORTUNITY" in codes(
        validate_economic_supply(
            supply, PurchaseCandidate((replace(line, opportunity_id="unknown"),))
        )
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"unit_price": None}, "MISSING_REQUIRED_DATA"),
        ({"current_status": "UNKNOWN"}, "MISSING_REQUIRED_DATA"),
        ({"observed_at": ISSUE + timedelta(seconds=1)}, "NOT_YET_AVAILABLE"),
    ],
)
def test_unknown_unselected_offer_prevents_complete_domain(supply, change, code):
    p = replace(supply, offers=(supply.offers[0].model_copy(update=change),))
    actual = validate_economic_supply(p, PurchaseCandidate(()))
    assert not actual.complete and actual.cash is None and code in codes(actual)


@pytest.mark.parametrize("field", ["supply_policy", "fee_policy", "reliability_policy"])
def test_unresolved_policy_is_incomplete(supply, field):
    assert "MISSING_OR_UNSUPPORTED_POLICY" in codes(
        validate_economic_supply(replace(supply, **{field: None}), candidate("1"))
    )


def test_unknown_disposal_cost_and_expiry_are_not_zero(supply):
    assert "MISSING_REQUIRED_DATA" in codes(
        validate_economic_supply(replace(supply, disposal_rates={}), candidate("1"))
    )
    assert supply.opportunities
    ops = (replace(supply.opportunities[0], expiry_date=None), supply.opportunities[1])
    assert "MISSING_EXPECTED_EXPIRY" in codes(
        validate_economic_supply(replace(supply, opportunities=ops), candidate("1"))
    )


def test_future_evidence_and_wrong_revision_fail_closed(supply):
    for ev, expected in (
        (replace(EV, available_at=ISSUE + timedelta(seconds=1)), "NOT_YET_AVAILABLE"),
        (replace(EV, captured_revision="other"), "REVISION_MISMATCH"),
    ):
        p = replace(supply, offer_evidence={"chicken-offer": ev})
        assert expected in codes(validate_economic_supply(p, candidate("1")))


def test_overlapping_renewals_and_unbounded_capacity_rejected(supply):
    assert supply.windows
    for window, message in (
        (replace(supply.windows[1], start=ISSUE), "Overlapping"),
        (replace(supply.windows[1], available_quantity=D(4)), "increase"),
    ):
        with pytest.raises(ValueError, match=message):
            supply_findings(replace(supply, windows=(supply.windows[0], window)))


def test_shared_shipment_charged_once(supply):
    assert supply.opportunities
    other = supply.offers[0].model_copy(
        update={"id": "other-offer", "ingredient_id": "rice"}
    )
    op = replace(supply.opportunities[0], id="op-rice", offer_id=other.id)
    ingredient = supply.ingredients[0].model_copy(update={"id": "rice", "name": "Rice"})
    assert supply.windows
    window = replace(supply.windows[0], id="rice-window", offer_id=other.id)
    p = replace(
        supply,
        ingredients=(*supply.ingredients, ingredient),
        offers=(*supply.offers, other),
        approved_offer_manifest=(
            *supply.approved_offer_manifest,
            (other.id, other.supplier_id, other.ingredient_id),
        ),
        opportunities=(*supply.opportunities, op),
        opportunity_manifest=(*supply.opportunity_manifest, op.id),
        windows=(*supply.windows, window),
        window_manifest=(*supply.window_manifest, window.id),
        capacity_window={**supply.capacity_window, op.id: window.id},
        shipment_groups={**supply.shipment_groups, op.id: "shipment-0"},
        disposal_rates={**supply.disposal_rates, other.id: D(0)},
        offer_evidence={**supply.offer_evidence, other.id: EV},
    )
    actual = validate_economic_supply(
        p,
        PurchaseCandidate(
            (PurchaseLine("op-0", D(1), "kg"), PurchaseLine(op.id, D(1), "kg"))
        ),
    )
    assert actual.feasible and actual.cash == Cash(D(4), D(3), D(0), D(7))


def test_emergency_fee_excludes_delivery_and_future_emergencies_rejected(supply):
    assert supply.opportunities
    p = replace(
        supply,
        opportunities=(
            replace(supply.opportunities[0], kind="EMERGENCY"),
            supply.opportunities[1],
        ),
    )
    actual = validate_economic_supply(p, candidate("1"))
    assert actual.feasible and actual.cash == Cash(D(2), D(3), D(4), D(9))
    with pytest.raises(ValueError, match="emergency"):
        supply_findings(
            replace(
                supply,
                opportunities=(
                    supply.opportunities[0],
                    replace(supply.opportunities[1], kind="EMERGENCY"),
                ),
            )
        )


def test_reliability_order_decimal_context_and_input_immutability(supply):
    expected = validate_economic_supply(supply, candidate("1.5", "2.5"))
    assert supply.opportunities and supply.windows
    p = replace(
        supply,
        offers=(
            supply.offers[0].model_copy(update={"recent_on_time_rate": D("0.01")}),
        ),
        opportunities=tuple(reversed(supply.opportunities)),
        windows=tuple(reversed(supply.windows)),
    )
    with localcontext() as ctx:
        ctx.prec = 2
        assert validate_economic_supply(p, candidate("1.5", "2.5")) == expected
    assert supply.offers[0].recent_on_time_rate is None
    assert supply.windows[0].available_quantity == 3


@pytest.mark.parametrize(
    "change,code",
    [
        ({"lead_time_minutes": 601}, "LEAD_TIME"),
        ({"feasible_delivery_at": []}, "DELIVERY_SLOT"),
        ({"shelf_life_days_on_arrival": 1}, "EXPECTED_EXPIRY_POLICY"),
    ],
)
def test_known_timing_failures_are_infeasible_not_missing(supply, change, code):
    actual = validate_economic_supply(
        replace(supply, offers=(supply.offers[0].model_copy(update=change),)),
        candidate("1"),
    )
    assert actual.complete and not actual.feasible and code in codes(actual)

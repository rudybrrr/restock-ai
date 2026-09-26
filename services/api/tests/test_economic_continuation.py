"""Independent daily restocking oracles on the canonical 21-date fixture."""

from dataclasses import replace
from datetime import time, timedelta
from decimal import Decimal

import pytest
from test_economic_rollout import END, EV, ISSUE
from test_economic_rollout import inputs as inputs  # noqa: PLC0414

from src.economic_continuation import (
    CONTINUATION_POLICY,
    ContinuationInputs,
    RoutineOccasion,
    continuation_findings,
    continue_routine,
)
from src.economic_rollout import AssetTerms
from src.economic_supply import (
    FEE_POLICY,
    SOURCES,
    SUPPLY_POLICY,
    CapacityWindow,
    EconomicSupply,
)
from src.inventory_projection import ExpectedSupply
from src.operations_schemas import Delivery
from src.procurement import OrderingOpportunity, PurchaseCandidate, PurchaseLine
from src.schemas import NoCutoff, Supplier, SupplierOffer

D = Decimal
EMPTY = PurchaseCandidate(())


@pytest.fixture
def routine(inputs):
    assert EV.captured_revision is not None
    ops = tuple(
        OrderingOpportunity(
            "routine-chicken-" + str(day),
            "chicken-offer",
            ISSUE + timedelta(days=day),
            ISSUE + timedelta(days=day, hours=10),
            "NORMAL",
            (ISSUE + timedelta(days=day)).date(),
            EV,
        )
        for day in range(1, 21)
    )
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
        feasible_delivery_at=[o.arrival_at for o in ops],
        current_status="AVAILABLE",
        recent_on_time_rate=None,
        shelf_life_days_on_arrival=1,
        delivery_fee_sgd=D(0),
        emergency_fee_sgd=D(0),
        observed_at=ISSUE,
    )
    windows = tuple(
        CapacityWindow(
            "window-" + str(n),
            offer.id,
            op.ordered_at,
            op.ordered_at + timedelta(days=1),
            D(3),
            EV,
        )
        for n, op in enumerate(ops)
    )
    supply = EconomicSupply(
        ISSUE,
        END,
        ISSUE,
        EV.captured_revision,
        inputs.inventory["ingredients"],
        (Supplier(id="fresh", name="Fresh"),),
        (offer,),
        ((offer.id, "fresh", "chicken"),),
        ops,
        tuple(o.id for o in ops),
        windows,
        tuple(w.id for w in windows),
        {o.id: w.id for o, w in zip(ops, windows, strict=True)},
        {o.id: "shipment:" + o.id for o in ops},
        {offer.id: D(1)},
        {offer.id: EV},
        {s: EV for s in SOURCES},
        SUPPLY_POLICY,
        FEE_POLICY,
        "CONTEXT_ONLY",
    )
    occasions = []
    for ingredient in inputs.inventory["ingredients"]:
        for n in range(1, 21):
            at = ISSUE + timedelta(days=n)
            delta = (at.date() - ingredient.starting_date).days
            if delta >= 0 and delta % ingredient.interval_days == 0:
                ids = (ops[n - 1].id,) if ingredient.id == "chicken" else ()
                until = min(END, at + timedelta(days=1, hours=10)) if ids else END
                occasions.append(RoutineOccasion(ingredient.id, at, until, ids, EV))
    return ContinuationInputs(
        inputs,
        supply,
        {i.id: time(0) for i in inputs.inventory["ingredients"]},
        tuple(occasions),
        D(1000),
        CONTINUATION_POLICY,
        EV,
        1000000,
        timeout_seconds=60.0,
    )


def total(result):
    assert result.complete, result.findings
    assert result.rollout and result.rollout.ledger and result.rollout.ledger.components
    return result.rollout.ledger.components.primary_sgd


def test_daily_continuation_covers_21_dates_without_buying_21_days_now(routine):
    result = continue_routine(routine, EMPTY)
    assert total(result) == D(
        "67.50"
    )  # opening6 + initial expiry disposal1.5 + 20*1.5kg*$2.
    assert result.future_lines is not None and len(result.future_lines) == 20
    assert all(line.quantity == D("1.5") for line in result.future_lines)
    assert all(d.line is None for d in result.decisions if d.ingredient_id != "chicken")
    assert result.rollout and result.rollout.service
    assert sum(s.served for s in result.rollout.service) == 210
    assert not result.actionable and not result.limitations


def test_moq_pack_expiry_and_storage_are_applied_at_each_occasion(routine):
    offer = routine.supply.offers[0].model_copy(update={"pack_size": D(1), "moq": D(2)})
    p = replace(routine, supply=replace(routine.supply, offers=(offer,)))
    result = continue_routine(p, EMPTY)
    # 20*2kg*$2 + opening6 + 1.5 initial expired + 20*0.5 extra expired.
    assert total(result) == D("97.50")
    assert result.future_lines and {line.quantity for line in result.future_lines} == {
        D(2)
    }
    inventory = dict(p.rollout.inventory)
    inventory["storage"] = {**inventory["storage"], "chicken": D("1.75")}
    limited = continue_routine(
        replace(p, rollout=replace(p.rollout, inventory=inventory)), EMPTY
    )
    assert limited.complete and limited.limitations and limited.future_lines == ()
    assert all(f.code == "CONTINUATION_HEURISTIC_SHORTAGE" for f in limited.limitations)


def test_fixed_supply_covers_future_demand_without_duplicate_routine_buy(routine):
    delivery = Delivery(
        id="fixed-thirty",
        supplier_id="fresh",
        ingredient_id="chicken",
        kind="NORMAL",
        expected_quantity=D(30),
        received_quantity=D(0),
        cancelled_quantity=D(0),
        outstanding_quantity=D(30),
        ordered_at=ISSUE - timedelta(days=1),
        expected_at=ISSUE + timedelta(days=1, hours=10),
        receipts=[],
    )
    inv = dict(routine.rollout.inventory)
    inv["supplies"] = (
        ExpectedSupply(
            delivery, (END + timedelta(days=1)).date(), EV, "fixed-thirty-lot"
        ),
    )
    inv["supply_manifest"] = (delivery.id,)
    rollout = replace(
        routine.rollout,
        inventory=inv,
        asset_terms={
            **routine.rollout.asset_terms,
            "supply:fixed-thirty": AssetTerms(D(2), D(1), EV),
        },
    )
    result = continue_routine(replace(routine, rollout=rollout), EMPTY)
    assert total(result) == D("67.50")
    assert result.future_lines == ()
    assert result.rollout and result.rollout.ledger and result.rollout.ledger.components
    assert result.rollout.ledger.components.acquisition == 0


def test_late_arrival_never_erases_earlier_shortage(routine):
    assert routine.supply.opportunities
    ops = (
        replace(
            routine.supply.opportunities[0],
            arrival_at=ISSUE + timedelta(days=1, hours=12),
        ),
        *routine.supply.opportunities[1:],
    )
    offer = routine.supply.offers[0].model_copy(
        update={"feasible_delivery_at": [o.arrival_at for o in ops]}
    )
    p = replace(
        routine, supply=replace(routine.supply, opportunities=ops, offers=(offer,))
    )
    result = continue_routine(p, EMPTY)
    assert total(result) == D("144.50")  # 6+1.5+19*3+10 unmet*$8.
    assert result.rollout and result.rollout.service
    assert sum(s.required - s.served for s in result.rollout.service) == 10
    assert any(f.code == "CONTINUATION_HEURISTIC_SHORTAGE" for f in result.limitations)


def test_empty_opportunities_are_known_heuristic_shortage_not_missing(routine):
    p = replace(
        routine,
        supply=replace(
            routine.supply,
            opportunities=(),
            opportunity_manifest=(),
            windows=(),
            window_manifest=(),
            capacity_window={},
            shipment_groups={},
        ),
        occasions=tuple(
            replace(o, opportunity_ids=(), protect_until=END) for o in routine.occasions
        ),
    )
    result = continue_routine(p, EMPTY)
    assert total(result) == D("1607.50") and result.limitations
    missing = replace(
        p, occasions=tuple(replace(o, opportunity_ids=None) for o in p.occasions)
    )
    actual = continue_routine(missing, EMPTY)
    assert (
        not actual.complete and actual.rollout is None and actual.future_lines is None
    )
    assert "MISSING_ROUTINE_DOMAIN" in {f.code for f in actual.findings}


def test_required_raw_demand_is_not_retrained_from_other_ingredient_stockouts(routine):
    inv = dict(routine.rollout.inventory)
    inv["opening_lots"] = tuple(
        l.model_copy(update={"quantity": D(0)}) if l.ingredient_id == "rice" else l
        for l in inv["opening_lots"]
    )
    result = continue_routine(
        replace(routine, rollout=replace(routine.rollout, inventory=inv)), EMPTY
    )
    assert result.complete and result.future_lines and len(result.future_lines) == 20
    assert all(line.quantity == D("1.5") for line in result.future_lines)
    assert (
        result.rollout
        and result.rollout.service
        and sum(s.served for s in result.rollout.service) == 0
    )


def test_incremental_budget_is_shared_across_future_orders(routine):
    result = continue_routine(replace(routine, incremental_budget=D(6)), EMPTY)
    assert result.complete and result.future_lines and len(result.future_lines) == 2
    assert total(result) == D("1453.50")  # opening6+disposal1.5+new6+180 unmet*8.


def test_work_exhaustion_has_no_actionable_incumbent_or_ledger(routine):
    result = continue_routine(replace(routine, work_limit=50), EMPTY)
    assert (
        not result.complete and result.future_lines is None and result.rollout is None
    )
    assert not result.actionable and {f.code for f in result.findings} == {
        "SEARCH_LIMIT_REACHED"
    }


@pytest.mark.parametrize(
    "field",
    ["incremental_budget", "policy", "evidence", "occasions", "timeout_seconds"],
)
def test_missing_policy_data_is_not_inferred(routine, field):
    result = continue_routine(replace(routine, **{field: None}), EMPTY)
    assert not result.complete and result.rollout is None


def test_calendar_and_protection_cannot_be_truncated(routine):
    missing = replace(routine, occasions=routine.occasions[1:])
    assert "INCOMPLETE_ROUTINE_CALENDAR" in {
        f.code for f in continuation_findings(missing)
    }
    first = routine.occasions[0]
    short = replace(first, protect_until=first.ordered_at + timedelta(hours=1))
    p = replace(routine, occasions=(short, *routine.occasions[1:]))
    assert "ROUTINE_PROTECTION_MISMATCH" in {f.code for f in continuation_findings(p)}
    wrong = replace(first, ordered_at=first.ordered_at + timedelta(hours=1))
    with pytest.raises(ValueError, match="anchored"):
        continuation_findings(
            replace(routine, occasions=(wrong, *routine.occasions[1:]))
        )


def test_zero_capacity_next_window_is_not_a_feasible_receipt_boundary(routine):
    windows = tuple(
        replace(w, available_quantity=D(0)) if w.id == "window-1" else w
        for w in routine.supply.windows
    )
    p = replace(routine, supply=replace(routine.supply, windows=windows))
    assert "ROUTINE_PROTECTION_MISMATCH" in {f.code for f in continuation_findings(p)}


def test_reliability_input_order_and_repeated_calls_do_not_change_choices(routine):
    first = continue_routine(routine, EMPTY)
    supply = replace(
        routine.supply,
        opportunities=tuple(reversed(routine.supply.opportunities)),
        offers=(
            routine.supply.offers[0].model_copy(
                update={"recent_on_time_rate": D("0.01")}
            ),
        ),
    )
    other = continue_routine(
        replace(routine, supply=supply, occasions=tuple(reversed(routine.occasions))),
        EMPTY,
    )
    assert first == other
    assert routine.supply.offers[0].recent_on_time_rate is None


def test_future_orders_cannot_be_disguised_as_current_action(routine):
    with pytest.raises(ValueError, match="smuggle"):
        continue_routine(
            routine, PurchaseCandidate((PurchaseLine("routine-chicken-1", D(1), "kg"),))
        )


def test_host_deadline_expiry_fails_closed(routine, monkeypatch):
    monkeypatch.setattr("src.economic_rollout.monotonic", lambda: 1e100)
    actual = continue_routine(routine, EMPTY)
    assert (
        not actual.complete and actual.rollout is None and actual.future_lines is None
    )
    assert {f.code for f in actual.findings} == {"SEARCH_LIMIT_REACHED"}


def test_feasible_future_split_is_reported_as_heuristic_shortage(routine):
    # Each supplier can provide1kg; together they could cover the1.5kg daily need.
    # The declared routine policy checks single-offer fills, not split search.
    original = routine.supply
    first = original.offers[0].model_copy(update={"available_quantity": D(1)})
    second = first.model_copy(update={"id": "second-offer", "supplier_id": "second"})
    second_ops = tuple(
        replace(o, id="second:" + o.id, offer_id=second.id)
        for o in original.opportunities
    )
    first_windows = tuple(replace(w, available_quantity=D(1)) for w in original.windows)
    second_windows = tuple(
        replace(w, id="second:" + w.id, offer_id=second.id) for w in first_windows
    )
    supply = replace(
        original,
        suppliers=(
            *original.suppliers,
            Supplier(id="second", name="Second synthetic supplier"),
        ),
        offers=(first, second),
        approved_offer_manifest=(
            (first.id, first.supplier_id, first.ingredient_id),
            (second.id, second.supplier_id, second.ingredient_id),
        ),
        opportunities=(*original.opportunities, *second_ops),
        opportunity_manifest=(
            *original.opportunity_manifest,
            *(o.id for o in second_ops),
        ),
        windows=(*first_windows, *second_windows),
        window_manifest=(*original.window_manifest, *(w.id for w in second_windows)),
        capacity_window={
            **original.capacity_window,
            **{o.id: w.id for o, w in zip(second_ops, second_windows, strict=True)},
        },
        shipment_groups={
            **original.shipment_groups,
            **{o.id: "shipment:" + o.id for o in second_ops},
        },
        disposal_rates={**original.disposal_rates, second.id: D(1)},
        offer_evidence={**original.offer_evidence, second.id: EV},
    )
    occasions = tuple(
        replace(
            o,
            opportunity_ids=(
                *o.opportunity_ids,
                *("second:" + key for key in o.opportunity_ids),
            ),
        )
        if o.ingredient_id == "chicken"
        else o
        for o in routine.occasions
    )
    actual = continue_routine(
        replace(routine, supply=supply, occasions=occasions), EMPTY
    )
    assert actual.complete and actual.future_lines == ()
    assert {f.code for f in actual.limitations} == {"CONTINUATION_HEURISTIC_SHORTAGE"}
    assert total(actual) == D("1607.50")


def test_currency_and_safety_are_explicit(routine):
    inv = dict(routine.rollout.inventory)
    inv["safety"] = {**inv["safety"], "chicken": D("0.5")}
    result = continue_routine(
        replace(routine, rollout=replace(routine.rollout, inventory=inv)), EMPTY
    )
    assert (
        result.complete
        and result.future_lines
        and {l.quantity for l in result.future_lines} == {D(2)}
    )
    assert total(result) == D("97.50")

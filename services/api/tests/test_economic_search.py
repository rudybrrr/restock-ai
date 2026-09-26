"""Complete tiny-domain oracles for economic rather than cash-only selection."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from test_economic_continuation import routine as routine  # noqa: PLC0414
from test_economic_rollout import END, EV, ISSUE
from test_economic_rollout import inputs as inputs  # noqa: PLC0414

from src.economic_search import (
    OBJECTIVE_POLICY,
    SEARCH_POLICY,
    TIE_POLICY,
    EconomicCandidate,
    EconomicSearchInputs,
    search_economics,
    validate_economic_candidate,
)
from src.economic_supply import CapacityWindow
from src.procurement import OrderingOpportunity, PurchaseCandidate, PurchaseLine
from src.schemas import Supplier
from src.service_buckets import allocate_service_buckets

D = Decimal


@pytest.fixture
def search_inputs(routine):
    inv = dict(routine.rollout.inventory)
    inv["opening_lots"] = tuple(
        l.model_copy(update={"quantity": D(0)}) if l.ingredient_id == "chicken" else l
        for l in inv["opening_lots"]
    )
    # A is $3 cash but wastes 1.5 kg; B is $3.75 cash and wastes nothing.
    offers = tuple(
        routine.supply.offers[0].model_copy(
            update={
                "id": key,
                "unit_price": price,
                "available_quantity": pack,
                "moq": pack,
                "pack_size": pack,
                "feasible_delivery_at": [ISSUE + timedelta(hours=10)],
            }
        )
        for key, price, pack in (("a-bulk", D(1), D(3)), ("b-lean", D("2.5"), D("1.5")))
    )
    ops = tuple(
        OrderingOpportunity(
            o.id, o.id, ISSUE, ISSUE + timedelta(hours=10), "NORMAL", ISSUE.date(), EV
        )
        for o in offers
    )
    windows = tuple(
        CapacityWindow(
            o.id, o.id, ISSUE, ISSUE + timedelta(days=1), o.available_quantity, EV
        )
        for o in offers
    )
    supply = replace(
        routine.supply,
        offers=(*routine.supply.offers, *offers),
        approved_offer_manifest=(
            *routine.supply.approved_offer_manifest,
            *((o.id, o.supplier_id, o.ingredient_id) for o in offers),
        ),
        opportunities=(*routine.supply.opportunities, *ops),
        opportunity_manifest=(
            *routine.supply.opportunity_manifest,
            *(o.id for o in ops),
        ),
        windows=(*routine.supply.windows, *windows),
        window_manifest=(*routine.supply.window_manifest, *(w.id for w in windows)),
        capacity_window={**routine.supply.capacity_window, **{o.id: o.id for o in ops}},
        shipment_groups={
            **routine.supply.shipment_groups,
            **{o.id: "shipment:" + o.id for o in ops},
        },
        disposal_rates={
            **routine.supply.disposal_rates,
            **{o.id: D(1) for o in offers},
        },
        offer_evidence={**routine.supply.offer_evidence, **{o.id: EV for o in offers}},
    )
    return EconomicSearchInputs(
        replace(
            routine, rollout=replace(routine.rollout, inventory=inv), supply=supply
        ),
        ("chicken",),
        SEARCH_POLICY,
        OBJECTIVE_POLICY,
        TIE_POLICY,
        1000000,
        33,
        timeout_seconds=120.0,
    )


def candidate(key="b-lean", quantity="1.5"):
    return EconomicCandidate(PurchaseCandidate((PurchaseLine(key, D(quantity), "kg"),)))


def cost(validation):
    assert validation.complete and validation.feasible, (
        validation.findings,
        validation.violations,
    )
    assert validation.continuation and validation.continuation.rollout
    assert (
        validation.continuation.rollout.ledger
        and validation.continuation.rollout.ledger.components
    )
    return validation.continuation.rollout.ledger.components


def test_complete_enumeration_selects_lean_over_cheaper_cash_bulk(search_inputs):
    result = search_economics(search_inputs)
    assert result.status == "OK", result
    assert result.search_complete and result.optimal_in_domain
    assert result.domain_size == result.evaluated == 4
    assert (
        result.candidate
        and result.candidate.purchase.lines == candidate().purchase.lines
    )
    assert result.validation and cost(result.validation).primary_sgd == D("63.75")
    assert result.context is not None and result.validation.context == result.context
    assert (
        result.no_action
        and result.no_action.rollout
        and result.no_action.rollout.ledger
    )
    assert (
        result.no_action.rollout.ledger.components
        and result.no_action.rollout.ledger.components.primary_sgd == 140
    )
    assert not result.no_action.actionable
    # Independently: 20 ordinary 1.5 kg purchases cost60; bulk initial3+1.5disposal=4.5.
    assert cost(
        validate_economic_candidate(search_inputs, candidate("a-bulk", "3"))
    ).primary_sgd == D("64.50")


def test_validator_recomputes_without_invoking_search(search_inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("validator called optimiser")

    monkeypatch.setattr("src.economic_search.search_economics", forbidden)
    assert cost(
        validate_economic_candidate(search_inputs, candidate())
    ).primary_sgd == D("63.75")


def test_tampered_cost_and_continuation_claims_rejected(search_inputs):
    valid = validate_economic_candidate(search_inputs, candidate())
    ledger = cost(valid)
    bad = replace(
        candidate(),
        claimed_components=replace(ledger, acquisition=D(0)),
        claimed_future_lines=(),
    )
    actual = validate_economic_candidate(search_inputs, bad)
    assert actual.complete and not actual.feasible
    assert {f.code for f in actual.violations} == {
        "ECONOMIC_CLAIM_MISMATCH",
        "CONTINUATION_CLAIM_MISMATCH",
    }


def test_current_shortage_cannot_be_certified_by_future_continuation(search_inputs):
    actual = validate_economic_candidate(
        search_inputs, EconomicCandidate(PurchaseCandidate(()))
    )
    assert actual.complete and actual.feasible is False and actual.continuation is None
    assert "SHORTAGE" in {f.code for f in actual.violations}


def test_budget_proves_infeasibility_with_correct_constraint(search_inputs):
    p = replace(
        search_inputs,
        continuation=replace(search_inputs.continuation, incremental_budget=D(2)),
    )
    actual = search_economics(p)
    assert actual.status == "INFEASIBLE" and actual.search_complete
    assert actual.reason == "NO_FEASIBLE_CANDIDATE_IN_DOMAIN"
    assert actual.candidate is None and "BUDGET" in dict(actual.rejection_counts)


def test_search_limit_after_feasible_incumbent_is_not_actionable(search_inputs):
    # The empty action is rejected; lean is next and feasible. Stop before bulk.
    actual = search_economics(replace(search_inputs, score_limit=2))
    assert actual.status == "INCOMPLETE" and actual.reason == "SEARCH_LIMIT_REACHED"
    assert not actual.search_complete and not actual.optimal_in_domain
    assert actual.candidate is None and actual.validation is None
    assert actual.diagnostic_incumbent is not None


def test_missing_economic_input_does_not_fall_back_to_cash(search_inputs):
    routine = search_inputs.continuation
    p = replace(
        search_inputs,
        continuation=replace(routine, rollout=replace(routine.rollout, asset_terms={})),
    )
    actual = search_economics(p)
    assert actual.status == "INCOMPLETE" and actual.candidate is None
    assert "MISSING_ASSET_VALUATION" in {f.code for f in actual.findings}
    assert actual.context is not None
    assert actual.context.rollout.issue_time == ISSUE
    assert actual.context.rollout.horizon_end == END
    assert actual.context.rollout.captured_revision == EV.captured_revision
    assert dict(actual.context.policies)["objective"] == OBJECTIVE_POLICY
    assert dict(actual.context.sources)["offer:a-bulk"] == EV


def test_current_and_future_authorization_are_separate(search_inputs):
    actual = validate_economic_candidate(
        search_inputs, candidate("routine-chicken-1", "1.5")
    )
    assert actual.complete and not actual.feasible
    assert "FUTURE_LINE_IN_CURRENT_ACTION" in {f.code for f in actual.violations}
    assert (
        search_economics(
            replace(search_inputs, current_ingredient_manifest=None)
        ).status
        == "INCOMPLETE"
    )


def test_terminal_sensitivity_changes_ranking_with_same_21_date_horizon(search_inputs):
    routine = search_inputs.continuation
    inv = dict(routine.rollout.inventory)
    inv["forecasts"] = tuple(
        f
        if f.target_date == ISSUE.date()
        else replace(
            f,
            buckets=allocate_service_buckets(
                {d.id: D(0) for d in inv["menu_items"]},
                inv["menu_items"],
                target_date=f.target_date,
                profile=f.profile,
            ),
        )
        for f in inv["forecasts"]
    )
    ops = tuple(
        replace(o, expiry_date=(END + timedelta(days=1)).date())
        if o.id == "a-bulk"
        else o
        for o in routine.supply.opportunities
    )
    offers = tuple(
        o.model_copy(update={"unit_price": D("1.4"), "shelf_life_days_on_arrival": 23})
        if o.id == "a-bulk"
        else o
        for o in routine.supply.offers
    )
    p = replace(
        search_inputs,
        continuation=replace(
            routine,
            rollout=replace(routine.rollout, inventory=inv),
            supply=replace(routine.supply, opportunities=ops, offers=offers),
        ),
    )
    zero = search_economics(p)
    assert (
        zero.candidate and zero.candidate.purchase.lines == candidate().purchase.lines
    )
    assert zero.validation and cost(zero.validation).primary_sgd == D("3.75")
    book = search_economics(
        replace(
            p,
            continuation=replace(
                p.continuation,
                rollout=replace(
                    p.continuation.rollout, terminal_policy="BOOK_TERMINAL_V1"
                ),
            ),
        )
    )
    assert (
        book.candidate
        and book.candidate.purchase.lines == candidate("a-bulk", "3").purchase.lines
    )
    assert book.validation and cost(book.validation).primary_sgd == D(
        "2.10"
    )  # 4.2-1.5*1.4


def test_explicit_no_current_domain_can_return_no_purchase(routine):
    p = EconomicSearchInputs(
        routine,
        (),
        SEARCH_POLICY,
        OBJECTIVE_POLICY,
        TIE_POLICY,
        1000000,
        33,
        timeout_seconds=120.0,
    )
    actual = search_economics(p)
    assert (
        actual.status == "OK"
        and actual.candidate
        and actual.candidate.purchase.lines == ()
    )
    assert actual.domain_size == actual.evaluated == 1


def test_huge_domain_is_not_materialised_or_claimed_infeasible(search_inputs):
    p = search_inputs.continuation
    offers = tuple(
        o.model_copy(update={"available_quantity": D("1e20")})
        if o.id == "a-bulk"
        else o
        for o in p.supply.offers
    )
    windows = tuple(
        replace(w, available_quantity=D("1e20")) if w.id == "a-bulk" else w
        for w in p.supply.windows
    )
    actual = search_economics(
        replace(
            search_inputs,
            continuation=replace(
                p, supply=replace(p.supply, offers=offers, windows=windows)
            ),
        )
    )
    assert actual.status == "INCOMPLETE" and actual.reason == "SEARCH_LIMIT_REACHED"
    assert actual.evaluated == 0 and actual.candidate is None


def test_current_protection_does_not_use_stockout_limited_sales(search_inputs):
    routine = search_inputs.continuation
    inv = dict(routine.rollout.inventory)
    inv["opening_lots"] = tuple(
        l.model_copy(update={"quantity": D(5)}) if l.ingredient_id == "rice" else l
        for l in inv["opening_lots"]
    )
    p = replace(
        search_inputs,
        continuation=replace(routine, rollout=replace(routine.rollout, inventory=inv)),
    )
    actual = validate_economic_candidate(p, candidate())
    # Rice must cover its full14-date window (14kg), even though absent future
    # chicken would suppress coupled service/consumption after the first day.
    assert actual.complete and not actual.feasible
    assert any(
        f.code == "SHORTAGE" and f.source.startswith("rice@") for f in actual.violations
    )
    assert actual.context is not None and actual.context.current_ingredients == (
        "chicken",
    )


def test_current_split_supplier_is_enumerated_and_independently_validated(
    search_inputs,
):
    routine = search_inputs.continuation
    offers = tuple(
        o.model_copy(
            update={
                "supplier_id": "supplier-two" if o.id == "b-lean" else o.supplier_id,
                "pack_size": D("0.75"),
                "moq": D("0.75"),
                "available_quantity": D("0.75"),
                "unit_price": D(1) if o.id == "a-bulk" else D(2),
            }
        )
        if o.id in ("a-bulk", "b-lean")
        else o
        for o in routine.supply.offers
    )
    windows = tuple(
        replace(w, available_quantity=D("0.75")) if w.id in ("a-bulk", "b-lean") else w
        for w in routine.supply.windows
    )
    supply = replace(
        routine.supply,
        offers=offers,
        windows=windows,
        suppliers=(
            *routine.supply.suppliers,
            Supplier(id="supplier-two", name="Second synthetic supplier"),
        ),
        approved_offer_manifest=tuple(
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ),
    )
    p = replace(search_inputs, continuation=replace(routine, supply=supply))
    result = search_economics(p)
    assert (
        result.status == "OK"
        and result.candidate
        and len(result.candidate.purchase.lines) == 2
    )
    assert result.domain_size == result.evaluated == 4
    assert {line.quantity for line in result.candidate.purchase.lines} == {D("0.75")}
    assert cost(validate_economic_candidate(p, result.candidate)).primary_sgd == D(
        "62.25"
    )  # .75*1+.75*2+60


def test_economic_tie_is_stable_and_reliability_only_changes_are_inert(search_inputs):
    routine = search_inputs.continuation
    offers = tuple(
        o.model_copy(
            update={
                "pack_size": D("1.5"),
                "moq": D("1.5"),
                "available_quantity": D("1.5"),
                "unit_price": D("2.5"),
            }
        )
        if o.id == "a-bulk"
        else o
        for o in routine.supply.offers
    )
    windows = tuple(
        replace(w, available_quantity=D("1.5")) if w.id == "a-bulk" else w
        for w in routine.supply.windows
    )
    p = replace(
        search_inputs,
        continuation=replace(
            routine, supply=replace(routine.supply, offers=offers, windows=windows)
        ),
    )
    first = search_economics(p)
    assert (
        first.candidate
        and first.candidate.purchase.lines == candidate("a-bulk", "1.5").purchase.lines
    )
    changed = replace(
        p.continuation.supply,
        offers=tuple(
            o.model_copy(
                update={"recent_on_time_rate": D("0.01") if o.id == "a-bulk" else D(1)}
            )
            for o in reversed(offers)
        ),
        opportunities=tuple(reversed(p.continuation.supply.opportunities)),
    )
    again = search_economics(
        replace(p, continuation=replace(p.continuation, supply=changed))
    )
    assert first == again


def test_search_host_deadline_and_missing_deadline_are_explicit(
    search_inputs, monkeypatch
):
    absent = search_economics(replace(search_inputs, timeout_seconds=None))
    assert absent.status == "INCOMPLETE" and {f.code for f in absent.findings} == {
        "MISSING_HOST_DEADLINE"
    }
    monkeypatch.setattr("src.economic_rollout.monotonic", lambda: 1e100)
    actual = search_economics(search_inputs)
    assert actual.status == "INCOMPLETE" and actual.reason == "SEARCH_LIMIT_REACHED"
    assert actual.candidate is None and not actual.optimal_in_domain

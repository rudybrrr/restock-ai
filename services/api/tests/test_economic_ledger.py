"""Independent accounting oracles, not procurement or live-profit assertions."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from src.contingency import ShipmentCharge
from src.economic_ledger import (
    LEDGER_POLICY,
    MONEY_POLICY,
    AssetFlow,
    DishService,
    score_ledger,
)
from src.inventory_projection import SourceEvidence
from src.schemas import Ingredient, MenuItem

D = Decimal
START = datetime.fromisoformat("2026-02-16T00:00:00+08:00")
END = START + timedelta(days=21)


def asset(q="10", allocated="5", expired="5", ending="0", price="1", disposal="1"):
    return AssetFlow(
        "synthetic-chicken",
        "chicken",
        "kg",
        "NEW_PURCHASE",
        D(q),
        D(allocated),
        D(expired),
        D(ending),
        D(0),
        D(price),
        D(disposal),
    )


@pytest.fixture
def scope():
    return {
        "ingredients": [
            Ingredient(
                id="chicken",
                name="Chicken",
                unit="kg",
                interval_days=1,
                starting_date=date(2026, 2, 15),
            )
        ],
        "menu_items": [MenuItem(id="chicken-rice", name="Chicken rice")],
        "asset_manifest": ["synthetic-chicken"],
        "service_manifest": [],
        "shipment_manifest": [],
        "start": START,
        "end": END,
        "known_at": START,
        "captured_revision": "fixture-ledger-1",
        "evidence": {
            name: SourceEvidence(f"synthetic:{name}", START, "fixture-ledger-1")
            for name in (
                "assets",
                "service",
                "shipments",
                "valuation",
                "policy",
                "catalogue",
            )
        },
        "ledger_policy": LEDGER_POLICY,
        "money_policy": MONEY_POLICY,
        "terminal_policy": "ZERO_TERMINAL_V1",
        "provenance": "PROJECTED",
    }


def components(scope, assets, service=(), shipments=()):
    result = score_ledger(assets, service, shipments, **scope)
    assert result.complete and result.components is not None
    return result.components


def test_v3_cheap_bulk_loses_to_smaller_purchase_without_double_charging(scope):
    # Isolated chicken terms: every other catalogue term is the same constant K.
    # A: 10 kg * $1 plus 5 expired kg * $1 incremental disposal = $15.
    # B: 5 kg * $2.20, all used = $11. Cash-only would incorrectly prefer A.
    bulk = components(scope, [asset()])
    small = components(scope, [asset(q="5", expired="0", price="2.20")])
    assert bulk.acquisition == 10 and small.acquisition == 11
    assert bulk.expired_book == 5 and bulk.disposal_incremental == 5
    assert bulk.primary_sgd == D("15.00")
    assert small.primary_sgd == D("11.00")
    assert bulk.primary_total != 20  # book-valued expiry is not charged again


def test_terminal_sensitivity_reverses_ranking_without_calling_leftovers_waste(scope):
    bulk = components(scope, [asset(expired="0", ending="5", price="1.20")])
    small = components(scope, [asset(q="5", expired="0", price="2.20")])
    assert bulk.zero_terminal_total == 12 > small.zero_terminal_total == 11
    assert bulk.book_terminal_total == 6 < small.book_terminal_total == 11
    assert bulk.expired_book == 0 and bulk.terminal_usable_book == 6
    scope["terminal_policy"] = "BOOK_TERMINAL_V1"
    assert components(
        scope, [asset(expired="0", ending="5", price="1.20")]
    ).primary_sgd == D("6.00")


def test_expired_stock_has_no_terminal_credit(scope):
    scope["terminal_policy"] = "BOOK_TERMINAL_V1"
    result = components(scope, [asset(price="1.20", disposal="0")])
    assert result.zero_terminal_total == result.book_terminal_total == 12
    assert result.terminal_usable_book == 0 and result.expired_book == 6


@pytest.mark.parametrize(
    "served,acquisition,total", [("10", "20", "20"), ("5", "10", "50")]
)
def test_v2_contribution_identity_not_gross_lost_sales_twice(
    scope, served, acquisition, total
):
    # Accounting-only unit oracle: $2 resource cost per served portion, price $10,
    # noningredient variable cost $2. This does not redefine the canonical recipe.
    flow = asset(q=served, allocated=served, expired="0", price="2", disposal="0")
    demand = DishService(
        START + timedelta(hours=11),
        START + timedelta(hours=12),
        "chicken-rice",
        D(10),
        D(served),
        D(10),
        D(2),
    )
    scope["service_manifest"] = [(demand.start, demand.end, demand.menu_item_id)]
    result = components(scope, [flow], [demand])
    assert result.acquisition == D(acquisition)
    assert result.primary_sgd == D(total)
    assert D(80) - result.primary_total == (D(60) if served == "10" else D(30))
    if served == "5":
        assert result.unmet_contribution == 40 and result.gross_lost_sales == 50


def test_fixed_part_received_commitment_is_opening_asset_not_new_acquisition(scope):
    # Original 10 kg: 6 already received, 1 cancelled, 3 outstanding.
    # Received quantity appears only as the opening lot. All prices $2/kg.
    opening = replace(
        asset(q="6", allocated="6", expired="0", price="2"),
        origin="OPENING",
        reference="received-6",
    )
    incoming = replace(
        asset(q="3", allocated="0", expired="0", price="2"),
        origin="FIXED_COMMITMENT",
        reference="outstanding-3",
        ending_incoming=D(3),
    )
    scope["asset_manifest"] = ["received-6", "outstanding-3"]
    result = components(scope, [opening, incoming])
    assert result.opening_assets == 18 and result.acquisition == 0
    assert result.terminal_incoming_book == 6
    assert result.zero_terminal_total == 18 and result.book_terminal_total == 12


def test_new_shipment_charged_once_and_emergency_is_exclusive(scope):
    scope["shipment_manifest"] = ["new-shipment"]
    fees = [
        ShipmentCharge("new-shipment", "fresh", START + timedelta(hours=8), D(3), D(4))
    ]
    result = components(
        scope, [asset(q="4", allocated="4", expired="0", price="2")], shipments=fees
    )
    assert (
        result.acquisition == 8 and result.delivery == 3 and result.emergency_extra == 4
    )
    assert result.primary_sgd == D("15.00")
    with pytest.raises(ValueError, match="Duplicate economic shipments"):
        components(scope, [asset()], shipments=fees + fees)


def test_missing_valuation_evidence_produces_no_cash_fallback(scope):
    scope["evidence"].pop("valuation")
    result = score_ledger([asset()], [], [], **scope)
    assert not result.complete and result.components is None
    assert result.expired_quantities is None
    assert any(f.source == "valuation" for f in result.findings)


@pytest.mark.parametrize("key", ["ledger_policy", "terminal_policy", "money_policy"])
def test_missing_policy_is_incomplete(scope, key):
    scope[key] = None
    result = score_ledger([asset()], [], [], **scope)
    assert not result.complete and result.components is None
    assert result.findings[0].code == "ECONOMIC_POLICY_UNRESOLVED"


def test_missing_ledger_row_is_not_zero(scope):
    result = score_ledger([], [], [], **scope)
    assert not result.complete and result.components is None
    assert result.findings[0].code == "ECONOMIC_COVERAGE_MISMATCH"


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": D(9)},
        {"allocated": D(-1)},
        {"unit_cost": D("NaN")},
        {"ingredient_id": "unknown"},
        {"unit": "litres"},
        {"ending_incoming": D(1)},
        {"origin": "FUTURE_TRUTH"},
    ],
)
def test_tampered_asset_is_rejected(scope, change):
    with pytest.raises(ValueError):
        components(scope, [replace(asset(), **change)])


def test_duplicate_asset_cannot_double_count_acquisition(scope):
    with pytest.raises(ValueError, match="Duplicate economic assets"):
        components(scope, [asset(), asset()])


def test_service_overlaps_and_overserving_rejected(scope):
    first = DishService(
        START, START + timedelta(hours=1), "chicken-rice", D(2), D(1), D(5), D(1)
    )
    second = replace(first, start=START + timedelta(minutes=30))
    scope["service_manifest"] = [
        (s.start, s.end, s.menu_item_id) for s in (first, second)
    ]
    with pytest.raises(ValueError, match="Overlapping"):
        components(scope, [asset()], [first, second])
    scope["service_manifest"] = [(first.start, first.end, first.menu_item_id)]
    with pytest.raises(ValueError, match="exceed"):
        components(scope, [asset()], [replace(first, served=D(3))])


def test_final_cent_rounding_preserves_exact_components_and_caller_context(scope):
    row = asset(q="1", allocated="1", expired="0", price="1.225")
    with localcontext() as ctx:
        ctx.prec = 2
        result = components(scope, [row])
    assert result.acquisition == result.primary_total == D("1.225")
    assert result.primary_sgd == D("1.22")
    assert row.unit_cost == D("1.225")
    assert result == components(scope, [row])


def test_identical_projected_and_realised_ledger_has_identical_components(scope):
    projected = components(scope, [asset()])
    scope["provenance"] = "REALISED"
    assert components(scope, [asset()]) == projected

"""Hand-derived multi-day oracles; no optimiser or database supplies answers."""

import copy
import json
import subprocess
import sys
from dataclasses import fields
from datetime import datetime
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path

import pytest

from src.forecasting import seasonal_baseline
from src.history_dataset import Catalogue, canonical_json, sha256
from src.physical_scenario import (
    PhysicalScenario,
    scenario_observations_at,
    simulate_scenario,
)

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal


def at(day, clock):
    return datetime.fromisoformat(f"2026-02-{day:02d}T{clock}:00+08:00")


@pytest.fixture
def raw():
    return json.loads((FIXTURES / "physical_seven_days_v1.json").read_text())


@pytest.fixture
def catalogue():
    raw = json.loads((FIXTURES / "seasonal_baseline_v3.json").read_text())
    return Catalogue.model_validate(
        {k: raw[k] for k in ("menu_items", "ingredients", "recipes")}
    )


def run(raw, catalogue):
    return simulate_scenario(PhysicalScenario.model_validate(raw), catalogue)


def by_id(rows):
    return {r.identity: r for r in rows}


def test_seven_day_independent_oracle(raw, catalogue):
    result = run(raw, catalogue)
    # Chicken rice is .150 kg chicken + .100 kg rice + .010 litres soy/portion.
    # Four fulfilled pairs plus three ordinary transactions -> 11 served, 7 paid.
    assert (
        result.totals.attempted,
        result.totals.served,
        result.totals.unmet,
        result.totals.paid,
        result.totals.free,
        result.totals.revenue,
    ) == (15, 11, 4, 7, 4, D("35"))
    assert [
        (d.sales.attempted, d.sales.served, d.sales.unmet, d.sales.revenue)
        for d in result.days
    ] == [
        (3, 3, 0, D("10")),
        (1, 1, 0, D("5")),
        (3, 2, 1, D("5")),
        (3, 3, 0, D("10")),
        (2, 0, 2, D("0")),
        (0, 0, 0, D("0")),
        (3, 2, 1, D("5")),
    ]
    ingredients = by_id(result.ingredients)
    chicken = ingredients["chicken"]
    assert (
        chicken.opening,
        chicken.received,
        chicken.consumed,
        chicken.hidden_loss,
        chicken.newly_expired,
        chicken.disposed,
        chicken.closing_usable,
        chicken.closing_expired,
    ) == (D(".6"), D("1.35"), D("1.65"), D(".15"), D(".15"), D(".1"), D(0), D(".05"))
    assert (
        ingredients["rice"].consumed,
        ingredients["rice"].hidden_loss,
        ingredients["rice"].closing_usable,
    ) == (D("1.1"), D(".2"), D("1.7"))
    assert (
        ingredients["soy-sauce"].consumed,
        ingredients["soy-sauce"].closing_usable,
    ) == (D(".11"), D(".89"))
    assert len(ingredients) == 8
    for i in ("eggs", "oil", "noodles", "tofu"):
        assert (
            ingredients[i].opening
            == ingredients[i].received
            == ingredients[i].consumed
            == 0
        )


def test_whole_run_lot_ingredient_and_commitment_conservation(raw, catalogue):
    result = run(raw, catalogue)
    for l in result.lots + result.ingredients:
        assert (
            l.opening + l.received
            == l.consumed
            + l.hidden_loss
            + l.disposed
            + l.closing_usable
            + l.closing_expired
        )
    # Expiry is a transfer, NOT a physical outflow or an extra deduction.
    lots = by_id(result.lots)
    assert lots["chicken-opening"].opening_expired + lots[
        "chicken-opening"
    ].newly_expired == D(".15")
    assert lots["chicken-opening"].disposed + lots[
        "chicken-opening"
    ].closing_expired == D(".15")
    for c in result.commitments:
        assert c.total == c.received + c.cancelled + c.outstanding
    commitments = {c.delivery_id: c for c in result.commitments}
    c = commitments["opening-chicken"]
    assert (c.total, c.received, c.cancelled, c.outstanding) == (
        D("1.5"),
        D("1.05"),
        D(".45"),
        D(0),
    )
    assert commitments["contingency-chicken"].received == D(".9")
    # Prior .600 receipt belongs only to opening, not this run's 1.350 receipts.
    assert sum(
        (m.quantity for m in result.movements if m.kind == "RECEIPT"), D(0)
    ) == D("1.35")


def test_two_day_continuity_is_not_a_new_count(raw, catalogue):
    raw["days"] = raw["days"][:2]
    raw["end"] = at(18, "00:00").isoformat()
    for key in ("orders", "counts"):
        raw[key] = [
            e for e in raw[key] if datetime.fromisoformat(e["at"]) < at(18, "00:00")
        ]
    raw["receipts"] = raw["receipts"][:1]
    for key in ("purchases", "cancellations", "disposals", "hidden_losses"):
        raw[key] = []
    result = run(raw, catalogue)
    assert result.days[0].closing == result.days[1].opening
    balances = {l.lot_id: l for l in result.days[1].opening}
    assert balances["rice-opening"].usable == D("2.7")
    assert balances["chicken-opening"].retained_expired == D(".15")
    assert balances["chicken-opening"].received_at == at(15, "08:00")
    assert "counted_at" not in {f.name for f in fields(balances["rice-opening"])}
    assert [c.at for c in result.observations.counts] == [
        at(16, "00:00"),
        at(16, "22:00"),
        at(17, "22:00"),
    ]
    assert (result.totals.served, result.totals.revenue) == (4, D("15"))
    assert by_id(result.ingredients)["rice"].closing_usable == D("2.6")
    assert result.commitments[0].outstanding == D(".45")


def test_expiry_once_overnight_and_explicit_disposal(raw, catalogue):
    result = run(raw, catalogue)
    expiries = [
        (m.at, m.lot_id, m.quantity) for m in result.movements if m.kind == "EXPIRY"
    ]
    assert expiries == [
        (at(17, "00:00"), "chicken-opening", D(".15")),
        (at(18, "00:00"), "veg-fresh", D(".2")),
    ]
    vegetables = by_id(result.ingredients)["vegetables"]
    assert (
        vegetables.opening_expired,
        vegetables.newly_expired,
        vegetables.closing_expired,
    ) == (D(".1"), D(".2"), D(".3"))
    assert all(
        d.closing == next_day.opening
        for d, next_day in zip(result.days, result.days[1:])
    )
    assert len([m for m in result.movements if m.kind == "DISPOSAL"]) == 1
    counts = {c.id: c for c in result.observations.counts}
    assert next(
        l.quantity for l in counts["count-20"].lots if l.id == "chicken-opening"
    ) == D(".15")
    assert next(
        l.quantity for l in counts["count-21"].lots if l.id == "chicken-opening"
    ) == D(".05")


def test_late_receipts_do_not_repair_past_shortages(raw, catalogue):
    result = run(raw, catalogue)
    failed = {o.order_id: o for o in result.outcomes if o.unmet}
    assert set(failed) == {"order-18-1", "order-20-0", "order-20-1", "order-22-1"}
    # Placement at 12:30 and expected 17:00 never create day-three physical stock.
    assert not any(
        m.kind == "RECEIPT" and m.at.date() == at(18, "00:00").date()
        for m in result.movements
    )
    assert next(
        m.at for m in result.movements if m.source_id == "contingency-first"
    ) == at(19, "01:00")


def test_atomic_pair_and_multiple_missing_ingredients(raw, catalogue):
    raw["opening_lots"][1]["quantity"] = ".100"
    raw["hidden_losses"] = [e for e in raw["hidden_losses"] if e["id"] != "hidden-rice"]
    result = run(raw, catalogue)
    outcomes = {o.order_id: o for o in result.outcomes}
    assert (
        outcomes["order-16-0"].served,
        outcomes["order-16-1"].served,
        outcomes["order-16-1"].unmet,
    ) == (1, 0, 2)
    assert by_id(result.ingredients)["chicken"].consumed == D(".15")
    assert by_id(result.ingredients)["rice"].consumed == D(".1")
    # The later tofu order misses several ingredients but still only one portion.
    assert len(outcomes["order-20-1"].missing_ingredients) > 1
    assert outcomes["order-20-1"].unmet == 1


def test_counts_and_availability_do_not_expose_hidden_loss_or_future(raw, catalogue):
    result = run(raw, catalogue)
    before = scenario_observations_at(result.observations, known_at=at(20, "22:04"))
    after = scenario_observations_at(result.observations, known_at=at(20, "22:05"))
    assert "count-20" not in {c.id for c in before.counts}
    count = next(c for c in after.counts if c.id == "count-20")
    rice = next(l for l in count.lots if l.id == "rice-opening")
    # Nine portions to day four: 3 - .9 sales - .2 hidden loss = 1.9 physical.
    assert rice.quantity == D("1.9")
    assert rice.counted_at == at(20, "22:00")
    assert not {"hidden_losses", "orders", "outcomes", "movements", "days"} & {
        f.name for f in fields(after)
    }
    assert all(r.receipt.received_at <= at(20, "22:05") for r in after.receipts)
    assert all(
        b.batch.period_start != at(20, "07:00")
        and b.batch.period_end != at(20, "07:00")
        for b in after.batches
    )
    # Quantity discrepancies are measurable, but no loss explanation is published.
    assert not hasattr(rice, "hidden_loss")


def test_observation_only_seam_defensive_copies_and_explicit_zeros(raw, catalogue):
    result = run(raw, catalogue)
    assert (
        scenario_observations_at(result.observations, known_at=at(16, "00:04")).counts
        == ()
    )
    observed = scenario_observations_at(result.observations, known_at=at(23, "00:05"))
    zero = next(
        d for d in observed.daily if d.sales.service_date == at(21, "00:00").date()
    )
    assert len(zero.sales.portions) == 5 and set(zero.sales.portions.values()) == {0}
    assert not any(
        d.sales.service_date == at(21, "00:00").date()
        for d in scenario_observations_at(
            result.observations, known_at=at(21, "22:04")
        ).daily
    )
    observed.counts[0].lots[0].quantity = D(999)
    observed.batches[0].batch.sales["chicken-rice"] = 999
    assert result.observations.counts[0].lots[0].quantity != 999
    assert result.observations.batches[0].batch.sales["chicken-rice"] != 999
    with pytest.raises(ValueError, match="timezone-aware"):
        scenario_observations_at(
            result.observations, known_at=at(23, "00:00").replace(tzinfo=None)
        )


def test_reporting_and_counts_never_consume_again(raw, catalogue):
    result = run(raw, catalogue)
    raw["counts"] = []
    for d in raw["days"]:
        d["daily_available_at"] = at(24, "22:00").isoformat()
        d["batch_reporting_delay_seconds"] = 90000
    delayed = run(raw, catalogue)
    assert delayed.lots == result.lots and delayed.outcomes == result.outcomes
    observed = scenario_observations_at(result.observations, known_at=at(23, "01:00"))
    assert sum(sum(b.batch.sales.values()) for b in observed.batches) == 11
    assert sum(sum(d.sales.portions.values()) for d in observed.daily) == 11
    assert by_id(result.ingredients)["chicken"].consumed == D("1.65")
    # Forecast API accepts finals, not finals+batch additions; eligibility/warmup stays explicit.
    forecast = seasonal_baseline(
        [d.sales for d in observed.daily],
        catalogue.menu_items,
        issue_time=at(23, "01:00"),
        target_date=at(23, "00:00").date(),
    )
    assert forecast["chicken-rice"].expected_portions is None


def test_reordered_inputs_determinism_no_mutation_and_decimal_context(raw, catalogue):
    model = PhysicalScenario.model_validate(raw)
    original = model.model_dump()
    result = simulate_scenario(model, catalogue)
    assert simulate_scenario(model, catalogue) == result
    assert model.model_dump() == original
    for key in (
        "opening_lots",
        "orders",
        "receipts",
        "cancellations",
        "commitments",
        "purchases",
        "hidden_losses",
        "counts",
        "disposals",
    ):
        raw[key].reverse()
    for day in raw["days"]:
        day["profile"].reverse()
    for ids in raw["opening_manifest"].values():
        ids.reverse()
    with localcontext() as context:
        context.prec = 2
        assert run(raw, catalogue) == result


def test_identical_demand_different_external_actions_are_isolated(raw, catalogue):
    original = run(raw, catalogue)
    changed = copy.deepcopy(raw)
    changed["purchases"] = []
    changed["receipts"] = changed["receipts"][:1]
    changed["hidden_losses"] = [
        e for e in changed["hidden_losses"] if e["id"] != "hidden-chicken"
    ]
    alternate = run(changed, catalogue)
    assert (
        alternate.totals.attempted,
        alternate.totals.served,
        alternate.totals.revenue,
    ) == (15, 6, D("20"))
    assert raw["orders"] == changed["orders"]
    assert run(raw, catalogue) == original


@pytest.mark.parametrize(
    "kind", ["receipt-id", "retry", "lot-id", "old-retry", "old-id"]
)
def test_cross_day_retry_and_conflicting_identity_rejected(raw, catalogue, kind):
    duplicate = copy.deepcopy(raw["receipts"][0])
    duplicate["receipt"].update(
        id="another-receipt",
        lot_id="another-lot",
        request_id="another-slip",
        received_at=at(18, "01:00").isoformat(),
    )
    duplicate["available_at"] = at(18, "01:05").isoformat()
    field, value = {
        "receipt-id": ("id", "partial-overnight"),
        "retry": ("request_id", "partial-overnight-slip"),
        "lot-id": ("lot_id", "chicken-partial"),
        "old-retry": ("request_id", "prior-receipt-slip"),
        "old-id": ("id", "prior-receipt"),
    }[kind]
    duplicate["receipt"][field] = value
    raw["receipts"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate"):
        run(raw, catalogue)


def test_same_request_id_different_deliveries_allowed(raw, catalogue):
    raw["receipts"][1]["receipt"]["request_id"] = raw["receipts"][0]["receipt"][
        "request_id"
    ]
    assert run(raw, catalogue).totals.served == 11


def test_midnight_receipt_carries_stock_without_a_midnight_count(raw, catalogue):
    raw["receipts"][0]["receipt"]["received_at"] = at(17, "00:00").isoformat()
    result = run(raw, catalogue)
    prior_close = {l.lot_id: l for l in result.days[0].closing}
    assert prior_close["chicken-partial"].usable == D(".45")
    assert result.days[0].closing == result.days[1].opening
    assert not any(c.at == at(17, "00:00") for c in result.observations.counts)
    assert result.totals.served == 11


def test_explicit_usable_disposal_and_no_implicit_removal(raw, catalogue):
    raw["disposals"].append(
        {
            "id": "dispose-rice",
            "at": at(21, "09:00").isoformat(),
            "available_at": at(21, "09:01").isoformat(),
            "lot_id": "rice-opening",
            "quantity": ".400",
            "pool": "USABLE",
        }
    )
    result = run(raw, catalogue)
    rice = by_id(result.ingredients)["rice"]
    assert (rice.disposed, rice.closing_usable, rice.consumed) == (
        D(".4"),
        D("1.3"),
        D("1.1"),
    )
    assert (
        rice.opening
        == rice.disposed + rice.closing_usable + rice.consumed + rice.hidden_loss
    )


def test_contiguous_complete_batches_and_late_receipt_boundaries(raw, catalogue):
    raw["receipts"][0]["available_at"] = at(17, "12:00").isoformat()
    result = run(raw, catalogue)
    batches = result.observations.batches
    assert batches[0].batch.period_start == at(16, "00:00")
    assert batches[-1].batch.period_end == at(23, "00:00")
    assert all(a.batch.period_end == b.batch.period_start for a, b in pairwise(batches))
    assert all(len(b.batch.sales) == 5 for b in batches)
    before = scenario_observations_at(result.observations, known_at=at(17, "11:59"))
    assert not before.receipts
    assert not any(
        at(17, "01:00") in (b.batch.period_start, b.batch.period_end)
        for b in before.batches
    )


def test_known_opening_commitments_and_external_actions_are_not_future_outcomes(
    raw, catalogue
):
    result = run(raw, catalogue)
    before = scenario_observations_at(result.observations, known_at=at(16, "00:04"))
    assert before.opening_commitments == ()
    opening = scenario_observations_at(result.observations, known_at=at(16, "00:05"))
    assert len(opening.opening_commitments) == 1
    assert opening.opening_commitments[0].delivery.outstanding_quantity == D(".9")
    assert opening.receipts == opening.purchases == ()
    before = scenario_observations_at(result.observations, known_at=at(18, "12:34"))
    after = scenario_observations_at(result.observations, known_at=at(18, "12:35"))
    assert before.purchases == ()
    assert len(after.purchases) == 1
    assert after.purchases[0].delivery.received_quantity == 0
    assert after.purchases[0].delivery.outstanding_quantity == D(".9")
    # Observed placement is never mutated into its later realised receipt state.
    assert after.purchases[0].delivery.receipts == []


@pytest.mark.parametrize(
    "what", ["over-receipt", "over-cancel", "cancel-before-receipt", "after-cancel"]
)
def test_outstanding_reconciliation_rejects_excess(raw, catalogue, what):
    if what == "over-receipt":
        raw["receipts"][0]["receipt"]["quantity"] = "1"
    elif what == "over-cancel":
        raw["cancellations"][0]["quantity"] = ".451"
    elif what == "cancel-before-receipt":
        raw["cancellations"][0].update(
            at=at(16, "10:00").isoformat(),
            available_at=at(16, "10:05").isoformat(),
            quantity=".900",
        )
    else:
        raw["receipts"][0]["receipt"]["remainder"] = "CANCELLED"
    with pytest.raises(ValueError, match="outstanding"):
        run(raw, catalogue)


def test_equal_time_sale_precedes_receipt(raw, catalogue):
    raw["orders"][3]["at"] = at(19, "11:05").isoformat()  # ordinarily day-three pair
    raw["receipts"][1]["receipt"]["received_at"] = at(19, "11:05").isoformat()
    raw["receipts"][1]["available_at"] = at(19, "11:06").isoformat()
    result = run(raw, catalogue)
    # Earlier day-three ordinary used .150; only .150 remains for .300 pair.
    outcome = next(o for o in result.outcomes if o.order_id == "order-18-0")
    assert outcome.served == 0 and outcome.unmet == 2


@pytest.mark.parametrize(
    "path,value,match",
    [
        (("catalogue_sha256",), "wrong", "hash mismatch"),
        (("recipe_sha256",), "wrong", "hash mismatch"),
        (("end",), "2026-02-22T23:00:00+08:00", "calendar days"),
        (("days", 1, "target_date"), "2026-02-19", "consecutive"),
        (("opening_available_at",), "2026-02-15T23:00:00+08:00", "Opening count"),
        (
            ("days", 0, "daily_available_at"),
            "2026-02-16T12:00:00+08:00",
            "service ends",
        ),
        (("orders", 0, "at"), "2026-02-16T08:00:00+08:00", "outside"),
        (("orders", 0, "at"), "2026-02-16T11:05:00", "timezone"),
        (("orders", 0, "unit_price"), "NaN", "finite"),
        (("orders", 0, "unit_price"), "-1", "greater"),
        (("orders", 0, "menu_item_id"), "unknown", "Unknown dish"),
        (("orders", 1, "promotion_reference"), None, "promotional pair"),
        (("opening_lots", 1, "unit"), "litres", "Invalid opening"),
        (("purchases", 0, "delivery", "received_quantity"), ".1", "Invalid new"),
        (("purchases", 0, "delivery", "outstanding_quantity"), ".8", "Invalid new"),
        (("purchases", 0, "delivery", "ingredient_id"), "bad", "Invalid new"),
        (
            ("purchases", 0, "delivery", "ordered_at"),
            "2026-02-15T12:30:00+08:00",
            "Invalid new",
        ),
        (("purchases", 0, "available_at"), "2026-02-18T12:29:00+08:00", "Invalid new"),
        (
            ("receipts", 1, "receipt", "received_at"),
            "2026-02-18T12:00:00+08:00",
            "Invalid receipt",
        ),
        (("counts", 0, "available_at"), "2026-02-16T21:00:00+08:00", "count"),
        (("disposals", 0, "quantity"), "-.1", "greater"),
        (("disposals", 0, "quantity"), "NaN", "finite"),
        (("disposals", 0, "quantity"), ".2", "Disposal exceeds"),
        (("disposals", 0, "pool"), "USABLE", "Disposal exceeds"),
        (("hidden_losses", 0, "quantity"), ".2", "Hidden loss exceeds"),
        (("hidden_losses", 0, "at"), "2026-02-24T07:00:00+08:00", "outside"),
    ],
)
def test_invalid_boundaries(raw, catalogue, path, value, match):
    target = raw
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=match):
        run(raw, catalogue)


def test_missing_zero_manifest_is_not_zero(raw, catalogue):
    del raw["opening_manifest"]["tofu"]
    with pytest.raises(ValueError, match="Complete opening manifest"):
        run(raw, catalogue)


def test_cli_reproduction_and_report_hash():
    command = [
        sys.executable,
        "-m",
        "src.physical_scenario",
        "--scenario",
        str(FIXTURES / "physical_seven_days_v1.json"),
        "--catalogue",
        str(FIXTURES / "seasonal_baseline_v3.json"),
    ]
    first = subprocess.check_output(command)
    assert subprocess.check_output(command) == first
    report = json.loads(first)
    digest = report.pop("report_sha256")
    assert sha256(canonical_json(report)) == digest
    assert report["scenario_file_sha256"] == sha256(
        (FIXTURES / "physical_seven_days_v1.json").read_bytes()
    )
    assert report["totals"] == {
        "attempted": 15,
        "served": 11,
        "unmet": 4,
        "paid": 7,
        "free": 4,
        "revenue": "35.00",
    }

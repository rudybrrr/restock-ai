"""Independent physical accounting oracles; no database or optimiser involved."""

import ast
import copy
import itertools
import json
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.history_dataset import Catalogue
from src.physical_simulator import PhysicalDay, observations_at, simulate_day

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal


def at(clock):
    return datetime.fromisoformat(f"2026-02-16T{clock}:00+08:00")


@pytest.fixture
def catalogue():
    source = json.loads((FIXTURES / "seasonal_baseline_v3.json").read_text())
    return Catalogue.model_validate(
        {k: source[k] for k in ("menu_items", "ingredients", "recipes")}
    )


@pytest.fixture
def raw():
    return json.loads((FIXTURES / "physical_day_v1.json").read_text())


def run(raw, catalogue):
    return simulate_day(PhysicalDay.model_validate(raw), catalogue)


def balances(result):
    return {lot.lot_id: lot for lot in result.lots}


def test_complete_independent_reference(raw, catalogue):
    result = run(raw, catalogue)
    assert [(o.order_id, o.served, o.unmet) for o in result.outcomes] == [
        ("a", 1, 0),
        ("b", 2, 0),
        ("c", 0, 1),
        ("d", 0, 1),
        ("e", 1, 0),
        ("f", 1, 0),
        ("g", 0, 1),
        ("h", 0, 1),
    ]
    lots = balances(result)
    assert (
        lots["chicken-a"].consumed,
        lots["chicken-b"].consumed,
        lots["chicken-arrival"].consumed,
    ) == (D(".300"), D(".150"), D(".150"))
    assert lots["rice-a"].consumed == D(".500")  # 4 chicken rice + 1 fried rice
    assert lots["rice-a"].hidden_loss == D(".250")
    assert lots["rice-a"].closing_usable == D("1.250")
    assert lots["eggs-a"].consumed == 1
    assert lots["vegetables-a"].closing_usable == D(".150")
    assert lots["vegetables-expired"].expired == D(".100")
    assert lots["oil-a"].closing_usable == D(".090")
    assert lots["soy-a"].closing_usable == D(".160")
    for lot in result.lots:
        assert lot.opening + lot.received == (
            lot.consumed + lot.hidden_loss + lot.expired + lot.closing_usable
        )
    for o in result.outcomes:
        assert o.attempted == o.served + o.unmet
        assert o.served == o.paid + o.free
    observed = result.observations
    assert observed.daily_sales is not None
    assert dict(observed.daily_sales.portions) == {
        "chicken-rice": 4,
        "fried-rice": 1,
        "chicken-noodles": 0,
        "tofu-bowl": 0,
        "vegetable-noodles": 0,
    }
    assert observed.daily_sales.censored is True
    assert observed.daily_sales.promotion is True
    sales = {s.menu_item_id: s for s in observed.daily_accounting}
    assert (
        sales["chicken-rice"].paid,
        sales["chicken-rice"].free,
        sales["chicken-rice"].transactions,
        sales["chicken-rice"].revenue,
    ) == (3, 1, 3, D(15))
    assert sum(s.revenue for s in sales.values()) == D(19)
    assert sum(sum(b.batch.sales.values()) for b in observed.batches) == 5
    c = result.commitments[0]
    assert (c.total, c.received, c.cancelled, c.outstanding) == (
        D(".3"),
        D(".15"),
        D(".15"),
        D(0),
    )


def test_fixture_recipes_match_seed_without_database(catalogue):
    # Read only the seed's literal recipe table: no seed execution, SQL or imports.
    tree = ast.parse((Path(__file__).parents[1] / "src/seed.py").read_text())
    assignment = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "recipe_data" for t in n.targets)
    )
    expected = ast.literal_eval(assignment.value)
    assert {
        (r.menu_item_id, r.ingredient_id): r.quantity for r in catalogue.recipes
    } == {
        (dish, ingredient): D(quantity)
        for dish, recipe in expected.items()
        for ingredient, quantity in recipe.items()
    }


def test_promotional_pair_failure_is_atomic(raw, catalogue):
    raw["orders"] = [raw["orders"][1]]
    raw["opening_lots"][0]["quantity"] = "0.100"  # total .25; pair needs .30
    raw["receipts"] = []
    raw["hidden_losses"] = []
    result = run(raw, catalogue)
    o = result.outcomes[0]
    assert (o.attempted, o.served, o.unmet, o.revenue) == (2, 0, 2, D(0))
    assert o.missing_ingredients == ("chicken",)
    assert all(l.consumed == 0 for l in result.lots)  # no other ingredient debited


def test_multiple_missing_ingredients_count_one_unmet_order(raw, catalogue):
    raw["orders"] = [dict(raw["orders"][0], menu_item_id="vegetable-noodles")]
    raw["opening_lots"] = [
        l for l in raw["opening_lots"] if l["ingredient_id"] != "vegetables"
    ]
    raw["opening_manifest"]["vegetables"] = []
    result = run(raw, catalogue)
    assert result.outcomes[0].missing_ingredients == ("noodles", "vegetables")
    assert result.outcomes[0].unmet == 1


@pytest.mark.parametrize(
    "receipt_clock,served,boundary_sales",
    [
        ("11:29", 5, (1, 0)),
        ("11:30", 5, (0, 1)),
        ("11:36", 4, (0, 0)),
    ],
)
def test_arrivals_never_repair_earlier_shortages(
    raw, catalogue, receipt_clock, served, boundary_sales
):
    raw["receipts"][0]["receipt"]["received_at"] = at(receipt_clock)
    raw["receipts"][0]["available_at"] = at("12:00")
    result = run(raw, catalogue)
    assert sum(o.served for o in result.outcomes) == served
    assert (
        tuple(o.served for o in result.outcomes if o.order_id in ("d", "e"))
        == boundary_sales
    )
    assert next(o for o in result.outcomes if o.order_id == "c").unmet == 1


def test_mid_bucket_actual_receipt_splits_observed_coverage(raw, catalogue):
    raw["receipts"][0]["receipt"]["received_at"] = at("11:20")
    raw["receipts"][0]["available_at"] = at("11:25")
    result = run(raw, catalogue)
    batches = result.observations.batches
    assert any(b.batch.period_end == at("11:20") for b in batches)
    assert any(b.batch.period_start == at("11:20") for b in batches)
    for previous, current in itertools.pairwise(batches):
        assert previous.batch.period_end == current.batch.period_start
    # Late-recorded receipt cannot expose its synthetic split early.
    early = observations_at(result.observations, known_at=at("11:24"))
    assert not early.receipts
    assert not any(b.batch.period_end == at("11:20") for b in early.batches)


def test_partial_receipt_opening_six_of_ten_not_double_counted(raw, catalogue):
    raw["orders"] = []
    raw["hidden_losses"] = []
    prior = dict(
        raw["receipts"][0]["receipt"],
        id="prior",
        request_id="prior",
        lot_id="chicken-a",
        quantity="6",
        received_at="2026-02-15T08:00:00+08:00",
        expiry_date="2026-02-16",
        remainder="EXPECTED",
    )
    raw["opening_lots"][0].update(quantity="6", initial_quantity="6")
    raw["commitments"][0].update(
        expected_quantity="10",
        received_quantity="6",
        outstanding_quantity="4",
        receipts=[prior],
        ordered_at="2026-02-14T22:00:00+08:00",
    )
    raw["receipts"][0]["receipt"]["quantity"] = "2"
    result = run(raw, catalogue)
    c = result.commitments[0]
    assert (c.received, c.cancelled, c.outstanding) == (8, 2, 0)
    assert balances(result)["chicken-a"].closing_usable == 6
    assert balances(result)["chicken-arrival"].closing_usable == 2
    assert sum(l.received for l in result.lots) == 2


def test_explicit_cancellation_never_creates_stock(raw, catalogue):
    raw["receipts"] = []
    raw["cancellations"] = [
        {
            "id": "cancel",
            "delivery_id": "external-chicken",
            "at": at("11:00"),
            "available_at": at("12:00"),
            "quantity": "0.300",
        }
    ]
    result = run(raw, catalogue)
    assert result.commitments[0].cancelled == D(".300")
    assert result.commitments[0].outstanding == 0
    assert sum(l.received for l in result.lots) == 0
    assert sum(o.served for o in result.outcomes) == 4


def test_expected_delivery_is_not_actual_stock(raw, catalogue):
    raw["receipts"] = []
    result = run(raw, catalogue)
    assert result.commitments[0].outstanding == D(".3")
    assert sum(l.received for l in result.lots) == 0
    assert next(o for o in result.outcomes if o.order_id == "e").unmet == 1


def test_expiry_next_singapore_midnight_not_disposal(raw, catalogue):
    raw["orders"] = []
    raw["hidden_losses"] = []
    raw["end"] = "2026-02-17T00:00:00+08:00"
    raw["closing_available_at"] = "2026-02-17T00:01:00+08:00"
    result = run(raw, catalogue)
    lot = balances(result)["chicken-a"]
    assert (lot.expired, lot.closing_usable) == (D(".3"), 0)
    closing = {l.id: l for l in result.observations.closing_lots}
    assert closing["chicken-a"].quantity == D(".3")  # physically retained expired stock
    assert any(
        m.lot_id == "chicken-a"
        and m.at == at("00:00").replace(day=17)
        and m.kind == "EXPIRY"
        for m in result.movements
    )


@pytest.mark.parametrize("earlier_receipt", [True, False])
def test_equal_expiry_fefo_received_time_then_actual_lot_id(
    raw, catalogue, earlier_receipt
):
    raw["orders"] = raw["orders"][:1]
    raw["receipts"] = []
    raw["hidden_losses"] = []
    raw["opening_lots"][1]["expiry_date"] = "2026-02-16"
    if earlier_receipt:
        raw["opening_lots"][1]["received_at"] = "2026-02-15T07:00:00+08:00"
    result = run(raw, catalogue)
    expected = "chicken-b" if earlier_receipt else "chicken-a"
    assert balances(result)[expected].consumed == D(".15")
    other = "chicken-a" if earlier_receipt else "chicken-b"
    assert balances(result)[other].consumed == 0


def test_hidden_truth_and_future_facts_are_not_observations(raw, catalogue):
    with_loss = run(raw, catalogue)
    raw["hidden_losses"] = []
    without_loss = run(raw, catalogue)
    before_count = observations_at(with_loss.observations, known_at=at("21:59"))
    assert before_count == observations_at(
        without_loss.observations, known_at=at("21:59")
    )
    assert before_count.daily_sales is None
    assert before_count.daily_accounting == ()
    assert before_count.closing_lots == ()
    before_receipt = observations_at(with_loss.observations, known_at=at("11:31"))
    assert before_receipt.receipts == ()
    assert not (
        {f.name for f in fields(before_count)}
        & {"orders", "outcomes", "hidden_losses", "movements"}
    )
    final = observations_at(with_loss.observations, known_at=at("22:05"))
    closing = {l.id: l for l in final.closing_lots}
    # Recorded recipe consumption explains .5, but actual count is another .25 lower.
    assert closing["rice-a"].quantity == D("1.25")
    assert D(2) - D(".5") - closing["rice-a"].quantity == D(".25")
    assert "HIDDEN_LOSS" not in repr(final)


def test_observed_zero_distinct_from_unavailable_daily_report(raw, catalogue):
    raw["orders"] = []
    result = run(raw, catalogue)
    assert (
        observations_at(result.observations, known_at=at("22:04")).daily_sales is None
    )
    final = observations_at(result.observations, known_at=at("22:05"))
    assert final.daily_sales is not None
    assert set(final.daily_sales.portions.values()) == {0}
    assert final.daily_sales.censored is False
    assert all(len(b.batch.sales) == 5 for b in final.batches)


def test_daily_revision_can_replace_without_batch_double_counting(raw, catalogue):
    daily = run(raw, catalogue).observations.daily_sales
    assert daily is not None
    correction = DailySalesObservation(
        daily.service_date,
        at("23:00"),
        2,
        {dish: 0 for dish in daily.portions},
        False,
        False,
    )
    # Reader/forecaster receives final revisions only. Censored first revision is
    # ineligible; correction is one eligible day, not final+batch consumption.
    forecast = seasonal_baseline(
        [daily, correction],
        catalogue.menu_items,
        issue_time=at("23:01"),
        target_date=daily.service_date.replace(day=17),
    )
    assert all(
        v.eligible_days == 1 and v.expected_portions is None for v in forecast.values()
    )


def test_deterministic_reordered_inputs_low_decimal_context_and_immutability(
    raw, catalogue
):
    inputs = PhysicalDay.model_validate(raw)
    before = inputs.model_dump_json()
    cat_before = catalogue.model_dump_json()
    expected = simulate_day(inputs, catalogue)
    for key in ("orders", "opening_lots", "receipts", "profile"):
        raw[key].reverse()
    with localcontext() as context:
        context.prec = 3
        actual = run(raw, catalogue)
    assert actual == expected
    assert inputs.model_dump_json() == before
    assert catalogue.model_dump_json() == cat_before
    copy_observations = observations_at(expected.observations, known_at=at("23:00"))
    copy_observations.batches[0].batch.sales["chicken-rice"] = 999
    assert expected.observations.batches[0].batch.sales["chicken-rice"] == 0


def test_equal_time_order_ids_resolve_scarce_stock_independent_of_input_order(
    raw, catalogue
):
    raw["orders"] = [
        dict(raw["orders"][0], id=key, at=at("11:10")) for key in ("z", "a", "b", "c")
    ]
    result = run(raw, catalogue)
    assert [(o.order_id, o.served) for o in result.outcomes] == [
        ("a", 1),
        ("b", 1),
        ("c", 1),
        ("z", 0),
    ]


def test_equivalent_utc_times_preserve_identities(raw, catalogue):
    expected = run(raw, catalogue)
    for row in raw["orders"]:
        row["at"] = datetime.fromisoformat(row["at"]).astimezone(UTC)
    assert run(raw, catalogue) == expected


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("catalogue_sha256",), "unknown", "hash mismatch"),
        (("recipe_sha256",), "unknown", "hash mismatch"),
        (("fefo_policy",), "EXPIRY_ID", "literal"),
        (("event_policy",), "unknown", "literal"),
        (("orders", 0, "menu_item_id"), "D1", "Unknown dish"),
        (("orders", 0, "at"), "2026-02-16T11:10:00", "timezone"),
        (("orders", 0, "at"), at("11:00"), "service intervals"),
        (("orders", 0, "at"), at("15:00"), "service intervals"),
        (("orders", 0, "free_portions"), 2, "less than or equal"),
        (("orders", 0, "free_portions"), True, "integer"),
        (("orders", 1, "promotion_reference"), None, "promotion reference"),
        (("orders", 0, "unit_price"), "NaN", "finite"),
        (("orders", 0, "unit_price"), "-1", "greater than or equal"),
        (("orders", 0, "unit_price"), 1.25, "float"),
        (("opening_lots", 0, "unit"), "litres", "Invalid opening"),
        (("opening_lots", 0, "ingredient_id"), "unknown", "manifest"),
        (("opening_lots", 0, "quantity"), "NaN", "finite|Finite"),
        (("opening_lots", 0, "quantity"), "-1", "nonnegative|Invalid opening"),
        (("opening_lots", 0, "quantity"), "99", "Invalid opening"),
        (("opening_lots", 0, "counted_at"), at("09:00"), "Invalid opening"),
        (("opening_lots", 0, "received_at"), at("11:00"), "Invalid opening"),
        (("commitments", 0, "outstanding_quantity"), ".1", "conservation"),
        (("receipts", 0, "receipt", "delivery_id"), "unknown", "unknown external"),
        (("receipts", 0, "receipt", "quantity"), "1", "exceeds outstanding"),
        (("receipts", 0, "receipt", "lot_id"), "chicken-a", "Duplicate physical lot"),
        (("receipts", 0, "receipt", "received_at"), at("10:00"), "receipt time"),
        (("receipts", 0, "receipt", "expiry_date"), "2026-02-15", "expiry"),
        (("receipts", 0, "available_at"), at("11:00"), "recording time"),
        (("hidden_losses", 0, "quantity"), "5", "exceeds available"),
        (("hidden_losses", 0, "lot_id"), "future", "exceeds available"),
        (("hidden_losses", 0, "at"), at("09:00"), "outside"),
        (("closing_available_at",), at("21:00"), "before cutoff"),
        (("end",), at("20:00"), "complete dated"),
        (("profile", 0, "weight"), ".5", "sum exactly"),
    ],
)
def test_invalid_fixtures_rejected(raw, catalogue, path, value, message):
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        run(raw, catalogue)


@pytest.mark.parametrize(
    "key", ["orders", "receipts", "commitments", "hidden_losses", "opening_lots"]
)
def test_duplicates_rejected_without_second_effect(raw, catalogue, key):
    raw[key].append(copy.deepcopy(raw[key][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        run(raw, catalogue)


def test_missing_stock_not_inferred_zero(raw, catalogue):
    del raw["opening_manifest"]["tofu"]
    with pytest.raises(ValueError, match="Complete opening manifest"):
        run(raw, catalogue)


def test_changed_recipe_requires_new_hash(raw, catalogue):
    changed = catalogue.model_copy(deep=True)
    changed.recipes[0].quantity = D(".9")
    with pytest.raises(ValueError, match="hash mismatch"):
        run(raw, changed)


def test_cancellation_before_receipt_prevents_over_receiving(raw, catalogue):
    raw["cancellations"] = [
        {
            "id": "cancel",
            "delivery_id": "external-chicken",
            "at": at("11:00"),
            "available_at": at("11:00"),
            "quantity": ".3",
        }
    ]
    with pytest.raises(ValueError, match="Receipt exceeds"):
        run(raw, catalogue)


def test_future_hidden_loss_of_unreceived_lot_is_invalid(raw, catalogue):
    raw["hidden_losses"] = [
        {"id": "loss", "at": at("11:20"), "lot_id": "chicken-arrival", "quantity": ".1"}
    ]
    with pytest.raises(ValueError, match="exceeds available"):
        run(raw, catalogue)


def test_complete_catalogue_reference_320_portions(raw, catalogue):
    raw["opening_lots"] = [
        {
            "id": i.id,
            "ingredient_id": i.id,
            "unit": i.unit,
            "received_at": "2026-02-15T08:00:00+08:00",
            "counted_at": at("10:00"),
            "expiry_date": "2026-02-20",
            "initial_quantity": "1000",
            "quantity": "1000",
        }
        for i in catalogue.ingredients
    ]
    raw["opening_manifest"] = {i.id: [i.id] for i in catalogue.ingredients}
    raw["commitments"] = []
    raw["receipts"] = []
    raw["hidden_losses"] = []
    quantities = {
        "chicken-rice": 100,
        "fried-rice": 60,
        "chicken-noodles": 80,
        "tofu-bowl": 40,
        "vegetable-noodles": 40,
    }
    raw["orders"] = [
        {
            "id": f"{dish}-{n}",
            "at": at("12:00"),
            "menu_item_id": dish,
            "free_portions": 0,
            "unit_price": "1.00",
            "promotion_reference": None,
        }
        for dish, q in quantities.items()
        for n in range(q)
    ]
    result = run(raw, catalogue)
    expected = {
        "chicken": "24.600",
        "rice": "20.000",
        "noodles": "18.000",
        "eggs": "60",
        "tofu": "6.000",
        "vegetables": "11.800",
        "oil": "1.000",
        "soy-sauce": "1.800",
    }
    assert {l.ingredient_id: l.consumed for l in result.lots} == {
        k: D(v) for k, v in expected.items()
    }
    assert sum(o.served for o in result.outcomes) == 320
    assert sum(o.unmet for o in result.outcomes) == 0
    assert result.observations.daily_sales is not None
    assert result.observations.daily_sales.censored is False


def test_fractional_recipe_quantity_exact_without_rounding(raw, catalogue):
    raw["orders"] = [dict(raw["orders"][0], menu_item_id="chicken-noodles")]
    raw["receipts"] = []
    raw["hidden_losses"] = []
    raw["opening_lots"].append(
        {
            "id": "noodles",
            "ingredient_id": "noodles",
            "unit": "kg",
            "quantity": "0.150",
            "initial_quantity": "0.150",
            "received_at": "2026-02-15T08:00:00+08:00",
            "counted_at": at("10:00"),
            "expiry_date": "2026-02-18",
        }
    )
    raw["opening_manifest"]["noodles"] = ["noodles"]
    result = run(raw, catalogue)
    assert balances(result)["chicken-a"].consumed == D(".120")
    assert balances(result)["noodles"].closing_usable == 0


def test_cancelled_before_opening_and_partial_receipts_reconcile(raw, catalogue):
    raw["commitments"][0].update(cancelled_quantity=".100", outstanding_quantity=".200")
    result = run(raw, catalogue)
    assert result.commitments[0].received == D(".150")
    assert result.commitments[0].cancelled == D(".150")
    assert result.commitments[0].outstanding == 0


def test_cancellation_larger_than_remaining_rejected(raw, catalogue):
    raw["cancellations"] = [
        {
            "id": "cancel",
            "delivery_id": "external-chicken",
            "at": at("12:00"),
            "available_at": at("12:00"),
            "quantity": ".001",
        }
    ]
    with pytest.raises(ValueError, match="Cancellation exceeds"):
        run(raw, catalogue)


def test_past_stockout_not_erased_by_big_late_receipt(raw, catalogue):
    raw["commitments"][0].update(expected_quantity="10", outstanding_quantity="10")
    raw["receipts"][0]["receipt"].update(quantity="10", received_at=at("18:00"))
    raw["receipts"][0]["available_at"] = at("18:01")
    result = run(raw, catalogue)
    assert [(o.order_id, o.unmet) for o in result.outcomes if o.unmet] == [
        ("c", 1),
        ("d", 1),
        ("e", 1),
        ("g", 1),
        ("h", 1),
    ]
    assert balances(result)["chicken-arrival"].closing_usable == 10


def test_reject_naive_observation_cutoff(raw, catalogue):
    with pytest.raises(ValueError, match="timezone-aware"):
        observations_at(
            run(raw, catalogue).observations, known_at=at("10:00").replace(tzinfo=None)
        )


def test_explicit_zero_manifests_survive_observation_boundary(raw, catalogue):
    raw["opening_lots"] = []
    raw["opening_manifest"] = {i.id: [] for i in catalogue.ingredients}
    raw["hidden_losses"] = []
    raw["receipts"] = []
    result = run(raw, catalogue)
    assert (
        observations_at(result.observations, known_at=at("09:59")).opening_manifest
        == ()
    )
    visible = observations_at(result.observations, known_at=at("10:00"))
    assert len(visible.opening_manifest) == 8
    assert all(not ids for _, ids in visible.opening_manifest)
    assert not visible.closing_manifest
    final = observations_at(result.observations, known_at=at("22:05"))
    assert len(final.closing_manifest) == 8
    assert sum(o.served for o in result.outcomes) == 0
    assert sum(o.unmet for o in result.outcomes) == 9


@pytest.mark.parametrize(
    "path",
    [
        ("commitments", 0, "id"),
        ("receipts", 0, "receipt", "id"),
        ("receipts", 0, "receipt", "request_id"),
    ],
)
def test_blank_source_identities_rejected(raw, catalogue, path):
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = " "
    with pytest.raises(ValueError, match="Nonempty"):
        run(raw, catalogue)


def test_inconsistent_cancelled_opening_receipt_rejected(raw, catalogue):
    prior = dict(
        raw["receipts"][0]["receipt"],
        id="prior",
        request_id="prior",
        lot_id="chicken-a",
        quantity=".300",
        received_at="2026-02-15T08:00:00+08:00",
        expiry_date="2026-02-16",
        remainder="CANCELLED",
    )
    raw["commitments"][0].update(
        expected_quantity=".600",
        received_quantity=".300",
        outstanding_quantity=".300",
        receipts=[prior],
        ordered_at="2026-02-14T22:00:00+08:00",
    )
    with pytest.raises(ValueError, match="Cancelled opening remainder"):
        run(raw, catalogue)


def test_receipt_retry_identity_is_a_pair_not_delimited_text(raw, catalogue):
    # Distinct (delivery, request) pairs must not collide on embedded colons.
    raw["orders"] = []
    raw["hidden_losses"] = []
    first = raw["commitments"][0]
    first["id"] = "external:chicken"
    second = dict(first, id="external")
    raw["commitments"] = [first, second]
    receipt = raw["receipts"][0]
    receipt["receipt"].update(delivery_id=first["id"], request_id="one")
    another = copy.deepcopy(receipt)
    another["receipt"].update(
        id="another",
        lot_id="another-lot",
        delivery_id=second["id"],
        request_id="chicken:one",
    )
    raw["receipts"].append(another)
    result = run(raw, catalogue)
    assert sum(l.received for l in result.lots) == D(".300")
    assert all(c.received == D(".150") for c in result.commitments)


def test_same_receipt_request_on_same_delivery_is_rejected(raw, catalogue):
    another = copy.deepcopy(raw["receipts"][0])
    another["receipt"].update(id="another", lot_id="another-lot")
    raw["receipts"].append(another)
    with pytest.raises(ValueError, match="Duplicate receipt retry"):
        run(raw, catalogue)

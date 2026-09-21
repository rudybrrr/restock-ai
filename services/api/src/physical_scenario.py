"""Continuous offline physical execution, with a separate observation-only seam.

Explicit fixtures drive events, not approvals or procurement decisions. A scenario
is one continuous state machine; calendar boundaries neither reset stock nor emit
stocktakes. The supported fixture scope is one to seven Singapore calendar days.
"""

import argparse
import copy
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from src.forecasting import SINGAPORE, DailySalesObservation
from src.history_dataset import Catalogue, DatasetModel, canonical_json, sha256
from src.inventory_projection import _precision
from src.operations_schemas import Delivery, SalesBatch
from src.physical_simulator import (
    ZERO,
    Cancellation,
    CommitmentBalance,
    Identity,
    Movement,
    ObservedBatch,
    ObservedDishSales,
    PhysicalInputs,
    PositiveQuantity,
    RealisedReceipt,
    SaleOutcome,
    _physical_quantities,
    _PhysicalState,
    _unique,
    _validate_events,
)
from src.schemas import InventoryLot
from src.service_buckets import ServicePeriod, allocate_service_buckets

VERSION = "PHYSICAL_SCENARIO_V1"


class ScenarioDay(DatasetModel):
    target_date: date
    profile: tuple[ServicePeriod, ...]
    batch_reporting_delay_seconds: Annotated[int, Field(ge=0, strict=True)]
    daily_available_at: AwareDatetime


class CountSchedule(DatasetModel):
    id: Identity
    at: AwareDatetime
    available_at: AwareDatetime


class ExternalPurchase(DatasetModel):
    """An explicitly supplied external action, never a simulator recommendation."""

    delivery: Delivery
    available_at: AwareDatetime


class Disposal(DatasetModel):
    id: Identity
    at: AwareDatetime
    available_at: AwareDatetime
    lot_id: Identity
    quantity: PositiveQuantity
    pool: Literal["USABLE", "EXPIRED"]


class PhysicalScenario(PhysicalInputs):
    scenario_version: Literal["PHYSICAL_SCENARIO_V1"]
    timezone: Literal["Asia/Singapore"]
    scenario_event_policy: Literal[
        "EXPIRY_PLACEMENT_LOSS_SALE_RECEIPT_CANCEL_DISPOSAL_COUNT_V1"
    ]
    days: Annotated[tuple[ScenarioDay, ...], Field(min_length=1, max_length=7)]
    opening_available_at: AwareDatetime
    purchases: tuple[ExternalPurchase, ...]
    counts: tuple[CountSchedule, ...]
    disposals: tuple[Disposal, ...]


@dataclass(frozen=True)
class PhysicalBalance:
    """Evaluator state, deliberately not an InventoryLot count observation."""

    lot_id: str
    ingredient_id: str
    unit: str
    received_at: datetime
    expiry_date: date
    usable: Decimal
    retained_expired: Decimal


@dataclass(frozen=True)
class ScenarioLedger:
    identity: str
    ingredient_id: str
    unit: str
    opening: Decimal
    opening_expired: Decimal
    received: Decimal
    consumed: Decimal
    hidden_loss: Decimal
    newly_expired: Decimal
    disposed: Decimal
    closing_usable: Decimal
    closing_expired: Decimal


@dataclass(frozen=True)
class SalesTotals:
    attempted: int
    served: int
    unmet: int
    paid: int
    free: int
    revenue: Decimal


@dataclass(frozen=True)
class DailyResult:
    target_date: date
    opening: tuple[PhysicalBalance, ...]
    closing: tuple[PhysicalBalance, ...]
    sales: SalesTotals


@dataclass(frozen=True)
class CountObservation:
    id: str
    at: datetime
    available_at: datetime
    lots: tuple[InventoryLot, ...]
    manifest: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class DailyObservation:
    sales: DailySalesObservation
    accounting: tuple[ObservedDishSales, ...]


@dataclass(frozen=True)
class ScenarioObservations:
    """Published facts only. No schedule, future attempts or hidden loss truth."""

    counts: tuple[CountObservation, ...]
    opening_commitments: tuple[ExternalPurchase, ...]
    batches: tuple[ObservedBatch, ...]
    daily: tuple[DailyObservation, ...]
    receipts: tuple[RealisedReceipt, ...]
    cancellations: tuple[Cancellation, ...]
    purchases: tuple[ExternalPurchase, ...]
    disposals: tuple[Disposal, ...]


@dataclass(frozen=True)
class ScenarioResult:
    version: str
    catalogue_sha256: str
    recipe_sha256: str
    days: tuple[DailyResult, ...]
    totals: SalesTotals
    lots: tuple[ScenarioLedger, ...]
    ingredients: tuple[ScenarioLedger, ...]
    commitments: tuple[CommitmentBalance, ...]
    outcomes: tuple[SaleOutcome, ...]
    movements: tuple[Movement, ...]
    observations: ScenarioObservations


def _validate(data: PhysicalScenario, catalogue: Catalogue) -> None:
    if (data.catalogue_sha256, data.recipe_sha256) != (
        catalogue.catalogue_hash,
        catalogue.recipe_hash,
    ):
        raise ValueError("Catalogue/recipe hash mismatch")
    start = datetime.combine(data.days[0].target_date, time.min, SINGAPORE)
    if data.start != start or data.end != start + timedelta(days=len(data.days)):
        raise ValueError("Require consecutive complete Singapore calendar days")
    if data.opening_available_at < data.start:
        raise ValueError("Opening count cannot be available before its cutoff")
    buckets = []
    for index, day in enumerate(data.days):
        if day.target_date != start.date() + timedelta(days=index):
            raise ValueError("Days must be ordered, consecutive and complete")
        service = allocate_service_buckets(
            {d.id: ZERO for d in catalogue.menu_items},
            catalogue.menu_items,
            target_date=day.target_date,
            profile=day.profile,
        )
        if day.daily_available_at < max(b.end for b in service):
            raise ValueError("Daily total cannot be available before service ends")
        buckets.extend(service)
    new_deliveries = tuple(p.delivery for p in data.purchases)
    _validate_events(data, catalogue, tuple(buckets), new_deliveries)
    ingredients = {i.id for i in catalogue.ingredients}
    for purchase in data.purchases:
        d = purchase.delivery
        if (
            d.ingredient_id not in ingredients
            or not data.start < d.ordered_at <= data.end
            or purchase.available_at < d.ordered_at
            or d.expected_at < d.ordered_at
            or d.receipts
            or d.received_quantity
            or d.cancelled_quantity
            or d.expected_quantity != d.outstanding_quantity
        ):
            raise ValueError("Invalid new external commitment or placement evidence")
    for label, events in (("count", data.counts), ("disposal", data.disposals)):
        _unique([e.id for e in events], label)
        for event in events:
            if not data.start < event.at <= data.end or event.available_at < event.at:
                raise ValueError(f"Invalid {label} effective/availability time")
    if any(e.id == f"{data.fixture_id}:opening" for e in data.counts):
        raise ValueError("Count identity conflicts with the opening observation")


def _snapshot(state: _PhysicalState) -> tuple[PhysicalBalance, ...]:
    return tuple(
        PhysicalBalance(
            key,
            lot.ingredient_id,
            lot.unit,
            lot.received_at,
            lot.expiry_date,
            state.stock[key],
            state.retained[key],
        )
        for key, lot in sorted(state.metadata.items())
    )


def _count(
    state: _PhysicalState, identity: str, at: datetime, available: datetime
) -> CountObservation:
    lots = state.count(at)
    return CountObservation(
        identity,
        at,
        available,
        lots,
        tuple(
            (i, tuple(l.id for l in lots if l.ingredient_id == i))
            for i in sorted(state.units)
        ),
    )


def _totals(outcomes: tuple[SaleOutcome, ...]) -> SalesTotals:
    return SalesTotals(
        sum(o.attempted for o in outcomes),
        sum(o.served for o in outcomes),
        sum(o.unmet for o in outcomes),
        sum(o.paid for o in outcomes),
        sum(o.free for o in outcomes),
        sum((o.revenue for o in outcomes), ZERO),
    )


def simulate_scenario(inputs: PhysicalScenario, catalogue: Catalogue) -> ScenarioResult:
    """Execute one continuous timeline without input mutation or ambient rounding.

    Expiry precedes placement, hidden loss, sale, receipt, cancellation, disposal,
    count, then midnight snapshot. IDs order events within each kind. Sales at an
    interval end precede equal-time receipts. Invalid fixtures raise ValueError.
    """
    data = PhysicalScenario.model_validate(inputs.model_dump())
    catalogue = Catalogue.model_validate(catalogue.model_dump())
    values = _physical_quantities(data, catalogue)
    values += [e.quantity for e in data.disposals]
    values += [
        q
        for p in data.purchases
        for q in (
            p.delivery.expected_quantity,
            p.delivery.received_quantity,
            p.delivery.cancelled_quantity,
            p.delivery.outstanding_quantity,
        )
    ]
    if any(not v.is_finite() or v < 0 for v in values):
        raise ValueError("Finite nonnegative Decimal quantities required")
    events = (
        len(data.orders)
        + len(data.receipts)
        + len(data.hidden_losses)
        + len(data.disposals)
    )
    with localcontext(Context(prec=_precision(values) + len(str(events + 1)) + 3)):
        _validate(data, catalogue)
        return _execute(data, catalogue)


def _execute(data: PhysicalScenario, catalogue: Catalogue) -> ScenarioResult:
    state = _PhysicalState(data, catalogue)
    state.expire(data.start, opening=True)
    snapshots = {data.start: _snapshot(state)}
    counts = [
        _count(
            state, f"{data.fixture_id}:opening", data.start, data.opening_available_at
        )
    ]
    purchases = {p.delivery.id: p for p in data.purchases}
    losses = {e.id: e for e in data.hidden_losses}
    orders = {o.id: o for o in data.orders}
    receipts = {r.receipt.id: r for r in data.receipts}
    cancellations = {e.id: e for e in data.cancellations}
    disposals = {e.id: e for e in data.disposals}
    count_events = {e.id: e for e in data.counts}
    timeline = [(p.delivery.ordered_at, 1, p.delivery.id) for p in data.purchases]
    timeline += [(e.at, 2, e.id) for e in data.hidden_losses]
    timeline += [(e.at, 3, e.id) for e in data.orders]
    timeline += [(r.receipt.received_at, 4, r.receipt.id) for r in data.receipts]
    timeline += [(e.at, 5, e.id) for e in data.cancellations]
    timeline += [(e.at, 6, e.id) for e in data.disposals]
    timeline += [(e.at, 7, e.id) for e in data.counts]
    timeline += [
        (data.start + timedelta(days=i + 1), 8, "") for i in range(len(data.days))
    ]
    # All expiry boundaries are midnight, already present in the calendar timeline.
    for at, kind, identity in sorted(timeline):
        state.expire(at)
        if kind == 1:
            state.place(purchases[identity].delivery)
        elif kind == 2:
            state.lose(losses[identity])
        elif kind == 3:
            state.serve(orders[identity])
        elif kind == 4:
            state.receive(receipts[identity].receipt)
        elif kind == 5:
            state.cancel(cancellations[identity])
        elif kind == 6:
            e = disposals[identity]
            state.dispose(e.id, e.at, e.lot_id, e.quantity, expired=e.pool == "EXPIRED")
        elif kind == 7:
            e = count_events[identity]
            counts.append(_count(state, e.id, e.at, e.available_at))
        else:
            snapshots[at] = _snapshot(state)

    daily_results = []
    daily_observations = []
    batches = []
    for day in data.days:
        start = datetime.combine(day.target_date, time.min, SINGAPORE)
        end = start + timedelta(days=1)
        outcomes = tuple(o for o in state.outcomes if start < o.at <= end)
        daily_results.append(
            DailyResult(
                day.target_date, snapshots[start], snapshots[end], _totals(outcomes)
            )
        )
        daily_observations.append(
            DailyObservation(
                DailySalesObservation(
                    day.target_date,
                    day.daily_available_at,
                    1,
                    {
                        d: sum(o.served for o in outcomes if o.menu_item_id == d)
                        for d in state.dish_ids
                    },
                    any(o.free_portions for o in data.orders if start < o.at <= end),
                    any(o.unmet for o in outcomes),
                ),
                tuple(
                    ObservedDishSales(
                        d,
                        sum(o.served for o in outcomes if o.menu_item_id == d),
                        sum(o.paid for o in outcomes if o.menu_item_id == d),
                        sum(o.free for o in outcomes if o.menu_item_id == d),
                        sum(o.paid for o in outcomes if o.menu_item_id == d),
                        sum((o.revenue for o in outcomes if o.menu_item_id == d), ZERO),
                    )
                    for d in state.dish_ids
                ),
            )
        )
        service = allocate_service_buckets(
            {d: ZERO for d in state.dish_ids},
            catalogue.menu_items,
            target_date=day.target_date,
            profile=day.profile,
        )
        # Split only on observable physical boundaries, never hidden losses.
        public_boundaries = [
            (r.receipt.received_at, r.available_at) for r in data.receipts
        ]
        public_boundaries += [(e.at, e.available_at) for e in data.counts]
        public_boundaries += [(e.at, e.available_at) for e in data.disposals]
        boundaries = {start, end} | {t for b in service for t in (b.start, b.end)}
        boundaries.update(t for t, _ in public_boundaries if start < t < end)
        for left, right in pairwise(sorted(boundaries)):
            identity = f"{left.astimezone(SINGAPORE).isoformat()}/{right.astimezone(SINGAPORE).isoformat()}"
            available = max(
                [right + timedelta(seconds=day.batch_reporting_delay_seconds)]
                + [a for t, a in public_boundaries if t in (left, right)]
            )
            batches.append(
                ObservedBatch(
                    SalesBatch(
                        id=f"{data.fixture_id}:{identity}:1",
                        source=data.fixture_id,
                        batch_id=identity,
                        period_start=left,
                        period_end=right,
                        sales={
                            d: sum(
                                o.served
                                for o in outcomes
                                if o.menu_item_id == d and left < o.at <= right
                            )
                            for d in state.dish_ids
                        },
                        revision=1,
                        active=True,
                    ),
                    available,
                )
            )

    lots = tuple(
        ScenarioLedger(
            k,
            state.metadata[k].ingredient_id,
            state.metadata[k].unit,
            state.ledger[k][0],
            state.opening_expired[k],
            state.ledger[k][1],
            state.ledger[k][2],
            state.ledger[k][3],
            state.ledger[k][4],
            state.disposed[k],
            state.stock[k],
            state.retained[k],
        )
        for k in sorted(state.metadata)
    )
    ingredients = tuple(
        ScenarioLedger(
            ingredient,
            ingredient,
            unit,
            *(
                sum(
                    (getattr(l, field) for l in lots if l.ingredient_id == ingredient),
                    ZERO,
                )
                for field in (
                    "opening",
                    "opening_expired",
                    "received",
                    "consumed",
                    "hidden_loss",
                    "newly_expired",
                    "disposed",
                    "closing_usable",
                    "closing_expired",
                )
            ),
        )
        for ingredient, unit in sorted(state.units.items())
    )
    observations = ScenarioObservations(
        tuple(counts),
        tuple(
            ExternalPurchase(delivery=d, available_at=data.opening_available_at)
            for d in sorted(data.commitments, key=lambda d: d.id)
        ),
        tuple(batches),
        tuple(daily_observations),
        tuple(
            sorted(data.receipts, key=lambda r: (r.receipt.received_at, r.receipt.id))
        ),
        tuple(sorted(data.cancellations, key=lambda e: (e.at, e.id))),
        tuple(
            sorted(data.purchases, key=lambda p: (p.delivery.ordered_at, p.delivery.id))
        ),
        tuple(sorted(data.disposals, key=lambda e: (e.at, e.id))),
    )
    return ScenarioResult(
        VERSION,
        catalogue.catalogue_hash,
        catalogue.recipe_hash,
        tuple(daily_results),
        _totals(tuple(state.outcomes)),
        lots,
        ingredients,
        tuple(
            CommitmentBalance(
                k,
                d.expected_quantity,
                state.received[k],
                state.cancelled[k],
                state.remaining[k],
            )
            for k, d in sorted(state.deliveries.items())
        ),
        tuple(state.outcomes),
        tuple(
            sorted(state.movements, key=lambda m: (m.at, m.kind, m.source_id, m.lot_id))
        ),
        observations,
    )


def scenario_observations_at(
    observations: ScenarioObservations, *, known_at: datetime
) -> ScenarioObservations:
    """Availability-filtered defensive copy; accepts no evaluator state.

    Daily revision 1 totals replace batches in forecasting; they never add to
    physical consumption. No explanation of count discrepancies is disclosed.
    """
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("Knowledge time must be timezone-aware")
    # DailySalesObservation contains a mappingproxy, so reconstruct its vector.
    daily = tuple(
        DailyObservation(
            DailySalesObservation(
                d.sales.service_date,
                d.sales.available_at,
                d.sales.revision,
                dict(d.sales.portions),
                d.sales.promotion,
                d.sales.censored,
            ),
            d.accounting,
        )
        for d in observations.daily
        if d.sales.available_at <= known_at
    )
    return ScenarioObservations(
        copy.deepcopy(
            tuple(e for e in observations.counts if e.available_at <= known_at)
        ),
        copy.deepcopy(
            tuple(
                e
                for e in observations.opening_commitments
                if e.available_at <= known_at
            )
        ),
        copy.deepcopy(
            tuple(e for e in observations.batches if e.available_at <= known_at)
        ),
        daily,
        copy.deepcopy(
            tuple(e for e in observations.receipts if e.available_at <= known_at)
        ),
        copy.deepcopy(
            tuple(e for e in observations.cancellations if e.available_at <= known_at)
        ),
        copy.deepcopy(
            tuple(e for e in observations.purchases if e.available_at <= known_at)
        ),
        copy.deepcopy(
            tuple(e for e in observations.disposals if e.available_at <= known_at)
        ),
    )


def compact_report(data: PhysicalScenario, result: ScenarioResult) -> dict[str, object]:
    """Evaluator report, not an agent snapshot or an operating-cost score."""
    return {
        "version": result.version,
        "fixture_id": data.fixture_id,
        "timezone": data.timezone,
        "start": data.start.isoformat(),
        "end": data.end.isoformat(),
        "catalogue_sha256": result.catalogue_sha256,
        "recipe_sha256": result.recipe_sha256,
        "fefo_policy": data.fefo_policy,
        "event_policy": data.scenario_event_policy,
        "totals": asdict(result.totals),
        "daily": [
            {"date": d.target_date.isoformat(), **asdict(d.sales)} for d in result.days
        ],
        "ingredients": [asdict(l) for l in result.ingredients],
        "commitments": [asdict(c) for c in result.commitments],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument(
        "--catalogue",
        type=Path,
        required=True,
        help="Catalogue or existing seasonal fixture JSON",
    )
    args = parser.parse_args()
    source = json.loads(args.catalogue.read_text(encoding="utf-8"))
    catalogue = Catalogue.model_validate(
        {k: source[k] for k in ("menu_items", "ingredients", "recipes")}
    )
    data = PhysicalScenario.model_validate_json(args.scenario.read_bytes())
    report = compact_report(data, simulate_scenario(data, catalogue))
    # Decimal strings are lossless; hashes have no wall-clock run timestamp.
    report = json.loads(json.dumps(report, default=str))
    report["scenario_file_sha256"] = sha256(args.scenario.read_bytes())
    report["report_sha256"] = sha256(canonical_json(report))
    print(canonical_json(report).decode(), end="")


if __name__ == "__main__":
    main()

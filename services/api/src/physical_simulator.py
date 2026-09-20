"""Pure, one-day physical fixture execution; NOT an observed-history replayer.

The caller supplies evaluator-only attempted orders and realised events. Outputs
separate observable records from evaluator truth; no database, agent or optimiser
is invoked. Policy comparisons must use independent calls with identical attempts.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from src.forecasting import SINGAPORE, DailySalesObservation
from src.history_dataset import Catalogue, DatasetModel
from src.inventory_projection import FEFO_POLICY, _expiry, _precision
from src.operations_schemas import Delivery, Receipt, SalesBatch
from src.requirements import calculate_requirements
from src.schemas import InventoryLot
from src.service_buckets import ServicePeriod, allocate_service_buckets

Quantity = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Identity = Annotated[str, Field(min_length=1, pattern=r"\S")]
ZERO = Decimal(0)
VERSION = "PHYSICAL_DAY_V1"


class AttemptedOrder(DatasetModel):
    id: Identity
    at: AwareDatetime
    menu_item_id: Identity
    # One ordinary portion, or one atomic buy-one-get-one transaction.
    free_portions: Annotated[int, Field(ge=0, le=1, strict=True)]
    unit_price: Quantity
    promotion_reference: str | None


class RealisedReceipt(DatasetModel):
    receipt: Receipt
    available_at: AwareDatetime


class Cancellation(DatasetModel):
    id: Identity
    delivery_id: Identity
    at: AwareDatetime
    available_at: AwareDatetime
    quantity: PositiveQuantity


class HiddenLoss(DatasetModel):
    id: Identity
    at: AwareDatetime
    lot_id: Identity
    quantity: PositiveQuantity


class PhysicalDay(DatasetModel):
    """Offline numerical fixture, not a proposed Backend request payload.

    Opening lots are complete true/count-equal physical stock at start. Opening
    deliveries contain only already observed commitments/receipts. Future actual
    receipts, cancellations and losses are evaluator inputs, never forecast input.
    """

    fixture_id: Identity
    target_date: date
    start: AwareDatetime
    end: AwareDatetime
    catalogue_sha256: Identity
    recipe_sha256: Identity
    fefo_policy: Literal["FEFO_EXPIRY_RECEIVED_LOT_ID_V1"]
    event_policy: Literal["EXPIRY_LOSS_SALE_RECEIPT_CANCEL_V1"]
    profile: tuple[ServicePeriod, ...]
    opening_lots: tuple[InventoryLot, ...]
    opening_manifest: dict[str, tuple[str, ...]]
    commitments: tuple[Delivery, ...]
    receipts: tuple[RealisedReceipt, ...]
    cancellations: tuple[Cancellation, ...]
    hidden_losses: tuple[HiddenLoss, ...]
    orders: tuple[AttemptedOrder, ...]
    batch_reporting_delay_seconds: Annotated[int, Field(ge=0, strict=True)]
    closing_available_at: AwareDatetime


@dataclass(frozen=True)
class SaleOutcome:
    order_id: str
    at: datetime
    menu_item_id: str
    attempted: int
    served: int
    paid: int
    free: int
    revenue: Decimal
    unmet: int
    missing_ingredients: tuple[str, ...]


@dataclass(frozen=True)
class LotLedger:
    lot_id: str
    ingredient_id: str
    unit: str
    opening: Decimal
    received: Decimal
    consumed: Decimal
    hidden_loss: Decimal
    expired: Decimal
    closing_usable: Decimal


@dataclass(frozen=True)
class Movement:
    at: datetime
    lot_id: str
    kind: Literal["RECEIPT", "CONSUMPTION", "HIDDEN_LOSS", "EXPIRY"]
    quantity: Decimal
    source_id: str


@dataclass(frozen=True)
class CommitmentBalance:
    delivery_id: str
    total: Decimal
    received: Decimal
    cancelled: Decimal
    outstanding: Decimal


@dataclass(frozen=True)
class ObservedBatch:
    batch: SalesBatch
    available_at: datetime


@dataclass(frozen=True)
class ObservedDishSales:
    menu_item_id: str
    served: int
    paid: int
    free: int
    transactions: int
    revenue: Decimal


@dataclass(frozen=True)
class Observations:
    """Only published facts. No attempted demand, losses or future outcomes."""

    opening_at: datetime
    opening_lots: tuple[InventoryLot, ...]
    opening_manifest: tuple[tuple[str, tuple[str, ...]], ...]
    batches: tuple[ObservedBatch, ...]
    receipts: tuple[RealisedReceipt, ...]
    cancellations: tuple[Cancellation, ...]
    daily_sales: DailySalesObservation | None
    daily_accounting: tuple[ObservedDishSales, ...]
    closing_lots: tuple[InventoryLot, ...]
    closing_manifest: tuple[tuple[str, tuple[str, ...]], ...]
    closing_available_at: datetime


@dataclass(frozen=True)
class PhysicalResult:
    version: str
    catalogue_sha256: str
    recipe_sha256: str
    observations: Observations
    # Evaluator-only fields: never serialize this whole object to an agent.
    outcomes: tuple[SaleOutcome, ...]
    lots: tuple[LotLedger, ...]
    movements: tuple[Movement, ...]
    commitments: tuple[CommitmentBalance, ...]


def _unique(values: list[str], label: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"Nonempty {label} identities required")
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}; deduplicate retries before execution")


def _validate(
    inputs: PhysicalDay, catalogue: Catalogue
) -> tuple[tuple[datetime, datetime], ...]:
    if (
        inputs.catalogue_sha256 != catalogue.catalogue_hash
        or inputs.recipe_sha256 != catalogue.recipe_hash
    ):
        raise ValueError("Catalogue/recipe hash mismatch")
    day_start = datetime.combine(inputs.target_date, time.min, SINGAPORE)
    if not day_start <= inputs.start < inputs.end <= day_start + timedelta(days=1):
        raise ValueError("Require one dated Singapore day with positive coverage")
    if inputs.closing_available_at < inputs.end:
        raise ValueError("Closing observations cannot be available before cutoff")
    buckets = allocate_service_buckets(
        {d.id: ZERO for d in catalogue.menu_items},
        catalogue.menu_items,
        target_date=inputs.target_date,
        profile=inputs.profile,
    )
    if any(b.start < inputs.start or b.end > inputs.end for b in buckets):
        raise ValueError("Physical day must cover the complete dated service profile")
    units: dict[str, Literal["kg", "litres", "pieces"]] = {
        i.id: i.unit for i in catalogue.ingredients
    }
    if set(inputs.opening_manifest) != set(units):
        raise ValueError("Complete opening manifest required; [] explicitly means zero")
    _unique([lot.id for lot in inputs.opening_lots], "opening lot")
    for ingredient, expected in inputs.opening_manifest.items():
        _unique(list(expected), "opening manifest lot")
        if set(expected) != {
            lot.id for lot in inputs.opening_lots if lot.ingredient_id == ingredient
        }:
            raise ValueError("Opening manifest differs from supplied physical lots")
    for lot in inputs.opening_lots:
        if (
            lot.ingredient_id not in units
            or lot.unit != units[lot.ingredient_id]
            or lot.counted_at != inputs.start
            or lot.received_at > inputs.start
            or lot.provenance != "PHYSICAL"
            or any(
                not q.is_finite() or q < 0 for q in (lot.quantity, lot.initial_quantity)
            )
            or lot.quantity > lot.initial_quantity
            or lot.expiry_date < lot.received_at.astimezone(SINGAPORE).date()
        ):
            raise ValueError(
                "Invalid opening physical lot, unit, count cutoff or quantity"
            )
        _expiry(lot.expiry_date)
    _unique([o.id for o in inputs.orders], "attempted order")
    for order in inputs.orders:
        if order.menu_item_id not in {d.id for d in catalogue.menu_items}:
            raise ValueError("Unknown dish in attempted order")
        if not any(b.start < order.at <= b.end for b in buckets):
            raise ValueError("Attempted order outside (start, end] service intervals")
        if (order.free_portions == 1) != bool(order.promotion_reference):
            raise ValueError(
                "Atomic promotional pair requires explicit promotion reference"
            )
        if (
            order.promotion_reference is not None
            and not order.promotion_reference.strip()
        ):
            raise ValueError("Nonempty promotion reference required")
    _unique([d.id for d in inputs.commitments], "delivery")
    opening = {lot.id: lot for lot in inputs.opening_lots}
    old_receipts: list[Receipt] = []
    for delivery in inputs.commitments:
        if (
            delivery.ingredient_id not in units
            or delivery.ordered_at > inputs.start
            or delivery.expected_at < delivery.ordered_at
        ):
            raise ValueError(
                "Opening commitment has unknown ingredient or future placement"
            )
        if delivery.expected_quantity != (
            delivery.received_quantity
            + delivery.cancelled_quantity
            + delivery.outstanding_quantity
        ):
            raise ValueError("Commitment quantity conservation failure")
        if (
            sum((r.quantity for r in delivery.receipts), ZERO)
            != delivery.received_quantity
        ):
            raise ValueError(
                "Opening received quantity lacks complete receipt evidence"
            )
        closed = False
        for receipt in sorted(delivery.receipts, key=lambda r: (r.received_at, r.id)):
            if closed:
                raise ValueError("Opening receipt follows a cancelled remainder")
            lot = opening.get(receipt.lot_id)
            if (
                receipt.delivery_id != delivery.id
                or lot is None
                or lot.ingredient_id != delivery.ingredient_id
                or receipt.received_at > inputs.start
                or receipt.received_at < delivery.ordered_at
                or lot.initial_quantity != receipt.quantity
                or lot.received_at != receipt.received_at
                or lot.expiry_date != receipt.expiry_date
                or receipt.closing_counts
            ):
                raise ValueError(
                    "Previously received stock must be represented once in opening"
                )
            old_receipts.append(receipt)
            closed = receipt.remainder == "CANCELLED"
        if closed and delivery.outstanding_quantity:
            raise ValueError("Cancelled opening remainder cannot remain outstanding")
    deliveries = {d.id: d for d in inputs.commitments}
    for event in inputs.receipts:
        receipt = event.receipt
        if receipt.delivery_id not in deliveries:
            raise ValueError("Actual receipt references unknown external commitment")
        if (
            not inputs.start < receipt.received_at <= inputs.end
            or event.available_at < receipt.received_at
            or receipt.expiry_date < receipt.received_at.astimezone(SINGAPORE).date()
            or receipt.closing_counts
        ):
            raise ValueError(
                "Invalid receipt time, recording time, expiry or historical correction"
            )
        _expiry(receipt.expiry_date)
    all_receipts = old_receipts + [r.receipt for r in inputs.receipts]
    if any(not r.request_id.strip() for r in all_receipts):
        raise ValueError("Nonempty receipt request identity required")
    _unique([r.id for r in all_receipts], "receipt")
    retry_keys = [(r.delivery_id, r.request_id) for r in all_receipts]
    if len(retry_keys) != len(set(retry_keys)):
        raise ValueError(
            "Duplicate receipt retry; deduplicate retries before execution"
        )
    _unique([r.lot_id for r in old_receipts], "prior receipt lot")
    _unique(list(opening) + [r.receipt.lot_id for r in inputs.receipts], "physical lot")
    for event in inputs.cancellations:
        if (
            event.delivery_id not in deliveries
            or not inputs.start < event.at <= inputs.end
            or event.available_at < event.at
        ):
            raise ValueError("Invalid cancellation reference or timestamp")
    _unique([e.id for e in inputs.cancellations], "cancellation")
    _unique([e.id for e in inputs.hidden_losses], "hidden loss")
    for loss in inputs.hidden_losses:
        if not inputs.start < loss.at <= inputs.end:
            raise ValueError("Hidden loss outside physical day")
    # Complete observed coverage, including explicitly closed gaps. Actual receipt
    # boundaries split batches: no inferred within-batch receipt ordering. Hidden
    # loss times NEVER alter public interval boundaries.
    boundaries = {inputs.start, inputs.end}
    boundaries.update(t for b in buckets for t in (b.start, b.end))
    boundaries.update(r.receipt.received_at for r in inputs.receipts)
    ordered = sorted(boundaries)
    return tuple(pairwise(ordered))


def simulate_day(inputs: PhysicalDay, catalogue: Catalogue) -> PhysicalResult:
    """Execute explicit realised events without modifying any supplied object.

    Equal-time policy: expiry, hidden loss, sales, receipts, cancellations; stable
    IDs within kind. Thus a receipt at a batch end covers subsequent sales only.
    Invalid/inconsistent fixtures raise ValueError; no partial certified result.
    """
    # Revalidate/copy canonical mutable nested models, including model_copy edits.
    inputs = PhysicalDay.model_validate(inputs.model_dump())
    catalogue = Catalogue.model_validate(catalogue.model_dump())
    values = [r.quantity for r in catalogue.recipes]
    values += [
        q for lot in inputs.opening_lots for q in (lot.quantity, lot.initial_quantity)
    ]
    values += [o.unit_price for o in inputs.orders]
    values += [r.receipt.quantity for r in inputs.receipts]
    values += [e.quantity for e in inputs.hidden_losses + inputs.cancellations]
    values += [
        q
        for d in inputs.commitments
        for q in (
            d.expected_quantity,
            d.received_quantity,
            d.cancelled_quantity,
            d.outstanding_quantity,
        )
    ]
    if any(not v.is_finite() or v < 0 for v in values):
        raise ValueError("Finite nonnegative Decimal quantities required")
    # Each order consumes at most two recipe portions. Allow carry digits for
    # all repeated movement/transaction sums, independently of ambient context.
    with localcontext(
        Context(prec=_precision(values) + len(str(len(inputs.orders) + 1)) + 3)
    ):
        intervals = _validate(inputs, catalogue)
        return _execute(inputs, catalogue, intervals)


def _execute(
    data: PhysicalDay,
    catalogue: Catalogue,
    intervals: tuple[tuple[datetime, datetime], ...],
) -> PhysicalResult:
    metadata = {lot.id: lot for lot in data.opening_lots}
    stock = {lot.id: lot.quantity for lot in data.opening_lots}
    # opening, received, consumed, hidden loss, expired
    ledger = {
        lot.id: [lot.quantity, ZERO, ZERO, ZERO, ZERO] for lot in data.opening_lots
    }
    deliveries = {d.id: d for d in data.commitments}
    received = {d.id: d.received_quantity for d in data.commitments}
    cancelled = {d.id: d.cancelled_quantity for d in data.commitments}
    remaining = {d.id: d.outstanding_quantity for d in data.commitments}
    movements: list[Movement] = []
    outcomes: list[SaleOutcome] = []
    dish_ids = sorted(d.id for d in catalogue.menu_items)
    units: dict[str, Literal["kg", "litres", "pieces"]] = {
        i.id: i.unit for i in catalogue.ingredients
    }
    usage = {
        (dish, portions): calculate_requirements(
            {dish: Decimal(portions)},
            catalogue.menu_items,
            catalogue.ingredients,
            catalogue.recipes,
            sparse=True,
        )
        for dish in dish_ids
        for portions in (1, 2)
    }
    orders = {o.id: o for o in data.orders}
    receipts = {r.receipt.id: r for r in data.receipts}
    losses = {e.id: e for e in data.hidden_losses}
    cancellations = {e.id: e for e in data.cancellations}
    timeline = [(o.at, 2, o.id) for o in data.orders]
    timeline += [(r.receipt.received_at, 3, r.receipt.id) for r in data.receipts]
    timeline += [(e.at, 1, e.id) for e in data.hidden_losses]
    timeline += [(e.at, 4, e.id) for e in data.cancellations]
    timeline += [(data.start, 0, ""), (data.end, 0, "")]
    timeline += [
        (_expiry(l.expiry_date), 0, l.id)
        for l in data.opening_lots
        if data.start < _expiry(l.expiry_date) <= data.end
    ]
    timeline += [
        (_expiry(r.receipt.expiry_date), 0, r.receipt.lot_id)
        for r in data.receipts
        if _expiry(r.receipt.expiry_date) <= data.end
    ]
    for at, kind, identity in sorted(timeline):
        for key in sorted(metadata):
            lot = metadata[key]
            if stock[key] and _expiry(lot.expiry_date) <= at:
                amount = stock[key]
                stock[key] = ZERO
                ledger[key][4] += amount
                movements.append(
                    Movement(
                        max(data.start, _expiry(lot.expiry_date)),
                        key,
                        "EXPIRY",
                        amount,
                        key,
                    )
                )
        if kind == 1:
            loss = losses[identity]
            if loss.lot_id not in stock or loss.quantity > stock[loss.lot_id]:
                raise ValueError("Hidden loss exceeds available usable lot stock")
            stock[loss.lot_id] -= loss.quantity
            ledger[loss.lot_id][3] += loss.quantity
            movements.append(
                Movement(at, loss.lot_id, "HIDDEN_LOSS", loss.quantity, identity)
            )
        elif kind == 2:
            order = orders[identity]
            portions = 1 + order.free_portions
            needed = usage[order.menu_item_id, portions]
            missing = tuple(
                i
                for i, q in needed.items()
                if q
                > sum(
                    (stock[k] for k, lot in metadata.items() if lot.ingredient_id == i),
                    ZERO,
                )
            )
            if not missing:
                # Same canonical FEFO policy as projector/replay; no helper or
                # observed-history behaviour is changed by this physical executor.
                keys = sorted(
                    metadata,
                    key=lambda k: (metadata[k].expiry_date, metadata[k].received_at, k),
                )
                for ingredient, required in needed.items():
                    for key in keys:
                        if metadata[key].ingredient_id != ingredient or not required:
                            continue
                        amount = min(required, stock[key])
                        if amount:
                            stock[key] -= amount
                            required -= amount
                            ledger[key][2] += amount
                            movements.append(
                                Movement(at, key, "CONSUMPTION", amount, identity)
                            )
            outcomes.append(
                SaleOutcome(
                    identity,
                    at,
                    order.menu_item_id,
                    portions,
                    0 if missing else portions,
                    0 if missing else 1,
                    0 if missing else order.free_portions,
                    ZERO if missing else order.unit_price,
                    portions if missing else 0,
                    missing,
                )
            )
        elif kind == 3:
            receipt = receipts[identity].receipt
            delivery = deliveries[receipt.delivery_id]
            if receipt.quantity > remaining[delivery.id]:
                raise ValueError(
                    "Receipt exceeds outstanding commitment after cancellations"
                )
            remaining[delivery.id] -= receipt.quantity
            received[delivery.id] += receipt.quantity
            if receipt.remainder == "CANCELLED":
                cancelled[delivery.id] += remaining[delivery.id]
                remaining[delivery.id] = ZERO
            metadata[receipt.lot_id] = InventoryLot(
                id=receipt.lot_id,
                ingredient_id=delivery.ingredient_id,
                unit=units[delivery.ingredient_id],
                received_at=at,
                expiry_date=receipt.expiry_date,
                initial_quantity=receipt.quantity,
                quantity=receipt.quantity,
                counted_at=at,
            )
            stock[receipt.lot_id] = receipt.quantity
            ledger[receipt.lot_id] = [ZERO, receipt.quantity, ZERO, ZERO, ZERO]
            movements.append(
                Movement(at, receipt.lot_id, "RECEIPT", receipt.quantity, identity)
            )
        elif kind == 4:
            event = cancellations[identity]
            if event.quantity > remaining[event.delivery_id]:
                raise ValueError("Cancellation exceeds outstanding commitment")
            remaining[event.delivery_id] -= event.quantity
            cancelled[event.delivery_id] += event.quantity
    batches = []
    for start, end in intervals:
        sales = {
            dish: sum(
                o.served
                for o in outcomes
                if o.menu_item_id == dish and start < o.at <= end
            )
            for dish in dish_ids
        }
        # IDs use semantic bounds, never row positions. All timestamps canonical SGT.
        batch_id = f"{start.astimezone(SINGAPORE).isoformat()}/{end.astimezone(SINGAPORE).isoformat()}"
        batches.append(
            ObservedBatch(
                SalesBatch(
                    source=data.fixture_id,
                    batch_id=batch_id,
                    id=f"{data.fixture_id}:{batch_id}:1",
                    period_start=start,
                    period_end=end,
                    sales=sales,
                    revision=1,
                    active=True,
                ),
                max(
                    [end + timedelta(seconds=data.batch_reporting_delay_seconds)]
                    + [
                        r.available_at
                        for r in data.receipts
                        if r.receipt.received_at in (start, end)
                    ]
                ),
            )
        )
    daily = DailySalesObservation(
        data.target_date,
        data.closing_available_at,
        1,
        {
            dish: sum(o.served for o in outcomes if o.menu_item_id == dish)
            for dish in dish_ids
        },
        any(o.free_portions for o in data.orders),
        any(o.unmet for o in outcomes),
    )
    # Expired stock is retained physically until explicit removal; expiry is NOT
    # a disposal observation. Usable balances exclude it. Hidden losses stay hidden.
    closing = tuple(
        metadata[k].model_copy(
            update={
                "quantity": stock[k] + ledger[k][4],
                "counted_at": data.end,
            }
        )
        for k in sorted(metadata)
    )
    observations = Observations(
        data.start,
        tuple(
            metadata[l.id].model_copy(deep=True)
            for l in sorted(data.opening_lots, key=lambda l: l.id)
        ),
        tuple(
            (i, tuple(sorted(ids))) for i, ids in sorted(data.opening_manifest.items())
        ),
        tuple(batches),
        tuple(
            sorted(data.receipts, key=lambda r: (r.receipt.received_at, r.receipt.id))
        ),
        tuple(sorted(data.cancellations, key=lambda e: (e.at, e.id))),
        daily,
        tuple(
            ObservedDishSales(
                dish,
                sum(o.served for o in outcomes if o.menu_item_id == dish),
                sum(o.paid for o in outcomes if o.menu_item_id == dish),
                sum(o.free for o in outcomes if o.menu_item_id == dish),
                sum(o.paid for o in outcomes if o.menu_item_id == dish),
                sum((o.revenue for o in outcomes if o.menu_item_id == dish), ZERO),
            )
            for dish in dish_ids
        ),
        closing,
        tuple(
            (i, tuple(l.id for l in closing if l.ingredient_id == i))
            for i in sorted(units)
        ),
        data.closing_available_at,
    )
    assert data.fefo_policy == FEFO_POLICY
    return PhysicalResult(
        VERSION,
        catalogue.catalogue_hash,
        catalogue.recipe_hash,
        observations,
        tuple(outcomes),
        tuple(
            LotLedger(
                k,
                metadata[k].ingredient_id,
                metadata[k].unit,
                ledger[k][0],
                ledger[k][1],
                ledger[k][2],
                ledger[k][3],
                ledger[k][4],
                stock[k],
            )
            for k in sorted(metadata)
        ),
        tuple(sorted(movements, key=lambda m: (m.at, m.kind, m.source_id, m.lot_id))),
        tuple(
            CommitmentBalance(
                k,
                deliveries[k].expected_quantity,
                received[k],
                cancelled[k],
                remaining[k],
            )
            for k in sorted(deliveries)
        ),
    )


def observations_at(observations: Observations, *, known_at: datetime) -> Observations:
    """Filter only the observation stream. Cannot access evaluator truth.

    Returned canonical mutable models are defensive copies. Daily final totals
    replace (never add to) batch totals in forecasting history. This seam emits
    exact revision 1 observations; later correction selection is Backend-owned.
    """
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("Knowledge time must be timezone-aware")
    daily = observations.daily_sales
    return Observations(
        observations.opening_at,
        tuple(
            l.model_copy(deep=True)
            for l in observations.opening_lots
            if l.counted_at <= known_at
        ),
        observations.opening_manifest if observations.opening_at <= known_at else (),
        tuple(
            ObservedBatch(b.batch.model_copy(deep=True), b.available_at)
            for b in observations.batches
            if b.available_at <= known_at
        ),
        tuple(
            r.model_copy(deep=True)
            for r in observations.receipts
            if r.available_at <= known_at
        ),
        tuple(
            e.model_copy(deep=True)
            for e in observations.cancellations
            if e.available_at <= known_at
        ),
        daily if daily and daily.available_at <= known_at else None,
        observations.daily_accounting
        if daily and daily.available_at <= known_at
        else (),
        tuple(l.model_copy(deep=True) for l in observations.closing_lots)
        if observations.closing_available_at <= known_at
        else (),
        observations.closing_manifest
        if observations.closing_available_at <= known_at
        else (),
        observations.closing_available_at,
    )

"""Pure one-day fixture projection. No historical replay or transport contract."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from typing import Literal

from src.forecasting import SINGAPORE
from src.operations_schemas import Delivery
from src.requirements import calculate_requirements
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

ZERO = Decimal(0)
SOURCE_NAMES = frozenset(
    {"snapshot", "opening", "supply", "catalogue", "recipe", "forecast", "profile"}
)
FixtureFEFO = Literal[
    "EXPIRY_RECEIVED_ID", "EXPIRY_ID", "FEFO_EXPIRY_RECEIVED_LOT_ID_V1"
]
FEFO_POLICY = "FEFO_EXPIRY_RECEIVED_LOT_ID_V1"


@dataclass(frozen=True)
class SourceEvidence:
    """Caller-resolved fixture evidence; availability uses the knowledge clock."""

    reference: str | None
    available_at: datetime | None
    captured_revision: str | None


@dataclass(frozen=True)
class ExpectedSupply:
    """Existing Delivery plus explicit expected-expiry evidence, not an actual lot."""

    delivery: Delivery
    expiry_date: date | None
    expiry_evidence: SourceEvidence | None
    projected_lot_id: str | None = None


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    source: str


@dataclass(frozen=True)
class LotBalance:
    key: str
    ingredient_id: str
    unit: str
    source: Literal["OPENING_ESTIMATE", "EXPECTED_SUPPLY"]
    opening: Decimal
    admitted: Decimal
    allocated: Decimal
    expired: Decimal
    closing: Decimal


@dataclass(frozen=True)
class IngredientBalance:
    ingredient_id: str
    unit: str
    opening: Decimal
    admitted: Decimal
    required: Decimal
    allocated: Decimal
    unmet: Decimal
    expired: Decimal
    closing: Decimal


@dataclass(frozen=True)
class BucketProjection:
    start: datetime
    end: datetime
    ingredients: tuple[IngredientBalance, ...]
    lots: tuple[LotBalance, ...]


@dataclass(frozen=True)
class ExpiryQuantity:
    at: datetime
    lot_key: str
    quantity: Decimal


@dataclass(frozen=True)
class ShortageInterval:
    ingredient_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class InventoryProjection:
    as_of: datetime
    horizon_end: datetime
    known_at: datetime
    captured_revision: str
    fixture_fefo: FixtureFEFO
    evidence: tuple[tuple[str, SourceEvidence], ...]
    complete: bool
    findings: tuple[Finding, ...]
    buckets: tuple[BucketProjection, ...] | None
    lots: tuple[LotBalance, ...] | None
    ingredients: tuple[IngredientBalance, ...] | None
    expiries: tuple[ExpiryQuantity, ...] | None
    first_shortages: tuple[ShortageInterval, ...] | None
    provenance: Literal["PROJECTED"] = "PROJECTED"


def _aware(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timestamps must be timezone-aware")
    return value.astimezone(SINGAPORE)


def _id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty identities required")


def _quantity(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Finite nonnegative Decimal quantity required")


def _precision(values: Sequence[Decimal]) -> int:
    nonzero = [q for q in values if q]
    if not nonzero:
        return 28
    # Covers exact products already computed by the recipe helper, subtraction
    # and the largest possible sum. Never inherit the caller's Decimal context.
    return max(
        28,
        max(q.adjusted() for q in nonzero)
        - min(int(q.as_tuple().exponent) for q in nonzero)
        + len(str(len(nonzero)))
        + 3,
    )


def _expiry(day: date) -> datetime:
    if type(day) is not date or day == date.max:
        raise ValueError("Expiry must be a supported date")
    return datetime.combine(day + timedelta(days=1), time.min, SINGAPORE)


def project_inventory(
    opening_lots: Sequence[EstimatedInventoryLot],
    buckets: Sequence[ProjectedDemandBucket],
    menu_items: Sequence[MenuItem],
    ingredients: Sequence[Ingredient],
    recipes: Sequence[RecipeItem],
    supplies: Sequence[ExpectedSupply],
    *,
    as_of: datetime,
    target_date: date,
    horizon_end: datetime,
    known_at: datetime,
    captured_revision: str,
    opening_manifest: Mapping[str, Sequence[str]],
    supply_manifest: Sequence[str],
    recipe_manifest: Sequence[tuple[str, str]],
    service_profile: Sequence[ServicePeriod],
    evidence: Mapping[str, SourceEvidence],
    fixture_fefo: FixtureFEFO,
) -> InventoryProjection:
    """Project one service day from explicit frozen fixture inputs.

    Structural contradictions raise ValueError. Missing evidence/coverage or
    unsupported timing returns complete=False with numerical fields None.
    Manifests explicitly declare expected lots (empty means verified zero),
    deliveries and recipe lines. Evidence resolution remains the caller's duty.

    Bucket balances are measured after start-boundary events and before end-
    boundary events. Whole-horizon totals include gap events and events at the
    inclusive horizon end. Demand is allocated at bucket end using only stock
    available at its start; arrivals inside a bucket are unsupported.
    """
    as_of, horizon_end, known_at = map(_aware, (as_of, horizon_end, known_at))
    _id(captured_revision)
    if fixture_fefo not in ("EXPIRY_RECEIVED_ID", "EXPIRY_ID", FEFO_POLICY):
        raise ValueError("Explicit fixture FEFO ordering required")
    if type(target_date) is not date or target_date == date.max:
        raise ValueError("One supported target date required")
    day_start = datetime.combine(target_date, time.min, SINGAPORE)
    day_end = day_start + timedelta(days=1)
    if not as_of < horizon_end or not day_start < horizon_end <= day_end:
        raise ValueError("Horizon must end within the one target service day")
    if as_of.date() not in (target_date, target_date - timedelta(days=1)):
        raise ValueError("Opening must be on the service day or preceding setup day")

    findings: set[Finding] = set()

    def check_evidence(name: str, item: SourceEvidence | None) -> None:
        if item is None:
            findings.add(Finding("MISSING_EVIDENCE", name))
            return
        if not isinstance(item, SourceEvidence):
            raise TypeError("Expected SourceEvidence")
        if item.reference is not None and not isinstance(item.reference, str):
            raise ValueError("Evidence references must be strings")
        if not item.reference or not item.reference.strip():
            findings.add(Finding("MISSING_EVIDENCE", name))
        if item.captured_revision != captured_revision:
            findings.add(Finding("REVISION_MISMATCH", name))
        if item.available_at is None:
            findings.add(Finding("MISSING_AVAILABILITY", name))
        elif _aware(item.available_at) > known_at:
            findings.add(Finding("NOT_YET_AVAILABLE", name))

    if set(evidence) - SOURCE_NAMES:
        raise ValueError("Unknown evidence category")
    for name in sorted(SOURCE_NAMES):
        check_evidence(name, evidence.get(name))

    # Reuse the allocator's public profile validation and expected interval set.
    expected = allocate_service_buckets(
        {d.id: ZERO for d in menu_items},
        menu_items,
        target_date=target_date,
        profile=service_profile,
    )
    intervals = {(b.start, b.end) for b in expected}
    ordered = sorted(buckets, key=lambda b: _aware(b.start))
    actual = []
    for b in ordered:
        start, end = _aware(b.start), _aware(b.end)
        if b.provenance != "PROJECTED" or not day_start <= start < end <= horizon_end:
            raise ValueError("Expected projected service intervals within the horizon")
        if actual and start < actual[-1][1]:
            raise ValueError("Overlapping or duplicate demand buckets")
        actual.append((start, end))
    if set(actual) != intervals:
        findings.add(Finding("DEMAND_COVERAGE_MISMATCH", "profile"))
    if any(start < as_of for start, _ in actual):
        findings.add(Finding("UNSUPPORTED_OPENING_CUTOFF", "opening"))

    # Validate catalogue/recipes even if every demand bucket is missing.
    calculate_requirements(
        {d.id: ZERO for d in menu_items}, menu_items, ingredients, recipes
    )
    units = {i.id: i.unit for i in ingredients}
    for identifier in [*units, *(d.id for d in menu_items)]:
        _id(identifier)
    pairs = [(r.menu_item_id, r.ingredient_id) for r in recipes]
    if len(set(recipe_manifest)) != len(recipe_manifest):
        raise ValueError("Duplicate recipe manifest line")
    if set(pairs) != set(recipe_manifest):
        findings.add(Finding("RECIPE_MANIFEST_MISMATCH", "recipe"))
    requirements = [
        calculate_requirements(b.expected_portions, menu_items, ingredients, recipes)
        for b in ordered
    ]

    # Copy existing mutable backend models; never change the caller's records.
    for lot in opening_lots:
        for q in (lot.quantity, lot.initial_quantity, lot.unallocated_consumption):
            _quantity(q)
        if type(lot.coverage_complete) is not bool:
            raise ValueError("Explicit boolean coverage required")
    lots = [EstimatedInventoryLot.model_validate(l.model_dump()) for l in opening_lots]
    lot_by_id = {l.id: l for l in lots}
    if len(lot_by_id) != len(lots):
        raise ValueError("Duplicate opening lot")
    if set(opening_manifest) - set(units):
        raise ValueError("Unknown opening-manifest ingredient")
    if set(opening_manifest) != set(units):
        findings.add(Finding("OPENING_COVERAGE_MISMATCH", "opening"))
    declared = [key for ids in opening_manifest.values() for key in ids]
    if len(set(declared)) != len(declared):
        raise ValueError("Duplicate manifest lot")
    for ingredient in units:
        if set(opening_manifest.get(ingredient, ())) != {
            l.id for l in lots if l.ingredient_id == ingredient
        }:
            findings.add(Finding("OPENING_COVERAGE_MISMATCH", ingredient))
    deficits: dict[str, Decimal] = {}
    for lot in lots:
        _id(lot.id)
        for q in (lot.quantity, lot.initial_quantity, lot.unallocated_consumption):
            _quantity(q)
        if lot.ingredient_id not in units or lot.unit != units[lot.ingredient_id]:
            raise ValueError("Unknown ingredient or incompatible lot unit")
        if not _aware(lot.received_at) <= _aware(lot.counted_at) <= as_of:
            raise ValueError("Opening receipt/count times inconsistent")
        if _aware(lot.as_of) != as_of:
            findings.add(Finding("OPENING_AS_OF_MISMATCH", lot.id))
        if (
            _aware(lot.coverage_start) != _aware(lot.counted_at)
            or not lot.coverage_complete
        ):
            findings.add(Finding("MISSING_OBSERVED_COVERAGE", lot.id))
        expired = _expiry(lot.expiry_date) <= as_of
        if expired != (lot.status == "EXPIRED") or (expired and lot.quantity != 0):
            raise ValueError("Opening usable quantity/status contradicts expiry")
        if lot.expiry_date < _aware(lot.received_at).date():
            raise ValueError("Lot expired before receipt")
        if (
            lot.ingredient_id in deficits
            and deficits[lot.ingredient_id] != lot.unallocated_consumption
        ):
            raise ValueError("Repeated ingredient deficits disagree")
        deficits[lot.ingredient_id] = lot.unallocated_consumption
        if lot.unallocated_consumption:
            findings.add(
                Finding("HISTORICAL_UNALLOCATED_CONSUMPTION", lot.ingredient_id)
            )

    delivery_ids = [s.delivery.id for s in supplies]
    if len(set(delivery_ids)) != len(delivery_ids) or len(set(supply_manifest)) != len(
        supply_manifest
    ):
        raise ValueError("Duplicate supply identity")
    if set(delivery_ids) != set(supply_manifest):
        findings.add(Finding("SUPPLY_COVERAGE_MISMATCH", "supply"))
    received_ids: set[str] = set()
    received_lots: set[str] = set()
    deliveries = []
    for supply in supplies:
        for q in (
            supply.delivery.expected_quantity,
            supply.delivery.received_quantity,
            supply.delivery.cancelled_quantity,
            supply.delivery.outstanding_quantity,
        ):
            _quantity(q)
        for receipt in supply.delivery.receipts:
            _quantity(receipt.quantity)
        d = Delivery.model_validate(supply.delivery.model_dump())
        _id(d.id)
        if d.ingredient_id not in units:
            raise ValueError("Unknown supply ingredient")
        if not _aware(d.ordered_at) <= as_of or _aware(d.expected_at) < _aware(
            d.ordered_at
        ):
            raise ValueError("Inconsistent order/arrival time")
        for q in (
            d.expected_quantity,
            d.received_quantity,
            d.cancelled_quantity,
            d.outstanding_quantity,
        ):
            _quantity(q)
        received = []
        request_ids: set[str] = set()
        for receipt in d.receipts:
            if (
                receipt.id in received_ids
                or receipt.lot_id in received_lots
                or receipt.request_id in request_ids
            ):
                raise ValueError("Duplicate received supply")
            received_ids.add(receipt.id)
            received_lots.add(receipt.lot_id)
            request_ids.add(receipt.request_id)
            if (
                receipt.delivery_id != d.id
                or not _aware(d.ordered_at) <= _aware(receipt.received_at) <= as_of
            ):
                raise ValueError("Receipt reference/time inconsistent with opening")
            lot = lot_by_id.get(receipt.lot_id)
            if lot is None:
                findings.add(Finding("RECEIPT_OPENING_LINK_MISSING", receipt.lot_id))
            elif (
                lot.ingredient_id != d.ingredient_id
                or lot.initial_quantity != receipt.quantity
                or lot.received_at != receipt.received_at
                or lot.expiry_date != receipt.expiry_date
            ):
                raise ValueError("Receipt disagrees with opening lot")
            received.append(receipt.quantity)
        with localcontext(
            Context(
                prec=_precision(
                    [
                        *received,
                        d.expected_quantity,
                        d.received_quantity,
                        d.cancelled_quantity,
                        d.outstanding_quantity,
                    ]
                )
            )
        ):
            if sum(received, ZERO) != d.received_quantity or (
                d.expected_quantity
                != d.received_quantity + d.cancelled_quantity + d.outstanding_quantity
            ):
                raise ValueError(
                    "Received/cancelled/outstanding quantities inconsistent"
                )
        if d.outstanding_quantity:
            if any(r.remainder == "CANCELLED" for r in d.receipts):
                raise ValueError(
                    "Cancelled receipt remainder cannot remain outstanding"
                )
            check_evidence("expiry:" + d.id, supply.expiry_evidence)
            arrival = _aware(d.expected_at)
            if arrival <= as_of:
                findings.add(Finding("OVERDUE_EXPECTED_SUPPLY", d.id))
            if any(start < arrival < end for start, end in actual):
                findings.add(Finding("UNSUPPORTED_MID_BUCKET_ARRIVAL", d.id))
            if supply.expiry_date is None:
                findings.add(Finding("MISSING_EXPECTED_EXPIRY", d.id))
            elif _expiry(supply.expiry_date) <= arrival:
                raise ValueError("Expected supply expires before arrival")
        deliveries.append((d, supply))

    # Result keys remain namespaced for provenance; they are not FEFO tie keys.
    identities = {"opening:" + lot.id: lot.id for lot in lots}
    if fixture_fefo == FEFO_POLICY:
        for d, supply in deliveries:
            if d.outstanding_quantity:
                if not supply.projected_lot_id or not supply.projected_lot_id.strip():
                    findings.add(Finding("MISSING_PROJECTED_LOT_ID", d.id))
                else:
                    identities["supply:" + d.id] = supply.projected_lot_id
        if len(set(identities.values())) != len(identities):
            raise ValueError(
                "FEFO identities must be unique across actual and projected lots"
            )

    source_rows = tuple(sorted(evidence.items())) + tuple(
        ("expiry:" + d.id, s.expiry_evidence)
        for d, s in sorted(deliveries, key=lambda row: row[0].id)
        if s.expiry_evidence is not None
    )
    if findings:
        return InventoryProjection(
            as_of=as_of,
            horizon_end=horizon_end,
            known_at=known_at,
            captured_revision=captured_revision,
            fixture_fefo=fixture_fefo,
            evidence=source_rows,
            complete=False,
            findings=tuple(sorted(findings)),
            buckets=None,
            lots=None,
            ingredients=None,
            expiries=None,
            first_shortages=None,
        )

    # This is forward depletion only. It does not select or replay observed events.
    metadata = {}
    balances = {}
    opening = {}
    arrivals = []
    for lot in lots:
        key = "opening:" + lot.id
        metadata[key] = (
            lot.ingredient_id,
            lot.unit,
            "OPENING_ESTIMATE",
            lot.received_at,
            _expiry(lot.expiry_date),
        )
        balances[key] = opening[key] = lot.quantity
    for d, supply in deliveries:
        if d.outstanding_quantity and supply.expiry_date is not None:
            key = "supply:" + d.id
            metadata[key] = (
                d.ingredient_id,
                units[d.ingredient_id],
                "EXPECTED_SUPPLY",
                _aware(d.expected_at),
                _expiry(supply.expiry_date),
            )
            balances[key] = opening[key] = ZERO
            if d.expected_at <= horizon_end:
                arrivals.append((_aware(d.expected_at), key, d.outstanding_quantity))
    keys = sorted(metadata)
    allocation_order = sorted(
        keys,
        key=lambda k: (
            metadata[k][4],
            metadata[k][3] if fixture_fefo != "EXPIRY_ID" else as_of,
            identities[k] if fixture_fefo == FEFO_POLICY else k,
        ),
    )
    values = [
        *balances.values(),
        *(d.outstanding_quantity for d, _ in deliveries),
        *(q for need in requirements for q in need.values()),
    ]
    with localcontext(Context(prec=_precision(values))):
        admitted = dict.fromkeys(keys, ZERO)
        allocated = dict.fromkeys(keys, ZERO)
        expired_qty = dict.fromkeys(keys, ZERO)
        expiry_rows = []
        processed_arrivals: set[str] = set()

        def boundary(at: datetime) -> None:
            for arrival, key, quantity in sorted(arrivals):
                if arrival <= at and key not in processed_arrivals:
                    balances[key] += quantity
                    admitted[key] += quantity
                    processed_arrivals.add(key)
            for key in keys:
                if metadata[key][4] <= at and balances[key]:
                    quantity = balances[key]
                    balances[key] = ZERO
                    expired_qty[key] += quantity
                    expiry_rows.append(ExpiryQuantity(metadata[key][4], key, quantity))

        def lot_rows(start, incoming, used, expired):
            return tuple(
                LotBalance(
                    k,
                    metadata[k][0],
                    metadata[k][1],
                    metadata[k][2],
                    start[k],
                    incoming[k],
                    used[k],
                    expired[k],
                    balances[k],
                )
                for k in keys
            )

        def ingredient_rows(rows, need, unmet):
            return tuple(
                IngredientBalance(
                    i,
                    units[i],
                    sum((r.opening for r in rows if r.ingredient_id == i), ZERO),
                    sum((r.admitted for r in rows if r.ingredient_id == i), ZERO),
                    need[i],
                    sum((r.allocated for r in rows if r.ingredient_id == i), ZERO),
                    unmet[i],
                    sum((r.expired for r in rows if r.ingredient_id == i), ZERO),
                    sum((r.closing for r in rows if r.ingredient_id == i), ZERO),
                )
                for i in sorted(units)
            )

        bucket_rows = []
        first = {}
        total_need = dict.fromkeys(units, ZERO)
        total_unmet = dict.fromkeys(units, ZERO)
        zeros = dict.fromkeys(keys, ZERO)
        for (start, end), need in zip(actual, requirements, strict=True):
            boundary(start)
            initial = dict(balances)
            used = dict.fromkeys(keys, ZERO)
            unmet = dict(need)
            for key in allocation_order:
                ingredient = metadata[key][0]
                take = min(balances[key], unmet[ingredient])
                balances[key] -= take
                unmet[ingredient] -= take
                used[key] = take
                allocated[key] += take
            for ingredient in units:
                total_need[ingredient] += need[ingredient]
                total_unmet[ingredient] += unmet[ingredient]
                if unmet[ingredient] and ingredient not in first:
                    first[ingredient] = ShortageInterval(ingredient, start, end)
            rows = lot_rows(initial, zeros, used, zeros)
            bucket_rows.append(
                BucketProjection(start, end, ingredient_rows(rows, need, unmet), rows)
            )
        boundary(horizon_end)
        rows = lot_rows(opening, admitted, allocated, expired_qty)
        return InventoryProjection(
            as_of=as_of,
            horizon_end=horizon_end,
            known_at=known_at,
            captured_revision=captured_revision,
            fixture_fefo=fixture_fefo,
            evidence=source_rows,
            complete=True,
            findings=(),
            buckets=tuple(bucket_rows),
            lots=rows,
            ingredients=ingredient_rows(rows, total_need, total_unmet),
            expiries=tuple(sorted(expiry_rows, key=lambda e: (e.at, e.lot_key))),
            first_shortages=tuple(first[i] for i in sorted(first)),
        )

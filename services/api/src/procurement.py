"""Pure one-day cash search and independent candidate validation.

Internal numerical records only: no backend Candidate, order creation or adapter.
All new purchases are hypothetical supply placed at the explicit opening/issue.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from math import ceil, prod
from typing import Literal, TypedDict

from src.inventory_projection import (
    ExpectedSupply,
    Finding,
    FixtureFEFO,
    InventoryProjection,
    SourceEvidence,
    _aware,
    _quantity,
    project_inventory,
)
from src.operations_schemas import Delivery
from src.requirements import calculate_requirements
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
    SupplierOffer,
)
from src.service_buckets import ProjectedDemandBucket, ServicePeriod


class ProjectionInputs(TypedDict):
    """Argument bundle for the existing projector, not a second stock schema."""

    opening_lots: Sequence[EstimatedInventoryLot]
    buckets: Sequence[ProjectedDemandBucket]
    menu_items: Sequence[MenuItem]
    ingredients: Sequence[Ingredient]
    recipes: Sequence[RecipeItem]
    supplies: Sequence[ExpectedSupply]
    as_of: datetime
    target_date: date
    horizon_end: datetime
    known_at: datetime
    captured_revision: str
    opening_manifest: Mapping[str, Sequence[str]]
    supply_manifest: Sequence[str]
    recipe_manifest: Sequence[tuple[str, str]]
    service_profile: Sequence[ServicePeriod]
    evidence: Mapping[str, SourceEvidence]
    fixture_fefo: FixtureFEFO


@dataclass(frozen=True)
class DatedRequirement:
    start: datetime
    end: datetime
    quantities: Mapping[str, Decimal]


@dataclass(frozen=True)
class OrderingOpportunity:
    id: str
    offer_id: str
    ordered_at: datetime
    arrival_at: datetime
    kind: Literal["NORMAL", "EMERGENCY"]
    expiry_date: date | None
    expiry_evidence: SourceEvidence | None


@dataclass(frozen=True)
class ProcurementInputs:
    inventory: ProjectionInputs
    issue_time: datetime
    requirements: Sequence[DatedRequirement]
    suppliers: Sequence[Supplier]
    offers: Sequence[SupplierOffer]
    approved_offer_manifest: Sequence[tuple[str, str, str]]
    opportunities: Sequence[OrderingOpportunity] | None
    safety: Mapping[str, Decimal]
    storage: Mapping[str, Decimal]
    budget: Decimal | None
    fee_policy: str | None
    tie_policy: str | None
    expiry_policy: str | None
    cash_policy: str | None
    policy_evidence: Mapping[str, SourceEvidence]
    offer_evidence: Mapping[str, SourceEvidence]
    max_packs: Mapping[str, int]
    work_limit: int
    # Legacy callers keep explicit full Cartesian enumeration, never implicit pruning.
    search_policy: str = "COMPLETE_CARTESIAN_V1"


@dataclass(frozen=True, order=True)
class PurchaseLine:
    opportunity_id: str
    quantity: Decimal
    unit: str


@dataclass(frozen=True)
class Cash:
    acquisition: Decimal
    delivery: Decimal
    emergency: Decimal
    total: Decimal


@dataclass(frozen=True)
class PurchaseCandidate:
    lines: tuple[PurchaseLine, ...]
    claimed_cash: Cash | None = None


@dataclass(frozen=True)
class CandidateValidation:
    complete: bool
    feasible: bool | None
    findings: tuple[Finding, ...]
    violations: tuple[Finding, ...]
    cash: Cash | None
    projection: InventoryProjection | None
    # Local names distinguish hypothetical recommendations from fixed commitments.
    proposed_supply_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcurementResult:
    status: Literal["OPTIMAL_IN_DOMAIN", "INFEASIBLE_IN_DOMAIN", "INCOMPLETE"]
    search_complete: bool
    optimal_in_domain: bool
    evaluated: int
    domain_size: int | None
    candidate: PurchaseCandidate | None
    validation: CandidateValidation | None
    findings: tuple[Finding, ...]
    rejection_counts: tuple[tuple[str, int], ...]
    diagnostic_incumbent: PurchaseCandidate | None = None
    search_policy: str = "COMPLETE_CARTESIAN_V1"
    reduced_domain_size: int | None = None
    work_used: int = 0


POLICIES = {
    "fee_policy": "SUPPLIER_ARRIVAL_ONCE_PLUS_EMERGENCY_ONCE",
    "tie_policy": "FEWER_LINES_THEN_STABLE_LINES",
    "expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
    "cash_policy": "CASH_SLICE_V1_EXACT_SGD",
}
EXPIRY_POLICY = POLICIES["expiry_policy"]
TIE_POLICY = "SUPPLIER_ID_THEN_INGREDIENT_ID_V1"
SEARCH_POLICY = "COMPLETE_PRUNED_DOMAIN_V1"
SUPPORTED_POLICIES = {key: {value} for key, value in POLICIES.items()}
SUPPORTED_POLICIES["fee_policy"].add("SUPPLIER_ARRIVAL_ONCE_V1")
SUPPORTED_POLICIES["cash_policy"].add("CASH_SLICE_V1")
SUPPORTED_POLICIES["tie_policy"].add(TIE_POLICY)
EVIDENCE = frozenset(
    {"approvals", "opportunities", "safety", "storage", "budget", "domain", *POLICIES}
)
NUMERIC_OFFER_FIELDS = (
    "unit_price",
    "available_quantity",
    "moq",
    "pack_size",
    "delivery_fee_sgd",
    "emergency_fee_sgd",
)


def _decimal(value: Fraction) -> Decimal:
    # Inputs to outputs are sums/products of finite Decimals, never 1/3.
    with localcontext(
        Context(
            prec=max(
                28, len(str(abs(value.numerator))) + len(str(value.denominator)) + 2
            )
        )
    ):
        return Decimal(value.numerator) / Decimal(value.denominator)


def _q(offer: SupplierOffer, field: str) -> Decimal:
    value = getattr(offer, field)
    assert isinstance(value, Decimal)  # _prepare established required completeness.
    return value


@dataclass(frozen=True)
class _Prepared:
    offers: Mapping[str, SupplierOffer]
    opportunities: Mapping[str, OrderingOpportunity]
    baseline: InventoryProjection
    findings: tuple[Finding, ...]


def _prepare(p: ProcurementInputs) -> _Prepared:
    inv = p.inventory
    baseline = project_inventory(**inv)
    findings = set(baseline.findings)

    def missing(code: str, source: str) -> None:
        findings.add(Finding(code, source))

    def evidence(source: str, item: SourceEvidence | None) -> None:
        if item is None or not item.reference or not item.reference.strip():
            missing("MISSING_EVIDENCE", source)
        if item is None or item.available_at is None:
            missing("MISSING_AVAILABILITY", source)
        elif _aware(item.available_at) > _aware(inv["known_at"]):
            missing("NOT_YET_AVAILABLE", source)
        if item is not None and item.captured_revision != inv["captured_revision"]:
            missing("REVISION_MISMATCH", source)

    issue = _aware(p.issue_time)
    if issue != _aware(inv["as_of"]):
        missing("UNSUPPORTED_ISSUE_OPENING", "issue_time")
    if type(p.work_limit) is not int or p.work_limit < 1:
        raise ValueError("work_limit must be a positive integer candidate count")
    if set(p.policy_evidence) - EVIDENCE:
        raise ValueError("Unknown policy evidence category")
    for key in sorted(EVIDENCE):
        evidence(key, p.policy_evidence.get(key))
    for key, supported in SUPPORTED_POLICIES.items():
        if getattr(p, key) not in supported:
            missing("MISSING_OR_UNSUPPORTED_POLICY", key)
    if p.search_policy not in ("COMPLETE_CARTESIAN_V1", SEARCH_POLICY):
        missing("MISSING_OR_UNSUPPORTED_POLICY", "search_policy")
    if p.search_policy == SEARCH_POLICY:
        evidence("search_policy", p.policy_evidence.get("domain"))
    units = {i.id: i.unit for i in inv["ingredients"]}
    for name, vector in (("safety", p.safety), ("storage", p.storage)):
        if set(vector) - set(units):
            raise ValueError("Unknown constraint ingredient")
        if set(vector) != set(units):
            missing("CONSTRAINT_COVERAGE_MISMATCH", name)
        for q in vector.values():
            _quantity(q)
    if p.budget is None:
        missing("MISSING_REQUIRED_DATA", "budget")
    else:
        _quantity(p.budget)

    declared = {}
    for r in p.requirements:
        key = (_aware(r.start), _aware(r.end))
        if key in declared:
            raise ValueError("Duplicate dated ingredient requirements")
        if set(r.quantities) - set(units):
            raise ValueError("Unknown required ingredient")
        for q in r.quantities.values():
            _quantity(q)
        declared[key] = dict(r.quantities)
    derived = {
        (_aware(b.start), _aware(b.end)): calculate_requirements(
            b.expected_portions, inv["menu_items"], inv["ingredients"], inv["recipes"]
        )
        for b in inv["buckets"]
    }
    if declared != derived:
        missing("DATED_REQUIREMENTS_MISMATCH", "requirements")

    supplier_ids = [s.id for s in p.suppliers]
    if len(set(supplier_ids)) != len(supplier_ids) or any(
        not s.strip() for s in supplier_ids
    ):
        raise ValueError("Unique approved supplier identities required")
    offers = {o.id: o for o in p.offers}
    if len(offers) != len(p.offers) or any(not s.strip() for s in offers):
        raise ValueError("Unique offer identities required")
    approved = set(p.approved_offer_manifest)
    if len(approved) != len(p.approved_offer_manifest):
        raise ValueError("Duplicate approved offer manifest entry")
    if approved != {(o.id, o.supplier_id, o.ingredient_id) for o in p.offers}:
        missing("APPROVED_OFFER_COVERAGE_MISMATCH", "offers")
    if set(p.offer_evidence) - set(offers):
        raise ValueError("Unknown offer evidence")
    for o in offers.values():
        if o.supplier_id not in supplier_ids or o.ingredient_id not in units:
            raise ValueError("Unapproved supplier or unknown offer ingredient")
        evidence(o.id, p.offer_evidence.get(o.id))
        if _aware(o.observed_at) > _aware(inv["known_at"]):
            missing("NOT_YET_AVAILABLE", o.id)
        for field in NUMERIC_OFFER_FIELDS:
            value = getattr(o, field)
            if value is None:
                missing("MISSING_REQUIRED_DATA", f"{o.id}.{field}")
            else:
                _quantity(value)
                if field == "pack_size" and not value:
                    raise ValueError("pack_size must be positive")
        # Check raw Decimals before serialization; also revalidate model_copy bypasses.
        SupplierOffer.model_validate(o.model_dump())
        for field in ("lead_time_minutes", "shelf_life_days_on_arrival"):
            value = getattr(o, field)
            if value is None:
                missing("MISSING_REQUIRED_DATA", f"{o.id}.{field}")
            elif type(value) is not int or value < 0:
                raise ValueError(
                    "Lead time and shelf-life days must be nonnegative integers"
                )
        if o.current_status == "UNKNOWN" or o.order_cutoff.kind == "UNKNOWN":
            missing("MISSING_REQUIRED_DATA", o.id)
        if o.order_cutoff.kind == "LOCAL_TIME" and o.order_cutoff.local_time.tzinfo:
            raise ValueError("Cutoff is a Singapore local wall-clock time")
        if o.feasible_delivery_at is None:
            missing("MISSING_REQUIRED_DATA", o.id + ".feasible_delivery_at")
        else:
            for t in o.feasible_delivery_at:
                _aware(t)
        if o.recent_on_time_rate is not None:
            _quantity(o.recent_on_time_rate)
            if o.recent_on_time_rate > 1:
                raise ValueError("Reliability context must be in [0,1]")

    opportunities = {o.id: o for o in p.opportunities or ()}
    if p.opportunities is None:
        missing("MISSING_REQUIRED_DATA", "opportunities")
    if len(opportunities) != len(p.opportunities or ()):
        raise ValueError("Duplicate ordering opportunity")
    slots = set()
    groups = {}
    for op in opportunities.values():
        if not op.id.strip() or op.offer_id not in offers:
            raise ValueError("Unknown offer or empty opportunity identity")
        offer = offers[op.offer_id]
        order, arrival = _aware(op.ordered_at), _aware(op.arrival_at)
        if op.kind not in ("NORMAL", "EMERGENCY"):
            raise ValueError("Unknown purchasing kind")
        if p.fee_policy == "SUPPLIER_ARRIVAL_ONCE_V1" and op.kind != "NORMAL":
            missing("UNSUPPORTED_NORMAL_ONLY_POLICY", op.id)
        key = (op.offer_id, order, arrival, op.kind)
        if key in slots:
            raise ValueError("Duplicate semantic opportunity")
        slots.add(key)
        if order != issue:
            missing("UNSUPPORTED_ORDER_TIME", op.id)
        if arrival <= issue:
            missing("UNSUPPORTED_ARRIVAL_AT_OR_BEFORE_OPENING", op.id)
        if any(b.start < arrival < b.end for b in inv["buckets"]):
            missing("UNSUPPORTED_MID_BUCKET_ARRIVAL", op.id)
        evidence("expiry:" + op.id, op.expiry_evidence)
        if op.expiry_date is None:
            missing("MISSING_EXPECTED_EXPIRY", op.id)
        elif type(op.expiry_date) is not date or op.expiry_date == date.max:
            raise ValueError("Supported expected expiry date required")
        group = (offer.supplier_id, arrival)
        fees = (offer.delivery_fee_sgd, offer.emergency_fee_sgd)
        if group in groups and groups[group] != fees:
            missing("CONFLICTING_GROUP_FEES", op.id)
        groups[group] = fees
        bound = p.max_packs.get(op.id)
        if bound is None:
            missing("MISSING_SEARCH_BOUND", op.id)
        elif type(bound) is not int or bound < 0:
            raise ValueError("Pack bounds must be nonnegative integers")
        elif (
            offer.available_quantity is not None
            and offer.pack_size is not None
            and bound != Fraction(offer.available_quantity) // Fraction(offer.pack_size)
        ):
            raise ValueError(
                "Search bound must cover every pack allowed by new capacity"
            )
    if p.opportunities is not None and set(p.max_packs) - set(opportunities):
        raise ValueError("Unknown search-bound opportunity")
    return _Prepared(offers, opportunities, baseline, tuple(sorted(findings)))


def _validate(
    p: ProcurementInputs, c: PurchaseCandidate, ready: _Prepared
) -> CandidateValidation:
    if ready.findings:
        return CandidateValidation(False, None, ready.findings, (), None, None)
    violations: set[Finding] = set()

    def reject(code: str, source: str) -> None:
        violations.add(Finding(code, source))

    units = {i.id: i.unit for i in p.inventory["ingredients"]}
    used: dict[str, Fraction] = {}
    fees: dict[tuple[str, datetime], tuple[Fraction, Fraction, bool]] = {}
    acquisition = Fraction(0)
    proposed = []
    seen = set()
    for line in c.lines:
        op = ready.opportunities.get(line.opportunity_id)
        if op is None:
            reject("UNKNOWN_OPPORTUNITY", line.opportunity_id)
            continue
        if line.opportunity_id in seen:
            reject("DUPLICATE_LINE", line.opportunity_id)
        seen.add(line.opportunity_id)
        o = ready.offers[op.offer_id]
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            reject("INVALID_QUANTITY", op.id)
            continue
        q = Fraction(line.quantity)
        if line.unit != units[o.ingredient_id]:
            reject("UNIT_MISMATCH", op.id)
        if o.current_status != "AVAILABLE":
            reject("OFFER_UNAVAILABLE", op.id)
        if q < _q(o, "moq"):
            reject("MOQ", op.id)
        packs = q / Fraction(_q(o, "pack_size"))
        if packs.denominator != 1:
            reject("PACK_MULTIPLE", op.id)
        if packs > p.max_packs[op.id]:
            reject("DOMAIN_BOUND", op.id)
        used[o.id] = used.get(o.id, Fraction(0)) + q
        if used[o.id] > _q(o, "available_quantity"):
            reject("SHARED_OFFER_CAPACITY", o.id)
        order, arrival = _aware(op.ordered_at), _aware(op.arrival_at)
        if (
            o.order_cutoff.kind == "LOCAL_TIME"
            and order.time() > o.order_cutoff.local_time
        ):
            reject("ORDER_CUTOFF", op.id)
        assert o.lead_time_minutes is not None
        if arrival < order + timedelta(minutes=o.lead_time_minutes):
            reject("LEAD_TIME", op.id)
        if arrival not in (o.feasible_delivery_at or ()):
            reject("DELIVERY_SLOT", op.id)
        assert o.shelf_life_days_on_arrival is not None
        expected_expiry = arrival.date() + timedelta(
            days=o.shelf_life_days_on_arrival - 1
        )
        if o.shelf_life_days_on_arrival < 1:
            reject("UNUSABLE_ARRIVAL_SHELF_LIFE", op.id)
        if op.expiry_date != expected_expiry:
            reject("EXPECTED_EXPIRY_POLICY", op.id)
        acquisition += q * Fraction(_q(o, "unit_price"))
        group = (o.supplier_id, arrival)
        prior_emergency = fees.get(group, (Fraction(0), Fraction(0), False))[2]
        fees[group] = (
            Fraction(_q(o, "delivery_fee_sgd")),
            Fraction(_q(o, "emergency_fee_sgd")),
            prior_emergency or op.kind == "EMERGENCY",
        )
        proposed.append((line, op, o))
    delivery = sum((f[0] for f in fees.values()), Fraction(0))
    emergency = sum((f[1] for f in fees.values() if f[2]), Fraction(0))
    cash = Cash(
        *map(
            _decimal,
            (acquisition, delivery, emergency, acquisition + delivery + emergency),
        )
    )
    if c.claimed_cash is not None:
        for amount in (
            c.claimed_cash.acquisition,
            c.claimed_cash.delivery,
            c.claimed_cash.emergency,
            c.claimed_cash.total,
        ):
            if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
                reject("INVALID_CASH", "claimed_cash")
        if (
            Finding("INVALID_CASH", "claimed_cash") not in violations
            and c.claimed_cash != cash
        ):
            reject("CASH_MISMATCH", "claimed_cash")
    assert p.budget is not None
    if cash.total > p.budget:
        reject("NEW_ORDER_BUDGET", "budget")
    if violations:
        return CandidateValidation(
            True, False, (), tuple(sorted(violations)), cash, None
        )

    # This constructs in-memory hypothetical supplies only, never external facts.
    # The reused Delivery quantity scale is checked, never rounded or bypassed.
    supplies = list(p.inventory["supplies"])
    ids = list(p.inventory["supply_manifest"])
    new_ids = []
    for line, op, o in sorted(proposed, key=lambda row: row[0]):
        key = "proposed:" + op.id
        if key in ids:
            raise ValueError("Hypothetical supply identity collides with fixed supply")
        try:
            d = Delivery(
                id=key,
                supplier_id=o.supplier_id,
                ingredient_id=o.ingredient_id,
                kind=op.kind,
                expected_quantity=line.quantity,
                outstanding_quantity=line.quantity,
                received_quantity=Decimal(0),
                cancelled_quantity=Decimal(0),
                receipts=[],
                ordered_at=op.ordered_at,
                expected_at=op.arrival_at,
            )
        except ValueError:
            return CandidateValidation(
                False,
                None,
                (Finding("UNSUPPORTED_PURCHASE_PRECISION", op.id),),
                (),
                None,
                None,
            )
        supplies.append(
            ExpectedSupply(
                d,
                op.expiry_date,
                op.expiry_evidence,
                "projected-purchase:"
                + json.dumps(_semantic_op(op, o), separators=(",", ":")),
            )
        )
        ids.append(key)
        new_ids.append(key)
    inv = p.inventory.copy()
    inv["supplies"], inv["supply_manifest"] = supplies, ids
    projection = project_inventory(**inv)
    if not projection.complete:
        return CandidateValidation(False, None, projection.findings, (), None, None)
    assert projection.buckets is not None and projection.expiries is not None
    assert projection.lots is not None
    for b in projection.buckets:
        for row in b.ingredients:
            source = f"{row.ingredient_id}@{b.start.isoformat()}/{b.end.isoformat()}"
            if row.unmet:
                reject("TIMELY_DEMAND_UNMET", source)
            if row.closing < p.safety[row.ingredient_id]:
                reject("SAFETY_SHORTFALL", source)

    # Storage evidence reuses the projector's allocations and expiry quantities.
    # End consumption, expiry, then simultaneous receipts; check before next usage.
    balances = {i: Fraction(0) for i in units}
    for lot in p.inventory["opening_lots"]:
        balances[lot.ingredient_id] += Fraction(lot.quantity)
    events: dict[datetime, dict[str, Fraction]] = {}

    def movement(at: datetime, ingredient: str, q: Fraction) -> None:
        row = events.setdefault(_aware(at), {})
        row[ingredient] = row.get(ingredient, Fraction(0)) + q

    def storage(at: datetime) -> None:
        for i, q in balances.items():
            if q > p.storage[i]:
                reject(
                    "STORAGE_CAPACITY",
                    f"{i}@{at.isoformat()}: {_decimal(q)} > {p.storage[i]}",
                )

    for b in projection.buckets:
        for row in b.ingredients:
            movement(b.end, row.ingredient_id, -Fraction(row.allocated))
    lot_ingredients = {r.key: r.ingredient_id for r in projection.lots}
    for e in projection.expiries:
        movement(e.at, lot_ingredients[e.lot_key], -Fraction(e.quantity))
    for s in supplies:
        d = s.delivery
        if d.outstanding_quantity and d.expected_at <= inv["horizon_end"]:
            movement(d.expected_at, d.ingredient_id, Fraction(d.outstanding_quantity))
    storage(_aware(p.issue_time))
    for at, changes in sorted(events.items()):
        for i, q in changes.items():
            balances[i] += q
        storage(at)
    return CandidateValidation(
        True,
        not violations,
        (),
        tuple(sorted(violations)),
        cash,
        projection,
        tuple(new_ids),
    )


def validate_candidate(
    inputs: ProcurementInputs, candidate: PurchaseCandidate
) -> CandidateValidation:
    """Check lines, cash, timing and constraints without running the search.

    Missing evidence/unsupported scope: complete=False, feasible/cash/projection=None.
    Known violation: complete=True, feasible=False, concrete violations.
    Structurally contradictory inputs raise ValueError; no inputs are mutated.
    """
    return _validate(inputs, candidate, _prepare(inputs))


def _semantic_op(op: OrderingOpportunity, offer: SupplierOffer) -> tuple[str, ...]:
    return (
        offer.supplier_id,
        offer.ingredient_id,
        _aware(op.ordered_at).isoformat(),
        _aware(op.arrival_at).isoformat(),
        op.kind,
        offer.id,
    )


def _candidate_key(p: ProcurementInputs, c: PurchaseCandidate, ready: _Prepared):
    if p.tie_policy != TIE_POLICY:
        return (len(c.lines), c.lines)
    # No fewer-lines preference in the backend's supplier-first contract.
    return tuple(
        sorted(
            (
                *_semantic_op(
                    ready.opportunities[line.opportunity_id],
                    ready.offers[ready.opportunities[line.opportunity_id].offer_id],
                ),
                line.quantity,
                line.unit,
            )
            for line in c.lines
        )
    )


class _SearchLimit(Exception):
    pass


@dataclass
class _Work:
    limit: int
    used: int = 0

    def tick(self) -> None:
        if self.used == self.limit:
            raise _SearchLimit
        self.used += 1


def _reduction_guards(p: ProcurementInputs, ready: _Prepared) -> tuple[Finding, ...]:
    """Sufficient conditions for deleting all above-minimum packs (see docs)."""
    failed = set()

    def require(condition: bool, name: str) -> None:
        if not condition:
            failed.add(Finding("UNSUPPORTED_SEARCH_SCOPE", name))

    require(
        p.cash_policy == "CASH_SLICE_V1", "cash_only_no_discounts_or_future_rewards"
    )
    require(
        p.fee_policy == "SUPPLIER_ARRIVAL_ONCE_V1", "nonnegative_normal_shipment_fees"
    )
    require(p.tie_policy == TIE_POLICY, "semantic_tie_policy")
    require(not any(p.safety.values()), "zero_safety")
    require(
        not p.inventory["supplies"] and not p.inventory["supply_manifest"],
        "empty_commitments",
    )
    ops = list(ready.opportunities.values())
    require(
        len({o.offer_id for o in ops}) == len(ops) == len(ready.offers),
        "one_opportunity_per_offer",
    )
    require(len({_aware(o.arrival_at) for o in ops}) <= 1, "common_arrival")
    buckets = p.inventory["buckets"]
    first = min(_aware(b.start) for b in buckets)
    last = max(_aware(b.end) for b in buckets)
    # Service ending exactly at midnight consumes on the prior date.
    last_day = (last - timedelta(microseconds=1)).date()
    require(
        all(
            not l.quantity or l.expiry_date >= last_day
            for l in p.inventory["opening_lots"]
        ),
        "opening_usable_through_service",
    )
    for op in ops:
        o = ready.offers[op.offer_id]
        arrival, order = _aware(op.arrival_at), _aware(op.ordered_at)
        require(op.kind == "NORMAL", "normal_only")
        require(arrival <= first, "pre_service_arrival")
        require(o.pack_size == 1 and o.moq == 1, "unit_pack_and_moq")
        require(_q(o, "unit_price") > 0, "positive_acquisition")
        require(o.current_status == "AVAILABLE", "available_offers")
        require(
            o.order_cutoff.kind == "NONE"
            or (
                o.order_cutoff.kind == "LOCAL_TIME"
                and order.time() <= o.order_cutoff.local_time
            ),
            "cutoff",
        )
        assert (
            o.lead_time_minutes is not None and o.shelf_life_days_on_arrival is not None
        )
        require(
            arrival >= order + timedelta(minutes=o.lead_time_minutes)
            and arrival in (o.feasible_delivery_at or ()),
            "feasible_arrival",
        )
        require(
            o.shelf_life_days_on_arrival >= 1
            and op.expiry_date is not None
            and op.expiry_date
            == (arrival.date() + timedelta(days=o.shelf_life_days_on_arrival - 1))
            and op.expiry_date >= last_day,
            "new_stock_usable_through_service",
        )
    return tuple(sorted(failed))


def _reduced_pools(p: ProcurementInputs, ready: _Prepared, ids: list[str], work: _Work):
    """Bound allocation construction itself; never materialize capacity ranges."""
    assert ready.baseline.ingredients is not None
    pools: list[list[dict[str, int]]] = []
    for row in ready.baseline.ingredients:
        work.tick()
        need = max(0, ceil(Fraction(row.required) - Fraction(row.opening)))
        group = [
            key
            for key in ids
            if ready.offers[ready.opportunities[key].offer_id].ingredient_id
            == row.ingredient_id
        ]
        caps = [p.max_packs[key] for key in group]
        pool: list[dict[str, int]] = []
        # Iterative DFS avoids recursion limits; stack width is bounded by work.
        stack = [(0, need, {})]
        while stack:
            work.tick()
            depth, remaining, allocation = stack.pop()
            if depth == len(group):
                if remaining == 0:
                    pool.append(allocation)
                continue
            low = max(0, remaining - sum(caps[depth + 1 :]))
            high = min(remaining, caps[depth])
            for count in range(low, high + 1):
                work.tick()
                stack.append(
                    (depth + 1, remaining - count, {**allocation, group[depth]: count})
                )
        pools.append(pool)
    return pools


def search_procurement(inputs: ProcurementInputs) -> ProcurementResult:
    """Complete Cartesian or explicitly guarded minimum-pack search.

    domain_size always records the original capacity domain. Reduced counts and
    generation/evaluation work are separate evidence; interruption is incomplete.
    """
    ready = _prepare(inputs)
    ids = sorted(ready.opportunities)
    sizes = [inputs.max_packs.get(key, 0) + 1 for key in ids]
    domain_size = prod(sizes) if not ready.findings else None
    reduced_size = None
    best = None
    best_validation = None
    best_key = None
    rejected: dict[str, int] = {}
    evaluated = 0
    work = _Work(inputs.work_limit)

    def result(findings=(), complete=False):
        return ProcurementResult(
            ("OPTIMAL_IN_DOMAIN" if best is not None else "INFEASIBLE_IN_DOMAIN")
            if complete
            else "INCOMPLETE",
            complete,
            complete and best is not None,
            evaluated,
            domain_size,
            best if complete else None,
            best_validation if complete else None,
            findings,
            tuple(sorted(rejected.items())),
            best if not complete else None,
            inputs.search_policy,
            reduced_size,
            work.used,
        )

    if ready.findings:
        return result(ready.findings)
    units = {i.id: i.unit for i in inputs.inventory["ingredients"]}
    try:
        pools = None
        if inputs.search_policy == SEARCH_POLICY:
            guards = _reduction_guards(inputs, ready)
            if guards:
                return result(guards)
            pools = _reduced_pools(inputs, ready, ids, work)
            sizes = [len(pool) for pool in pools]
            reduced_size = prod(sizes)
            if reduced_size == 0:
                rejected["INSUFFICIENT_NEW_CAPACITY"] = 1
        size = prod(sizes)
        for index in range(size):
            work.tick()
            remaining = index
            counts = []
            for radix in reversed(sizes):
                remaining, count = divmod(remaining, radix)
                counts.append(count)
            digits = list(reversed(counts))
            allocations = (
                dict(zip(ids, digits, strict=True))
                if pools is None
                else {
                    key: count
                    for pool, digit in zip(pools, digits, strict=True)
                    for key, count in pool[digit].items()
                }
            )
            lines = []
            for key, count in sorted(allocations.items()):
                if count:
                    offer = ready.offers[ready.opportunities[key].offer_id]
                    lines.append(
                        PurchaseLine(
                            key,
                            _decimal(Fraction(_q(offer, "pack_size")) * count),
                            units[offer.ingredient_id],
                        )
                    )
            candidate = PurchaseCandidate(tuple(lines))
            checked = _validate(inputs, candidate, ready)
            evaluated += 1
            if not checked.complete:
                return result(checked.findings)
            for code in {v.code for v in checked.violations}:
                rejected[code] = rejected.get(code, 0) + 1
            if checked.feasible:
                assert checked.cash is not None
                score = (checked.cash.total, _candidate_key(inputs, candidate, ready))
                if best_key is None or score < best_key:
                    best_key = score
                    best = PurchaseCandidate(candidate.lines, checked.cash)
                    best_validation = checked
    except _SearchLimit:
        return result(
            (
                Finding(
                    "SEARCH_LIMIT_REACHED",
                    f"{work.used} work units; {evaluated} candidates",
                ),
            )
        )
    return result(complete=True)

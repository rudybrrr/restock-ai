"""Bounded additional-purchase cash search; internal numerical contract only.

No persistence, order placement, historical replay, continuation or Agent outcome.
The independently callable validator never invokes search. The normal procurement
strategy and its reduction guards are deliberately unchanged.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from math import prod
from typing import TypedDict

from src.coverage import CoverageResult, evidence_findings
from src.inventory_projection import (
    ExpectedSupply,
    Finding,
    SourceEvidence,
    _aware,
    _id,
    _quantity,
)
from src.multiday_projection import MultiDayProjection, project_multiday
from src.operations_schemas import Delivery
from src.procurement import (
    EXPIRY_POLICY,
    NUMERIC_OFFER_FIELDS,
    TIE_POLICY,
    Cash,
    OrderingOpportunity,
    PurchaseCandidate,
    PurchaseLine,
    _decimal,
    _q,
    _semantic_op,
)
from src.promotion_forecasting import ForecastVersion
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
    SupplierOffer,
)

POLICY = "BOUNDED_CONTINGENCY_CASH_V1"
SEARCH_POLICY = "CONTINGENCY_CARTESIAN_V1"
FEE_POLICY = "EXPLICIT_NEW_SHIPMENT_ONCE_V1"
POLICIES = {
    "contingency": POLICY,
    "search": SEARCH_POLICY,
    "fee": FEE_POLICY,
    "cash": "CASH_SLICE_V1",
    "expiry": EXPIRY_POLICY,
    "tie": TIE_POLICY,
    "reliability": "CONTEXT_ONLY",
}
EVIDENCE = frozenset({*POLICIES, "domain", "approvals", "budget", "shipments"})
# Technical support limits, not business defaults or truncated search bounds.
MAX_OPPORTUNITIES = 32
MAX_INPUT_ROWS = 10000
MAX_HORIZON_DAYS = 31


class MultiDayInputs(TypedDict):
    """Exact existing project_multiday argument bundle; not a transport schema."""

    coverage: CoverageResult
    forecasts: Sequence[ForecastVersion]
    menu_items: Sequence[MenuItem]
    ingredients: Sequence[Ingredient]
    recipes: Sequence[RecipeItem]
    opening_lots: Sequence[EstimatedInventoryLot]
    supplies: Sequence[ExpectedSupply]
    opening_manifest: Mapping[str, Sequence[str]]
    supply_manifest: Sequence[str]
    recipe_manifest: Sequence[tuple[str, str]]
    evidence: Mapping[str, SourceEvidence]
    safety: Mapping[str, Decimal]
    storage: Mapping[str, Decimal]
    assessment_end: Mapping[str, datetime]
    constraint_policy: str | None
    fefo_policy: str | None


@dataclass(frozen=True)
class ContingencyInputs:
    inventory: MultiDayInputs
    suppliers: Sequence[Supplier]
    offers: Sequence[SupplierOffer]
    approved_offer_manifest: Sequence[tuple[str, str, str]]
    opportunities: Sequence[OrderingOpportunity] | None
    opportunity_manifest: Sequence[str] | None
    # Each opportunity belongs to one explicitly NEW shipment, never an old one.
    shipment_groups: Mapping[str, str]
    max_packs: Mapping[str, int]
    budget: Decimal | None
    policies: Mapping[str, str | None]
    evidence: Mapping[str, SourceEvidence]
    offer_evidence: Mapping[str, SourceEvidence]
    work_limit: int


@dataclass(frozen=True)
class Addition:
    opportunity_id: str
    offer_id: str
    supplier_id: str
    ingredient_id: str
    shipment_group_id: str
    quantity: Decimal
    unit: str
    ordered_at: datetime
    arrival_at: datetime
    latest_placement_at: datetime
    expiry_date: date
    kind: str


@dataclass(frozen=True)
class ShipmentCharge:
    shipment_group_id: str
    supplier_id: str
    arrival_at: datetime
    delivery: Decimal
    emergency: Decimal


@dataclass(frozen=True)
class ContingencyCandidate:
    purchase: PurchaseCandidate
    # Optional transport claims are compared against independently resolved rows.
    claimed_additions: tuple[Addition, ...] | None = None


@dataclass(frozen=True)
class ContingencyValidation:
    complete: bool
    feasible: bool | None
    findings: tuple[Finding, ...]
    violations: tuple[Finding, ...]
    cash: Cash | None
    additions: tuple[Addition, ...]
    shipments: tuple[ShipmentCharge, ...]
    projection: MultiDayProjection | None


@dataclass(frozen=True)
class NoPurchase:
    """Diagnostic only, even if safe. Dish losses/full economic score unavailable."""

    projection: MultiDayProjection
    fixed_supply_ids: tuple[str, ...]
    actionable: bool = False
    lost_dish_portions: None = None
    economic_score: None = None


@dataclass(frozen=True)
class ContingencyResult:
    status: str
    reason: str | None
    search_complete: bool
    optimal_in_domain: bool
    work_used: int
    evaluated: int
    domain_size: int | None
    candidate: ContingencyCandidate | None
    validation: ContingencyValidation | None
    no_purchase: NoPurchase | None
    findings: tuple[Finding, ...]
    rejection_counts: tuple[tuple[str, int], ...]
    exclusions: tuple[Finding, ...]
    diagnostic_incumbent: ContingencyCandidate | None
    coverage: CoverageResult
    assessment_end: tuple[tuple[str, datetime], ...]
    policies: tuple[tuple[str, str | None], ...]
    evidence: tuple[tuple[str, SourceEvidence], ...]


class _Limit(Exception):
    pass


@dataclass
class _Work:
    limit: int
    used: int = 0

    def charge(self, n: int = 1) -> None:
        if n > self.limit - self.used:
            self.used = self.limit
            raise _Limit
        self.used += n


@dataclass(frozen=True)
class _Prepared:
    offers: Mapping[str, SupplierOffer]
    ops: Mapping[str, OrderingOpportunity]
    baseline: MultiDayProjection | None
    findings: tuple[Finding, ...]
    exclusions: tuple[Finding, ...]


def _prepare(p: ContingencyInputs, work: _Work) -> _Prepared:
    inv, c = p.inventory, p.inventory["coverage"]
    issue, known = map(_aware, (c.issue_time, c.known_at))
    if type(p.work_limit) is not int or not 1 <= p.work_limit <= 1000000:
        raise ValueError("work_limit must be an integer in [1,1000000]")
    rows = (
        len(p.offers)
        + len(p.opportunities or ())
        + len(inv["opening_lots"])
        + len(inv["recipes"])
        + len(inv["ingredients"])
        + len(inv["supplies"])
        + sum(len(s.delivery.receipts) for s in inv["supplies"])
        + sum(len(f.buckets) + len(f.profile) for f in inv["forecasts"])
    )
    if (
        rows > MAX_INPUT_ROWS
        or len(p.opportunities or ()) > MAX_OPPORTUNITIES
        or c.max_horizon_days > MAX_HORIZON_DAYS
    ):
        return _Prepared(
            {}, {}, None, (Finding("UNSUPPORTED_SCOPE", "size/horizon"),), ()
        )
    work.charge(rows + 1)  # Input/domain construction plus baseline evaluation.
    baseline = project_multiday(**inv)
    findings = set(baseline.findings)
    if not c.complete:
        findings.add(Finding("INCOMPLETE_COVERAGE", "coverage"))
    if not baseline.complete:
        findings.add(Finding("INCOMPLETE_PROJECTION", "inventory"))
    for name in EVIDENCE:
        findings.update(
            evidence_findings(name, p.evidence.get(name), known, c.captured_revision)
        )
    for name, policy in POLICIES.items():
        if p.policies.get(name) != policy:
            findings.add(Finding("MISSING_OR_UNSUPPORTED_POLICY", name))
    if set(p.policies) - set(POLICIES):
        raise ValueError("Unknown policy category")
    if p.budget is None:
        findings.add(Finding("MISSING_REQUIRED_DATA", "budget"))
    else:
        _quantity(p.budget)
    units = {i.id: i.unit for i in inv["ingredients"]}
    supplier_ids = [s.id for s in p.suppliers]
    if len(set(supplier_ids)) != len(supplier_ids):
        raise ValueError("Duplicate supplier")
    for key in supplier_ids:
        _id(key)
    offers = {o.id: o for o in p.offers}
    ops = {o.id: o for o in p.opportunities or ()}
    if len(offers) != len(p.offers) or len(ops) != len(p.opportunities or ()):
        raise ValueError("Duplicate offer/opportunity")
    if len(set(p.approved_offer_manifest)) != len(p.approved_offer_manifest):
        raise ValueError("Duplicate approved offer")
    if set(p.approved_offer_manifest) != {
        (o.id, o.supplier_id, o.ingredient_id) for o in p.offers
    }:
        findings.add(Finding("APPROVED_DOMAIN_MISMATCH", "offers"))
    if p.opportunities is None or p.opportunity_manifest is None:
        findings.add(Finding("MISSING_REQUIRED_DATA", "opportunity_domain"))
    elif len(set(p.opportunity_manifest)) != len(p.opportunity_manifest):
        raise ValueError("Duplicate opportunity manifest")
    elif set(p.opportunity_manifest) != set(ops):
        findings.add(Finding("APPROVED_DOMAIN_MISMATCH", "opportunities"))
    if set(p.max_packs) - set(ops) or set(p.shipment_groups) - set(ops):
        raise ValueError("Unknown bound/shipment opportunity")
    if set(p.offer_evidence) - set(offers):
        raise ValueError("Unknown offer evidence")
    for o in offers.values():
        _id(o.id)
        if o.supplier_id not in supplier_ids or o.ingredient_id not in units:
            raise ValueError("Unapproved supplier or unknown ingredient")
        findings.update(
            evidence_findings(
                o.id, p.offer_evidence.get(o.id), known, c.captured_revision
            )
        )
        if _aware(o.observed_at) > known:
            findings.add(Finding("NOT_YET_AVAILABLE", o.id))
        for field in NUMERIC_OFFER_FIELDS:
            value = getattr(o, field)
            if value is None:
                findings.add(Finding("MISSING_REQUIRED_DATA", o.id + "." + field))
            else:
                _quantity(value)
                if field == "pack_size" and value == 0:
                    raise ValueError("Positive pack_size required")
        SupplierOffer.model_validate(o.model_dump())
        for field in ("lead_time_minutes", "shelf_life_days_on_arrival"):
            value = getattr(o, field)
            if value is None:
                findings.add(Finding("MISSING_REQUIRED_DATA", o.id + "." + field))
            elif type(value) is not int or value < 0:
                raise ValueError("Nonnegative integer lead time/shelf life required")
        if (
            o.current_status == "UNKNOWN"
            or o.order_cutoff.kind == "UNKNOWN"
            or o.feasible_delivery_at is None
        ):
            findings.add(Finding("MISSING_REQUIRED_DATA", o.id + ".availability"))
        if o.order_cutoff.kind == "LOCAL_TIME" and o.order_cutoff.local_time.tzinfo:
            raise ValueError("Cutoff must be Singapore local wall time")
        for at in o.feasible_delivery_at or ():
            _aware(at)
        if o.recent_on_time_rate is not None:
            _quantity(o.recent_on_time_rate)
            if o.recent_on_time_rate > 1:
                raise ValueError("Reliability must be in [0,1]")
    groups = {}
    semantic = set()
    for op in ops.values():
        _id(op.id)
        if op.offer_id not in offers or op.kind not in ("NORMAL", "EMERGENCY"):
            raise ValueError("Unknown offer or purchase kind")
        o = offers[op.offer_id]
        order, arrival = map(_aware, (op.ordered_at, op.arrival_at))
        group = p.shipment_groups.get(op.id)
        if not group or not group.strip():
            findings.add(Finding("MISSING_REQUIRED_DATA", "shipment:" + op.id))
        key = (*_semantic_op(op, o), group)
        if key in semantic:
            raise ValueError("Duplicate semantic opportunity in shipment")
        semantic.add(key)
        terms = (o.supplier_id, order, arrival, o.delivery_fee_sgd, o.emergency_fee_sgd)
        if group in groups and groups[group] != terms:
            findings.add(Finding("CONFLICTING_SHIPMENT_TERMS", str(group)))
        groups[group] = terms
        if order != issue or arrival <= issue:
            findings.add(Finding("UNSUPPORTED_ORDER_TIME", op.id))
        end = inv["assessment_end"].get(o.ingredient_id)
        if end is not None and arrival > end:
            findings.add(Finding("OPPORTUNITY_BEYOND_ASSESSMENT", op.id))
        if any(b.start < arrival < b.end for f in inv["forecasts"] for b in f.buckets):
            findings.add(Finding("UNSUPPORTED_MID_BUCKET_ARRIVAL", op.id))
        findings.update(
            evidence_findings(
                "expiry:" + op.id, op.expiry_evidence, known, c.captured_revision
            )
        )
        if op.expiry_date is None:
            findings.add(Finding("MISSING_EXPECTED_EXPIRY", op.id))
        elif type(op.expiry_date) is not date or op.expiry_date == date.max:
            raise ValueError("Invalid expected expiry")
        bound = p.max_packs.get(op.id)
        if bound is None:
            findings.add(Finding("MISSING_SEARCH_BOUND", op.id))
        elif type(bound) is not int or bound < 0:
            raise ValueError("Nonnegative integer pack bound required")
        elif (
            o.available_quantity is not None
            and o.pack_size is not None
            and bound != Fraction(o.available_quantity) // Fraction(o.pack_size)
        ):
            raise ValueError("Bound must include every pack allowed by NEW capacity")
    exclusions = (
        tuple(
            sorted(
                f
                for op in ops.values()
                for f in _op_violations(op, offers[op.offer_id])
            )
        )
        if not findings
        else ()
    )
    return _Prepared(offers, ops, baseline, tuple(sorted(findings)), exclusions)


def _op_violations(op: OrderingOpportunity, o: SupplierOffer) -> tuple[Finding, ...]:
    """Known opportunity exclusions, not missing-data substitutions."""
    result = []
    order, arrival = map(_aware, (op.ordered_at, op.arrival_at))
    assert o.lead_time_minutes is not None and o.shelf_life_days_on_arrival is not None
    if o.current_status != "AVAILABLE":
        result.append(Finding("OFFER_UNAVAILABLE", op.id))
    if _q(o, "available_quantity") < max(_q(o, "moq"), _q(o, "pack_size")):
        result.append(Finding("NO_PURCHASABLE_CAPACITY", op.id))
    if o.order_cutoff.kind == "LOCAL_TIME" and order.time() > o.order_cutoff.local_time:
        result.append(Finding("ORDER_CUTOFF", op.id))
    if arrival < order + timedelta(minutes=o.lead_time_minutes):
        result.append(Finding("LEAD_TIME", op.id))
    if arrival not in (o.feasible_delivery_at or ()):
        result.append(Finding("DELIVERY_SLOT", op.id))
    if o.shelf_life_days_on_arrival < 1 or op.expiry_date != arrival.date() + timedelta(
        days=o.shelf_life_days_on_arrival - 1
    ):
        result.append(Finding("EXPECTED_EXPIRY_POLICY", op.id))
    return tuple(result)


def _validate(
    p: ContingencyInputs, candidate: ContingencyCandidate, ready: _Prepared
) -> ContingencyValidation:
    if ready.findings:
        return ContingencyValidation(
            False, None, ready.findings, (), None, (), (), None
        )
    inv = p.inventory
    units = {i.id: i.unit for i in inv["ingredients"]}
    violations: set[Finding] = set()
    used: dict[str, Fraction] = {}
    additions = []
    fees: dict[str, ShipmentCharge] = {}
    acquisition = Fraction(0)
    seen = set()
    for line in candidate.purchase.lines:
        op = ready.ops.get(line.opportunity_id)
        if op is None:
            violations.add(Finding("UNKNOWN_OPPORTUNITY", line.opportunity_id))
            continue
        if op.id in seen:
            violations.add(Finding("DUPLICATE_LINE", op.id))
        seen.add(op.id)
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            violations.add(Finding("INVALID_QUANTITY", op.id))
            continue
        o = ready.offers[op.offer_id]
        violations.update(_op_violations(op, o))
        q = Fraction(line.quantity)
        for bad, code in (
            (line.unit != units[o.ingredient_id], "UNIT_MISMATCH"),
            (q < _q(o, "moq"), "MOQ"),
            ((q / Fraction(_q(o, "pack_size"))).denominator != 1, "PACK_MULTIPLE"),
            (q > p.max_packs[op.id] * Fraction(_q(o, "pack_size")), "DOMAIN_BOUND"),
        ):
            if bad:
                violations.add(Finding(code, op.id))
        used[o.id] = used.get(o.id, Fraction(0)) + q
        if used[o.id] > _q(o, "available_quantity"):
            violations.add(Finding("SHARED_OFFER_CAPACITY", o.id))
        assert o.lead_time_minutes is not None and op.expiry_date is not None
        latest = _aware(op.arrival_at) - timedelta(minutes=o.lead_time_minutes)
        if o.order_cutoff.kind == "LOCAL_TIME":
            latest = min(
                latest,
                datetime.combine(
                    _aware(op.ordered_at).date(),
                    o.order_cutoff.local_time,
                    latest.tzinfo,
                ),
            )
        group = p.shipment_groups[op.id]
        additions.append(
            Addition(
                op.id,
                o.id,
                o.supplier_id,
                o.ingredient_id,
                group,
                line.quantity,
                line.unit,
                _aware(op.ordered_at),
                _aware(op.arrival_at),
                latest,
                op.expiry_date,
                op.kind,
            )
        )
        acquisition += q * Fraction(_q(o, "unit_price"))
        prior = fees.get(group)
        emergency = _q(o, "emergency_fee_sgd") if op.kind == "EMERGENCY" else Decimal(0)
        fees[group] = ShipmentCharge(
            group,
            o.supplier_id,
            _aware(op.arrival_at),
            _q(o, "delivery_fee_sgd"),
            max(emergency, prior.emergency if prior else Decimal(0)),
        )
    additions = sorted(
        additions,
        key=lambda a: (
            a.supplier_id,
            a.ingredient_id,
            a.ordered_at,
            a.arrival_at,
            a.kind,
            a.offer_id,
            a.shipment_group_id,
            a.quantity,
        ),
    )
    shipments = tuple(fees[k] for k in sorted(fees))
    delivery = sum((Fraction(f.delivery) for f in shipments), Fraction(0))
    emergency = sum((Fraction(f.emergency) for f in shipments), Fraction(0))
    cash = Cash(
        *map(
            _decimal,
            (acquisition, delivery, emergency, acquisition + delivery + emergency),
        )
    )
    if candidate.claimed_additions is not None and candidate.claimed_additions != tuple(
        additions
    ):
        violations.add(Finding("ADDITION_CLAIM_MISMATCH", "candidate"))
    if (
        candidate.purchase.claimed_cash is not None
        and candidate.purchase.claimed_cash != cash
    ):
        violations.add(Finding("CASH_MISMATCH", "candidate"))
    if violations:
        return ContingencyValidation(
            True,
            False,
            (),
            tuple(sorted(violations)),
            cash,
            tuple(additions),
            shipments,
            None,
        )
    # Never mutate or relabel fixed supply. New IDs/lot ordering are semantic.
    supplies = list(inv["supplies"])
    ids = list(inv["supply_manifest"])
    for a in additions:
        op = ready.ops[a.opportunity_id]
        key = "proposed:" + a.opportunity_id
        lot_id = "projected-contingency:" + json.dumps(
            (*_semantic_op(op, ready.offers[a.offer_id]), a.shipment_group_id),
            separators=(",", ":"),
        )
        if key in ids:
            raise ValueError("Hypothetical identity collides with fixed supply")
        try:
            d = Delivery(
                id=key,
                supplier_id=a.supplier_id,
                ingredient_id=a.ingredient_id,
                kind=op.kind,
                expected_quantity=a.quantity,
                received_quantity=Decimal(0),
                cancelled_quantity=Decimal(0),
                outstanding_quantity=a.quantity,
                ordered_at=a.ordered_at,
                expected_at=a.arrival_at,
                receipts=[],
            )
        except ValueError:
            return ContingencyValidation(
                False,
                None,
                (Finding("UNSUPPORTED_PURCHASE_PRECISION", a.opportunity_id),),
                (),
                None,
                (),
                (),
                None,
            )
        supplies.append(ExpectedSupply(d, a.expiry_date, op.expiry_evidence, lot_id))
        ids.append(key)
    projected = inv.copy()
    projected["supplies"], projected["supply_manifest"] = supplies, ids
    projection = project_multiday(**projected)
    if not projection.complete:
        return ContingencyValidation(
            False, None, projection.findings, (), None, (), (), projection
        )
    for b in projection.breaches:
        # Later assessment shortage is diagnostic; storage includes late originals.
        if b.scope == "PROTECTED" or b.kind == "STORAGE":
            violations.add(
                Finding(
                    b.kind,
                    f"{b.ingredient_id}@{b.start.isoformat()}/{b.end.isoformat()}:{b.quantity}/{b.limit}",
                )
            )
    assert p.budget is not None
    if cash.total > p.budget:
        violations.add(Finding("BUDGET", "new_order_budget"))
    return ContingencyValidation(
        True,
        not violations,
        (),
        tuple(sorted(violations)),
        cash,
        tuple(additions),
        shipments,
        projection,
    )


def validate_contingency(
    p: ContingencyInputs, candidate: ContingencyCandidate
) -> ContingencyValidation:
    """Recompute candidate facts; complete feasibility does not certify optimality.

    Structural contradictions raise ValueError. Missing evidence/unsupported scope
    returns incomplete. No search, IO or input mutation occurs.
    """
    work = _Work(p.work_limit)
    try:
        ready = _prepare(p, work)
        work.charge()
        return _validate(p, candidate, ready)
    except _Limit:
        return ContingencyValidation(
            False,
            None,
            (Finding("SEARCH_LIMIT_REACHED", "validation_preparation"),),
            (),
            None,
            (),
            (),
            None,
        )


def _tie(candidate: ContingencyCandidate, p: ContingencyInputs, ready: _Prepared):
    return tuple(
        sorted(
            (
                *_semantic_op(
                    ready.ops[l.opportunity_id],
                    ready.offers[ready.ops[l.opportunity_id].offer_id],
                ),
                p.shipment_groups[l.opportunity_id],
                l.quantity,
                l.unit,
            )
            for l in candidate.purchase.lines
        )
    )


def search_contingency(p: ContingencyInputs) -> ContingencyResult:
    """Exact finite-domain cash optimum only after complete enumeration.

    Every 0..floor(new capacity/pack) allocation is visited, including invalid MOQ
    and shared-capacity combinations. O(opportunities) enumeration memory. A work
    limit never authorizes an incumbent or proves infeasibility.
    """
    work = _Work(p.work_limit)
    ready = _Prepared({}, {}, None, (), ())
    incumbent = None
    best_validation = None
    domain_size = None
    evaluated = 0
    counts: dict[str, int] = {}
    supply_covering = False

    def result(status: str, reason: str | None, findings: tuple[Finding, ...] = ()):
        complete = status != "INCOMPLETE"
        evidence = dict(p.inventory["evidence"])
        evidence.update({"policy:" + k: v for k, v in p.evidence.items()})
        evidence.update({"offer:" + k: v for k, v in p.offer_evidence.items()})
        if ready.baseline is not None:
            evidence.update(dict(ready.baseline.evidence))
        return ContingencyResult(
            status,
            reason,
            complete,
            status == "OPTIMAL_IN_DOMAIN",
            work.used,
            evaluated,
            domain_size,
            incumbent if complete else None,
            best_validation if complete else None,
            NoPurchase(ready.baseline, tuple(sorted(p.inventory["supply_manifest"])))
            if ready.baseline is not None
            else None,
            findings,
            tuple(sorted(counts.items())),
            ready.exclusions,
            incumbent if not complete else None,
            p.inventory["coverage"],
            tuple(sorted(p.inventory["assessment_end"].items())),
            tuple(sorted(p.policies.items())),
            tuple(sorted(evidence.items())),
        )

    try:
        ready = _prepare(p, work)
        if ready.findings:
            return result("INCOMPLETE", "INPUT_OR_SCOPE_INCOMPLETE", ready.findings)
        ops = sorted(
            ready.ops.values(),
            key=lambda o: (
                *_semantic_op(o, ready.offers[o.offer_id]),
                p.shipment_groups[o.id],
            ),
        )
        radices = [p.max_packs[o.id] + 1 for o in ops]
        domain_size = prod(radices)
        digits = [0] * len(ops)
        units = {i.id: i.unit for i in p.inventory["ingredients"]}
        for _ in range(domain_size):
            work.charge(1 + len(ops))  # Construct candidate and evaluate projection.
            candidate = ContingencyCandidate(
                PurchaseCandidate(
                    tuple(
                        PurchaseLine(
                            o.id,
                            _decimal(
                                Fraction(n)
                                * Fraction(_q(ready.offers[o.offer_id], "pack_size"))
                            ),
                            units[ready.offers[o.offer_id].ingredient_id],
                        )
                        for n, o in zip(digits, ops)
                        if n
                    )
                )
            )
            v = _validate(p, candidate, ready)
            evaluated += 1
            if not v.complete:
                return result("INCOMPLETE", "INPUT_OR_SCOPE_INCOMPLETE", v.findings)
            codes = {f.code for f in v.violations}
            for code in codes:
                counts[code] = counts.get(code, 0) + 1
            if v.projection is not None and not codes - {"BUDGET", "STORAGE", "SAFETY"}:
                supply_covering = True
            if v.feasible:
                assert v.cash is not None
                candidate = replace(
                    candidate,
                    purchase=replace(candidate.purchase, claimed_cash=v.cash),
                    claimed_additions=v.additions,
                )
                better = best_validation is None
                if best_validation is not None:
                    assert best_validation.cash is not None and incumbent is not None
                    better = (v.cash.total, _tie(candidate, p, ready)) < (
                        best_validation.cash.total,
                        _tie(incumbent, p, ready),
                    )
                if better:
                    incumbent, best_validation = candidate, v
            for j in range(len(digits) - 1, -1, -1):
                digits[j] += 1
                if digits[j] < radices[j]:
                    break
                digits[j] = 0
        if incumbent is not None:
            return result("OPTIMAL_IN_DOMAIN", None)
        return result(
            "INFEASIBLE_IN_DOMAIN",
            "POLICY_CONSTRAINT_INFEASIBLE"
            if supply_covering
            else "NO_TIMELY_SUPPLY_IN_DOMAIN",
        )
    except _Limit:
        return result(
            "INCOMPLETE",
            "SEARCH_LIMIT_REACHED",
            (
                Finding(
                    "SEARCH_LIMIT_REACHED", f"work={work.used}; evaluated={evaluated}"
                ),
            ),
        )

"""Frozen offer windows and independent hypothetical-purchase validation.

Internal numerical inputs only. Capacity is explicitly for NEW allocations in a
named renewal window; existing external commitments are not subtracted again.
Nothing here renews offers, creates orders, persists data, or searches candidates.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise

from src.contingency import Addition, ShipmentCharge, _op_violations
from src.coverage import evidence_findings
from src.economic_rollout import HypotheticalPurchase
from src.inventory_projection import Finding, SourceEvidence, _aware, _id, _quantity
from src.procurement import (
    NUMERIC_OFFER_FIELDS,
    Cash,
    OrderingOpportunity,
    PurchaseCandidate,
    _decimal,
    _q,
    _semantic_op,
)
from src.schemas import Ingredient, Supplier, SupplierOffer

SUPPLY_POLICY = "STABLE_OFFER_CONTINUATION_V1"
FEE_POLICY = "EXPLICIT_NEW_SHIPMENT_ONCE_V1"
SOURCES = frozenset({"supply_windows", "approvals", "shipments", "policy", "valuation"})


@dataclass(frozen=True)
class CapacityWindow:
    id: str
    offer_id: str
    start: datetime
    end: datetime
    # Remaining NEW capacity, not gross stock requiring fixed-order subtraction.
    available_quantity: Decimal
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class EconomicSupply:
    issue_time: datetime
    horizon_end: datetime
    known_at: datetime
    captured_revision: str
    ingredients: Sequence[Ingredient]
    suppliers: Sequence[Supplier]
    offers: Sequence[SupplierOffer]
    approved_offer_manifest: Sequence[tuple[str, str, str]]
    opportunities: Sequence[OrderingOpportunity] | None
    opportunity_manifest: Sequence[str] | None
    windows: Sequence[CapacityWindow] | None
    window_manifest: Sequence[str] | None
    capacity_window: Mapping[str, str]
    shipment_groups: Mapping[str, str]
    disposal_rates: Mapping[str, Decimal]
    offer_evidence: Mapping[str, SourceEvidence]
    evidence: Mapping[str, SourceEvidence]
    supply_policy: str | None
    fee_policy: str | None
    reliability_policy: str | None


@dataclass(frozen=True)
class SupplyValidation:
    complete: bool
    feasible: bool | None
    findings: tuple[Finding, ...]
    violations: tuple[Finding, ...]
    purchases: tuple[HypotheticalPurchase, ...]
    shipments: tuple[ShipmentCharge, ...]
    cash: Cash | None
    # Current action cash is separate from hypothetical continuation cash.
    immediate_cash: Cash | None
    capacity_used: tuple[tuple[str, Decimal], ...]


def supply_findings(p: EconomicSupply) -> tuple[Finding, ...]:
    """Validate the complete declared domain, including unselected alternatives.

    A manifest is a coverage declaration, not proof of authoritative selection.
    Missing facts return findings; contradictory identities/values raise errors.
    """
    issue, end, known = map(_aware, (p.issue_time, p.horizon_end, p.known_at))
    if not issue < end:
        raise ValueError("Supply horizon must follow issue time")
    if end - issue > timedelta(days=31):
        return (Finding("UNSUPPORTED_SCOPE", "supply horizon"),)
    _id(p.captured_revision)
    findings: set[Finding] = set()
    for source in SOURCES:
        findings.update(
            evidence_findings(
                source, p.evidence.get(source), known, p.captured_revision
            )
        )
    for name, actual, expected in (
        ("supply", p.supply_policy, SUPPLY_POLICY),
        ("fee", p.fee_policy, FEE_POLICY),
        ("reliability", p.reliability_policy, "CONTEXT_ONLY"),
    ):
        if actual != expected:
            findings.add(Finding("MISSING_OR_UNSUPPORTED_POLICY", name))
    ingredients = {i.id: i for i in p.ingredients}
    suppliers = {s.id: s for s in p.suppliers}
    offers = {o.id: o for o in p.offers}
    ops = {o.id: o for o in p.opportunities or ()}
    windows = {w.id: w for w in p.windows or ()}
    for name, rows, keys in (
        ("ingredient", p.ingredients, ingredients),
        ("supplier", p.suppliers, suppliers),
        ("offer", p.offers, offers),
        ("opportunity", p.opportunities or (), ops),
        ("capacity window", p.windows or (), windows),
    ):
        if len(rows) != len(keys):
            raise ValueError("Duplicate " + name)
        for key in keys:
            _id(key)
    if len(set(p.approved_offer_manifest)) != len(p.approved_offer_manifest):
        raise ValueError("Duplicate approved offer manifest entry")
    if set(p.approved_offer_manifest) != {
        (o.id, o.supplier_id, o.ingredient_id) for o in p.offers
    }:
        findings.add(Finding("APPROVED_OFFER_COVERAGE_MISMATCH", "offers"))
    for name, rows, manifest, keys in (
        ("opportunities", p.opportunities, p.opportunity_manifest, ops),
        ("windows", p.windows, p.window_manifest, windows),
    ):
        if rows is None or manifest is None:
            findings.add(Finding("MISSING_REQUIRED_DATA", name))
        elif len(set(manifest)) != len(manifest):
            raise ValueError("Duplicate " + name + " manifest entry")
        elif set(manifest) != set(keys):
            findings.add(Finding("DOMAIN_COVERAGE_MISMATCH", name))
    for name, mapping, expected in (
        ("capacity_window", p.capacity_window, ops),
        ("shipment_groups", p.shipment_groups, ops),
        ("disposal_rates", p.disposal_rates, offers),
        ("offer_evidence", p.offer_evidence, offers),
    ):
        if set(mapping) - set(expected):
            raise ValueError("Unknown reference in " + name)
        if set(mapping) != set(expected):
            findings.add(Finding("MISSING_REQUIRED_DATA", name))
    for o in p.offers:
        if o.currency != "SGD":
            raise ValueError("Unsupported offer currency; explicit SGD required")
        if o.supplier_id not in suppliers or o.ingredient_id not in ingredients:
            raise ValueError("Unknown supplier/ingredient in offer")
        findings.update(
            evidence_findings(
                o.id, p.offer_evidence.get(o.id), known, p.captured_revision
            )
        )
        if _aware(o.observed_at) > known:
            findings.add(Finding("NOT_YET_AVAILABLE", o.id))
        for field in NUMERIC_OFFER_FIELDS:
            value = getattr(o, field)
            if value is None:
                findings.add(Finding("MISSING_REQUIRED_DATA", o.id + ":" + field))
            else:
                _quantity(value)
                if field == "pack_size" and value == 0:
                    raise ValueError("Positive pack size required")
        if (
            o.lead_time_minutes is None
            or o.shelf_life_days_on_arrival is None
            or o.feasible_delivery_at is None
            or o.order_cutoff.kind == "UNKNOWN"
            or o.current_status == "UNKNOWN"
        ):
            findings.add(Finding("MISSING_REQUIRED_DATA", o.id + ":timing/status"))
        if o.lead_time_minutes is not None and o.lead_time_minutes < 0:
            raise ValueError("Negative lead time")
        if (
            o.shelf_life_days_on_arrival is not None
            and o.shelf_life_days_on_arrival < 1
        ):
            raise ValueError("Positive shelf life required")
        if o.recent_on_time_rate is not None:
            _quantity(o.recent_on_time_rate)
            if o.recent_on_time_rate > 1:
                raise ValueError("Invalid contextual reliability")
        if o.id in p.disposal_rates:
            _quantity(p.disposal_rates[o.id])
    by_offer: dict[str, list[CapacityWindow]] = {}
    for w in p.windows or ():
        if w.offer_id not in offers:
            raise ValueError("Unknown capacity-window offer")
        start, finish = map(_aware, (w.start, w.end))
        if not start < finish or start >= end or finish <= issue:
            raise ValueError("Capacity window outside supported horizon")
        _quantity(w.available_quantity)
        cap = offers[w.offer_id].available_quantity
        if cap is not None and w.available_quantity > cap:
            raise ValueError("Stable renewal cannot increase frozen offer capacity")
        findings.update(evidence_findings(w.id, w.evidence, known, p.captured_revision))
        by_offer.setdefault(w.offer_id, []).append(w)
    for rows in by_offer.values():
        ordered = sorted(rows, key=lambda w: _aware(w.start))
        if any(_aware(a.end) > _aware(b.start) for a, b in pairwise(ordered)):
            raise ValueError("Overlapping capacity renewals for one offer")
    groups: dict[str, tuple[object, ...]] = {}
    semantic: set[tuple[object, ...]] = set()
    for op in p.opportunities or ():
        if op.offer_id not in offers:
            raise ValueError("Unknown opportunity offer")
        o = offers[op.offer_id]
        ordered, arrival = map(_aware, (op.ordered_at, op.arrival_at))
        if not issue <= ordered < end or arrival < ordered:
            raise ValueError("Invalid hypothetical order/arrival time")
        if ordered > issue and op.kind != "NORMAL":
            raise ValueError("Routine continuation cannot create emergency orders")
        if op.expiry_date is None:
            findings.add(Finding("MISSING_EXPECTED_EXPIRY", op.id))
        findings.update(
            evidence_findings(
                op.id + ":expiry", op.expiry_evidence, known, p.captured_revision
            )
        )
        identity = _semantic_op(op, o)
        if identity in semantic:
            raise ValueError("Duplicate semantic opportunity")
        semantic.add(identity)
        if op.id in p.capacity_window:
            w = windows.get(p.capacity_window[op.id])
            if w is None or w.offer_id != o.id:
                raise ValueError("Unknown or mismatched capacity-window reference")
            if not _aware(w.start) <= ordered < _aware(w.end):
                raise ValueError("Order outside its capacity window")
        if op.id in p.shipment_groups:
            group = p.shipment_groups[op.id]
            _id(group)
            terms = (
                o.supplier_id,
                ordered,
                arrival,
                op.kind,
                o.delivery_fee_sgd,
                o.emergency_fee_sgd,
            )
            if group in groups and groups[group] != terms:
                raise ValueError("Inconsistent shipment-group terms")
            groups[group] = terms
    return tuple(sorted(findings))


def validate_economic_supply(
    p: EconomicSupply, candidate: PurchaseCandidate
) -> SupplyValidation:
    """Resolve untrusted lines against frozen offers; never invokes an optimiser.

    Feasible here certifies supply terms/capacity/cash only. Stock, storage, safety,
    budget, protection and the full economic trajectory require the outer validator.
    """
    findings = supply_findings(p)
    if findings:
        return SupplyValidation(False, None, findings, (), (), (), None, None, ())
    ops = {o.id: o for o in p.opportunities or ()}
    offers = {o.id: o for o in p.offers}
    windows = {w.id: w for w in p.windows or ()}
    units = {i.id: i.unit for i in p.ingredients}
    used: dict[str, Fraction] = {}
    seen: set[str] = set()
    violations: set[Finding] = set()
    purchases: list[HypotheticalPurchase] = []
    fees: dict[str, ShipmentCharge] = {}
    immediate_groups: set[str] = set()
    acquisition = Fraction(0)
    immediate_acquisition = Fraction(0)
    for line in candidate.lines:
        op = ops.get(line.opportunity_id)
        if op is None:
            violations.add(Finding("UNKNOWN_OPPORTUNITY", line.opportunity_id))
            continue
        if op.id in seen:
            violations.add(Finding("DUPLICATE_LINE", op.id))
            continue
        seen.add(op.id)
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            violations.add(Finding("INVALID_QUANTITY", op.id))
            continue
        o = offers[op.offer_id]
        q = Fraction(line.quantity)
        violations.update(_op_violations(op, o))
        for bad, code in (
            (line.unit != units[o.ingredient_id], "UNIT_MISMATCH"),
            (q < _q(o, "moq"), "MOQ"),
            ((q / Fraction(_q(o, "pack_size"))).denominator != 1, "PACK_MULTIPLE"),
        ):
            if bad:
                violations.add(Finding(code, op.id))
        window = p.capacity_window[op.id]
        used[window] = used.get(window, Fraction(0)) + q
        if used[window] > Fraction(windows[window].available_quantity):
            violations.add(Finding("SHARED_WINDOW_CAPACITY", window))
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
        current = _aware(op.ordered_at) == _aware(p.issue_time)
        addition = Addition(
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
        purchases.append(
            HypotheticalPurchase(
                addition,
                _q(o, "unit_price"),
                p.disposal_rates[o.id],
                "NEW_PURCHASE" if current else "CONTINUATION",
                p.offer_evidence[o.id],
            )
        )
        cost = q * Fraction(_q(o, "unit_price"))
        acquisition += cost
        if current:
            immediate_acquisition += cost
            immediate_groups.add(group)
        fees[group] = ShipmentCharge(
            group,
            o.supplier_id,
            _aware(op.arrival_at),
            _q(o, "delivery_fee_sgd"),
            _q(o, "emergency_fee_sgd") if op.kind == "EMERGENCY" else Decimal(0),
        )

    def cash_for(acquired: Fraction, groups: set[str]) -> Cash:
        delivery = sum((Fraction(fees[g].delivery) for g in groups), Fraction(0))
        emergency = sum((Fraction(fees[g].emergency) for g in groups), Fraction(0))
        return Cash(
            *map(
                _decimal,
                (acquired, delivery, emergency, acquired + delivery + emergency),
            )
        )

    cash = cash_for(acquisition, set(fees))
    if candidate.claimed_cash is not None and candidate.claimed_cash != cash:
        violations.add(Finding("CASH_MISMATCH", "candidate"))
    return SupplyValidation(
        True,
        not violations,
        (),
        tuple(sorted(violations)),
        tuple(sorted(purchases, key=lambda x: x.addition.opportunity_id)),
        tuple(fees[g] for g in sorted(fees)),
        cash,
        cash_for(immediate_acquisition, immediate_groups),
        tuple((k, _decimal(used[k])) for k in sorted(used)),
    )

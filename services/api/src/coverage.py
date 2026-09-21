"""Pure ingredient coverage from an explicitly frozen routine opportunity domain.

Internal numerical inputs, not Backend transport. No future order is created.
The OPEN-at-decision convention is opt-in fixture policy, not a production default.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from math import ceil

from src.forecasting import SINGAPORE
from src.inventory_projection import Finding, SourceEvidence, _aware, _id, _quantity
from src.procurement import EXPIRY_POLICY, OrderingOpportunity
from src.schemas import Ingredient, Supplier, SupplierOffer

OCCASION_POLICY = "FIXTURE_OPEN_AT_DECISION_PROTECT_NEXT_V1"


def evidence_findings(
    name: str, evidence: SourceEvidence | None, known_at: datetime, revision: str
) -> tuple[Finding, ...]:
    """Validate declarations only; source selection remains the input owner's duty."""
    result = []
    if evidence is None:
        return (Finding("MISSING_EVIDENCE", name),)
    if not isinstance(evidence.reference, str) or not evidence.reference.strip():
        result.append(Finding("MISSING_EVIDENCE", name))
    if evidence.captured_revision != revision:
        result.append(Finding("REVISION_MISMATCH", name))
    if evidence.available_at is None:
        result.append(Finding("MISSING_AVAILABILITY", name))
    elif _aware(evidence.available_at) > known_at:
        result.append(Finding("NOT_YET_AVAILABLE", name))
    return tuple(result)


@dataclass(frozen=True)
class Occasion:
    ingredient_id: str
    scheduled_date: date
    status: str
    effective_at: datetime
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class OpportunityDomain:
    ingredient_id: str
    scheduled_date: date
    # () is a declared empty domain; None means unavailable domain.
    opportunities: tuple[OrderingOpportunity, ...] | None
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class ProtectedWindow:
    ingredient_id: str
    start: datetime
    end: datetime
    current_occasion: date | None
    next_occasion: date
    opportunity_id: str


@dataclass(frozen=True)
class CoverageResult:
    issue_time: datetime
    known_at: datetime
    captured_revision: str
    ingredient_ids: tuple[str, ...]
    complete: bool
    windows: tuple[ProtectedWindow, ...]
    forecast_end: datetime | None
    findings: tuple[Finding, ...]
    exclusions: tuple[Finding, ...]
    evidence: tuple[tuple[str, SourceEvidence], ...]
    max_horizon_days: int
    occasion_policy: str | None
    expiry_policy: str | None


def calculate_coverage(
    ingredients: Sequence[Ingredient],
    suppliers: Sequence[Supplier],
    offers: Sequence[SupplierOffer],
    domains: Sequence[OpportunityDomain],
    occasions: Sequence[Occasion],
    *,
    issue_time: datetime,
    known_at: datetime,
    captured_revision: str,
    decision_time: time,
    approved_offer_manifest: Sequence[tuple[str, str, str]],
    evidence: Mapping[str, SourceEvidence],
    offer_evidence: Mapping[str, SourceEvidence],
    occasion_policy: str | None,
    expiry_policy: str | None,
    max_horizon_days: int,
) -> CoverageResult:
    """Protect until the earliest feasible receipt of the next anchored occasion.

    Explicit fixture convention: before today's decision, today's OPEN occasion
    is next; exactly at OPEN, today's action protects through the following one;
    after an OPEN occasion the state is unresolved. ORDERED/SKIPPED consumes the
    occasion without inventing stock. A next occasion already disposed is an
    unsupported domain, not an implicit renewal or skipped-period search.
    Equal cutoff and minimum lead-time boundaries are allowed, as in procurement.
    """
    issue_time, known_at = map(_aware, (issue_time, known_at))
    _id(captured_revision)
    if type(max_horizon_days) is not int or max_horizon_days < 1:
        raise ValueError("Explicit positive maximum horizon required")
    if not isinstance(decision_time, time) or decision_time.tzinfo is not None:
        raise ValueError("Explicit Singapore local decision time required")
    rows = [Ingredient.model_validate(i.model_dump()) for i in ingredients]
    ids = {i.id for i in rows}
    if not ids or len(ids) != len(rows):
        raise ValueError("Unique nonempty catalogue required")
    supplier_ids = {s.id for s in suppliers}
    if len(supplier_ids) != len(suppliers):
        raise ValueError("Duplicate approved supplier")
    for offer in offers:
        for field in (
            "available_quantity",
            "moq",
            "pack_size",
            "unit_price",
            "delivery_fee_sgd",
            "emergency_fee_sgd",
            "recent_on_time_rate",
        ):
            value = getattr(offer, field)
            if value is not None:
                _quantity(value)
        if offer.recent_on_time_rate is not None and offer.recent_on_time_rate > 1:
            raise ValueError("Reliability context must be in [0,1]")
        for value in (offer.lead_time_minutes, offer.shelf_life_days_on_arrival):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(
                    "Nonnegative integer lead time and shelf life required"
                )
    by_offer = {o.id: SupplierOffer.model_validate(o.model_dump()) for o in offers}
    if len(by_offer) != len(offers):
        raise ValueError("Duplicate offer")
    if set(offer_evidence) - set(by_offer):
        raise ValueError("Unknown offer evidence")
    if any(
        o.ingredient_id not in ids or o.supplier_id not in supplier_ids for o in offers
    ):
        raise ValueError("Unknown supplier or ingredient")
    findings: set[Finding] = set()
    exclusions: set[Finding] = set()
    sources: dict[str, SourceEvidence] = dict(evidence)

    def check(name: str, value: SourceEvidence | None) -> tuple[Finding, ...]:
        fs = evidence_findings(name, value, known_at, captured_revision)
        findings.update(fs)
        if value is not None:
            sources[name] = value
        return fs

    for name in ("catalogue", "schedule", "policy", "domain"):
        check(name, evidence.get(name))
    if occasion_policy != OCCASION_POLICY:
        findings.add(Finding("UNRESOLVED_OCCASION_POLICY", "policy"))
    if expiry_policy != EXPIRY_POLICY:
        findings.add(Finding("UNSUPPORTED_EXPIRY_POLICY", "policy"))
    manifest = list(approved_offer_manifest)
    if len(set(manifest)) != len(manifest):
        raise ValueError("Duplicate approved-offer manifest line")
    if set(manifest) != {(o.id, o.supplier_id, o.ingredient_id) for o in offers}:
        findings.add(Finding("OFFER_COVERAGE_MISMATCH", "domain"))
    occasion_map = {(o.ingredient_id, o.scheduled_date): o for o in occasions}
    domain_map = {(d.ingredient_id, d.scheduled_date): d for d in domains}
    if len(occasion_map) != len(occasions) or len(domain_map) != len(domains):
        raise ValueError("Duplicate occasion/domain")
    by_ingredient = {i.id: i for i in rows}
    for ingredient, day in [*occasion_map, *domain_map]:
        if ingredient not in ids or type(day) is not date:
            raise ValueError("Unknown ingredient or invalid scheduled date")
        i = by_ingredient[ingredient]
        if day < i.starting_date or (day - i.starting_date).days % i.interval_days:
            raise ValueError("Occasion must follow starting_date + k * interval_days")
    for o in occasions:
        if o.status not in ("OPEN", "ORDERED", "SKIPPED"):
            raise ValueError("Unknown occasion disposition")
        _aware(o.effective_at)
    windows = []
    global_blocked = bool(findings)
    opportunity_ids: set[str] = set()
    for i in sorted(rows, key=lambda i: i.id):
        before = set(findings)
        k = (issue_time.date() - i.starting_date).days // i.interval_days
        current = (
            i.starting_date + timedelta(days=k * i.interval_days) if k >= 0 else None
        )
        next_day = i.starting_date
        if current is not None:
            at = datetime.combine(current, decision_time, SINGAPORE)
            record = occasion_map.get((i.id, current))
            if record is None:
                findings.add(Finding("MISSING_OCCASION_DISPOSITION", i.id))
            else:
                check("occasion:" + i.id + ":" + str(current), record.evidence)
                if _aware(record.effective_at) > issue_time:
                    findings.add(Finding("FUTURE_OCCASION_STATE", i.id))
                if record.status == "OPEN" and issue_time > at:
                    findings.add(Finding("UNRESOLVED_PAST_OPEN_OCCASION", i.id))
                next_day = (
                    current
                    if record.status == "OPEN" and issue_time < at
                    else current + timedelta(days=i.interval_days)
                )
        nxt = occasion_map.get((i.id, next_day))
        if nxt is None:
            findings.add(Finding("MISSING_NEXT_OCCASION_DISPOSITION", i.id))
        else:
            check("occasion:" + i.id + ":" + str(next_day), nxt.evidence)
            if nxt.status != "OPEN" or _aware(nxt.effective_at) > issue_time:
                findings.add(Finding("UNSUPPORTED_NEXT_OCCASION_STATE", i.id))
        domain = domain_map.get((i.id, next_day))
        if domain is None or domain.opportunities is None:
            findings.add(Finding("MISSING_OPPORTUNITY_DOMAIN", i.id))
            continue
        check("domain:" + i.id, domain.evidence)
        feasible = []
        for op in sorted(domain.opportunities, key=lambda o: o.id):
            _id(op.id)
            if op.id in opportunity_ids:
                raise ValueError("Duplicate opportunity ID")
            opportunity_ids.add(op.id)
            o = by_offer.get(op.offer_id)
            if o is None or o.ingredient_id != i.id:
                raise ValueError("Unknown or incompatible opportunity offer")
            check("offer:" + o.id, offer_evidence.get(o.id))
            if _aware(o.observed_at) > known_at:
                findings.add(Finding("NOT_YET_AVAILABLE", o.id))
            order, arrival = map(_aware, (op.ordered_at, op.arrival_at))
            if order != datetime.combine(next_day, decision_time, SINGAPORE):
                raise ValueError("Opportunity does not belong to its dated occasion")
            reasons = []
            if op.kind != "NORMAL":
                reasons.append("NOT_ROUTINE")
            if o.current_status == "UNAVAILABLE":
                exclusions.add(Finding("UNAVAILABLE", op.id))
                continue
            elif o.current_status != "AVAILABLE":
                findings.add(Finding("MISSING_OFFER_STATUS", o.id))
            fields = (
                o.available_quantity,
                o.moq,
                o.pack_size,
                o.lead_time_minutes,
                o.shelf_life_days_on_arrival,
                o.feasible_delivery_at,
            )
            if any(v is None for v in fields) or o.order_cutoff.kind == "UNKNOWN":
                findings.add(Finding("MISSING_OFFER_TERMS", o.id))
                continue
            assert (
                o.available_quantity is not None
                and o.moq is not None
                and o.pack_size is not None
            )
            assert (
                o.lead_time_minutes is not None
                and o.shelf_life_days_on_arrival is not None
            )
            if o.lead_time_minutes < 0 or o.shelf_life_days_on_arrival < 0:
                raise ValueError("Negative lead time or shelf life")
            if (
                o.order_cutoff.kind == "LOCAL_TIME"
                and o.order_cutoff.local_time.tzinfo is not None
            ):
                raise ValueError("Cutoff must be a naive Singapore local time")
            for q in (o.available_quantity, o.moq, o.pack_size):
                _quantity(q)
            if o.pack_size <= 0:
                raise ValueError("Positive offer pack size required")
            minimum = max(1, ceil(Fraction(o.moq) / Fraction(o.pack_size))) * Fraction(
                o.pack_size
            )
            if minimum > Fraction(o.available_quantity):
                reasons.append("NO_ORDERABLE_PACK")
            if (
                o.order_cutoff.kind == "LOCAL_TIME"
                and order.time() > o.order_cutoff.local_time
            ):
                reasons.append("ORDER_CUTOFF")
            if arrival <= order or arrival < order + timedelta(
                minutes=o.lead_time_minutes
            ):
                reasons.append("MINIMUM_LEAD_TIME")
            if arrival not in (o.feasible_delivery_at or ()):
                reasons.append("UNLISTED_ARRIVAL")
            check("expiry:" + op.id, op.expiry_evidence)
            if op.expiry_date is None:
                findings.add(Finding("MISSING_EXPECTED_EXPIRY", op.id))
            elif (
                o.shelf_life_days_on_arrival < 1
                or op.expiry_date
                != arrival.date() + timedelta(days=o.shelf_life_days_on_arrival - 1)
            ):
                reasons.append("EXPECTED_EXPIRY")
            exclusions.update(Finding(reason, op.id) for reason in reasons)
            if not reasons:
                feasible.append(op)
        if global_blocked or findings != before:
            continue
        if not feasible:
            findings.add(Finding("NO_FEASIBLE_RECEIPT_IN_COMPLETE_DOMAIN", i.id))
            continue
        selected = min(
            feasible, key=lambda op: (_aware(op.arrival_at), op.offer_id, op.id)
        )
        end = _aware(selected.arrival_at)
        windows.append(
            ProtectedWindow(i.id, issue_time, end, current, next_day, selected.id)
        )
        if end > issue_time + timedelta(days=max_horizon_days):
            findings.add(Finding("UNSUPPORTED_HORIZON", i.id))
    return CoverageResult(
        issue_time,
        known_at,
        captured_revision,
        tuple(sorted(ids)),
        not findings,
        tuple(windows),
        max((w.end for w in windows), default=None),
        tuple(sorted(findings)),
        tuple(sorted(exclusions)),
        tuple(sorted(sources.items())),
        max_horizon_days,
        occasion_policy,
        expiry_policy,
    )

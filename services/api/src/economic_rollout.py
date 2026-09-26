"""Forward expected dish fulfilment and valued stock over a common horizon.

This is not observed-history replay or the physical simulator: it consumes only
the frozen forecast, opening estimates, fixed commitments and explicit hypothetical
purchases. Existing projection validates provenance and fixed-supply reconciliation.
Dish-coupled depletion is necessary: unserved dishes consume none of their recipes.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from time import monotonic
from typing import Literal

from src.contingency import Addition, MultiDayInputs, ShipmentCharge
from src.coverage import evidence_findings
from src.economic_ledger import AssetFlow, DishService, EconomicLedger, score_ledger
from src.forecasting import SINGAPORE
from src.inventory_projection import (
    Finding,
    SourceEvidence,
    _aware,
    _expiry,
    _id,
    _quantity,
)
from src.multiday_projection import Breach, MultiDayProjection, project_multiday
from src.procurement import _decimal
from src.requirements import calculate_requirements

FULFILMENT_POLICY = "FRACTIONAL_STABLE_DISH_28DP_DOWN_V1"
HORIZON_POLICY = "COMMON_21_CALENDAR_DAYS_V1"
ZERO = Decimal(0)


@dataclass(frozen=True)
class AssetTerms:
    unit_cost: Decimal
    incremental_disposal_rate: Decimal
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class DishTerms:
    effective_net_price: Decimal
    noningredient_variable_cost: Decimal
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class HypotheticalPurchase:
    addition: Addition
    unit_price: Decimal
    incremental_disposal_rate: Decimal
    origin: Literal["NEW_PURCHASE", "CONTINUATION"]
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class RolloutInputs:
    inventory: MultiDayInputs
    horizon_end: datetime
    asset_terms: Mapping[str, AssetTerms]
    # (bucket start, dish ID), including explicit prices for zero-demand dishes.
    dish_terms: Mapping[tuple[datetime, str], DishTerms]
    purchases: Sequence[HypotheticalPurchase]
    shipments: Sequence[ShipmentCharge]
    evidence: Mapping[str, SourceEvidence]
    ledger_policy: str | None
    terminal_policy: str | None
    money_policy: str | None
    fulfilment_policy: str | None
    horizon_policy: str | None
    work_limit: int


@dataclass(frozen=True)
class ExpectedMovement:
    at: datetime
    resource: str
    ingredient_id: str
    kind: Literal["EXPECTED_ARRIVAL", "PROJECTED_USE", "PROJECTED_EXPIRY"]
    quantity: Decimal
    dish_id: str | None = None


@dataclass(frozen=True)
class RolloutContext:
    issue_time: datetime
    horizon_end: datetime
    known_at: datetime
    captured_revision: str
    policies: tuple[tuple[str, str | None], ...]
    forecast_references: tuple[str, ...]
    fixed_supply_ids: tuple[str, ...]
    evidence: tuple[tuple[str, SourceEvidence], ...]


def _context(p: RolloutInputs) -> RolloutContext:
    c = p.inventory["coverage"]
    return RolloutContext(
        _aware(c.issue_time),
        _aware(p.horizon_end),
        _aware(c.known_at),
        c.captured_revision,
        (
            ("ledger", p.ledger_policy),
            ("terminal", p.terminal_policy),
            ("money", p.money_policy),
            ("fulfilment", p.fulfilment_policy),
            ("horizon", p.horizon_policy),
        ),
        tuple(sorted(f.reference for f in p.inventory["forecasts"])),
        tuple(sorted(p.inventory["supply_manifest"])),
        tuple(sorted(p.evidence.items())),
    )


@dataclass(frozen=True)
class EconomicRollout:
    complete: bool
    findings: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    ledger: EconomicLedger | None
    assets: tuple[AssetFlow, ...] | None
    service: tuple[DishService, ...] | None
    movements: tuple[ExpectedMovement, ...]
    breaches: tuple[Breach, ...]
    fixed_projection: MultiDayProjection | None
    work_used: int
    context: RolloutContext
    provenance: str = "PROJECTED"


class _Limit(Exception):
    pass


@dataclass
class _Work:
    limit: int
    used: int = 0
    deadline: float | None = None

    def charge(self, count: int = 1) -> None:
        if self.deadline is not None and monotonic() >= self.deadline:
            raise _Limit
        if count > self.limit - self.used:
            self.used = self.limit
            raise _Limit
        self.used += count


@dataclass
class _Resource:
    key: str
    lot_id: str
    ingredient: str
    unit: str
    origin: Literal["OPENING", "FIXED_COMMITMENT", "NEW_PURCHASE", "CONTINUATION"]
    arrival: datetime
    expiry: datetime
    quantity: Fraction
    cost: Decimal
    disposal: Decimal
    balance: Fraction = Fraction(0)
    allocated: Fraction = Fraction(0)
    expired: Fraction = Fraction(0)
    admitted: bool = False


def _take(
    resources: Sequence[_Resource], ingredient: str, requested: Fraction
) -> tuple[tuple[_Resource, Fraction], ...]:
    """Deplete the shared forward FEFO state; return allocations, never debt.

    Both dish-coupled economic service and routine ingredient gap checks use this
    helper. These mutable resources are private copies, never observed inventory.
    """
    remaining = requested
    allocations = []
    for r in sorted(resources, key=lambda row: (row.expiry, row.arrival, row.lot_id)):
        if r.ingredient != ingredient or not remaining:
            continue
        take = min(r.balance, remaining)
        if take:
            r.balance -= take
            r.allocated += take
            remaining -= take
            allocations.append((r, take))
    return tuple(allocations)


def scoring_end(issue: datetime, *, has_remaining_service: bool) -> datetime:
    """End of 21 forecast dates; count today only if its service is not finished.

    The caller resolves this flag from the frozen dated profile, not quantities
    sold: an explicit zero-demand service period still counts as remaining service.
    """
    issue = _aware(issue)
    if type(has_remaining_service) is not bool:
        raise ValueError("Explicit remaining-service flag required")
    return datetime.combine(
        issue.date() + timedelta(days=21 if has_remaining_service else 22),
        time.min,
        SINGAPORE,
    )


def _finite_portions(value: Fraction) -> Decimal:
    """Keep terminating ratios exact; round recurring ratios down to 28 places.

    A finite Decimal cannot represent 1/3. The explicit fulfilment policy rounds
    only that constrained served quantity down; required demand remains unchanged.
    Resulting resource remainder/unmet demand stay visible and conserve exactly.
    """
    denominator = value.denominator
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    if denominator == 1:
        return _decimal(value)
    scale = 10**28
    return _decimal(Fraction(value.numerator * scale // value.denominator, scale))


def rollout_economics(inputs: RolloutInputs) -> EconomicRollout:
    """Calculate one common 21-date conditional path; no automatic continuation.

    Future routine purchases must be supplied by the continuation engine, not
    inferred as actual commitments. This entry point does not validate offers or
    certify candidates. Incomplete calculation returns no ledger/asset/service
    totals; movements/breaches may retain a diagnostic prefix only.
    """
    if type(inputs.work_limit) is not int or not 1 <= inputs.work_limit <= 1000000:
        raise ValueError("Explicit work_limit must be in [1,1000000]")
    work = _Work(inputs.work_limit)
    movements: list[ExpectedMovement] = []
    breaches: list[Breach] = []
    projection: MultiDayProjection | None = None
    warnings: set[Finding] = set()
    try:
        return _rollout(inputs, work, movements, breaches, warnings)
    except _Limit:
        return EconomicRollout(
            False,
            (Finding("SEARCH_LIMIT_REACHED", "economic_rollout"),),
            tuple(sorted(warnings)),
            None,
            None,
            None,
            tuple(movements),
            tuple(breaches),
            projection,
            work.used,
            _context(inputs),
        )


def _rollout(
    p: RolloutInputs,
    work: _Work,
    movements: list[ExpectedMovement],
    breaches: list[Breach],
    warnings: set[Finding],
) -> EconomicRollout:
    inv = p.inventory
    coverage = inv["coverage"]
    issue, known = _aware(coverage.issue_time), _aware(coverage.known_at)
    end, revision = _aware(p.horizon_end), coverage.captured_revision
    units = {i.id: i.unit for i in inv["ingredients"]}
    dishes = sorted(d.id for d in inv["menu_items"])
    findings: set[Finding] = set()
    if not coverage.complete:
        findings.add(Finding("INCOMPLETE_PROTECTED_COVERAGE", "coverage"))
    remaining_service = any(
        f.target_date == issue.date()
        and any(period.end > issue for period in f.profile)
        for f in inv["forecasts"]
    )
    if p.horizon_policy != HORIZON_POLICY or end != scoring_end(
        issue, has_remaining_service=remaining_service
    ):
        findings.add(Finding("UNSUPPORTED_ECONOMIC_HORIZON", "policy"))
    if p.fulfilment_policy != FULFILMENT_POLICY:
        findings.add(Finding("UNRESOLVED_FULFILMENT_POLICY", "policy"))
    if set(inv["assessment_end"]) != set(units) or any(
        _aware(value) != end for value in inv["assessment_end"].values()
    ):
        findings.add(Finding("ECONOMIC_ASSESSMENT_HORIZON_MISMATCH", "inventory"))
    if findings:
        return EconomicRollout(
            False,
            tuple(sorted(findings)),
            (),
            None,
            None,
            None,
            (),
            (),
            None,
            work.used,
            _context(p),
        )
    work.charge(
        len(inv["opening_lots"])
        + len(inv["supplies"])
        + len(inv["recipes"])
        + len(inv["forecasts"])
        + len(p.purchases)
        + 1
    )
    projection = project_multiday(**inv)
    # This common finite ledger can retain documented incoming terminal assets.
    # The existing projection's beyond-horizon warning is NOT erased or relabelled
    # complete; it is returned intact, separately from this economic calculation.
    for finding in projection.findings:
        if finding.code == "DELAYED_COMMITMENT_BEYOND_ASSESSMENT":
            warnings.add(finding)
        else:
            findings.add(finding)
    for row in projection.ingredients:
        if (
            row.verified_until != end
            or row.projection is None
            or not row.projection.complete
        ):
            findings.add(Finding("INCOMPLETE_ECONOMIC_FORECAST", row.ingredient_id))
    for source in (
        "assets",
        "service",
        "shipments",
        "valuation",
        "policy",
        "catalogue",
    ):
        findings.update(
            evidence_findings(source, p.evidence.get(source), known, revision)
        )
    if p.evidence.get("catalogue") != inv["evidence"].get("catalogue"):
        findings.add(Finding("ECONOMIC_CATALOGUE_MISMATCH", "catalogue"))
    buckets = sorted(
        (b for f in inv["forecasts"] for b in f.buckets if issue <= b.start < end),
        key=lambda b: b.start,
    )
    required_prices = {(b.start, d) for b in buckets for d in dishes}
    if set(p.dish_terms) - required_prices:
        raise ValueError("Unknown or out-of-horizon dish price")
    if set(p.dish_terms) != required_prices:
        findings.add(Finding("MISSING_DISH_ECONOMICS", "prices"))
    for key, terms in p.dish_terms.items():
        _quantity(terms.effective_net_price)
        _quantity(terms.noningredient_variable_cost)
        findings.update(evidence_findings(str(key), terms.evidence, known, revision))
    required_assets = {"opening:" + l.id for l in inv["opening_lots"]} | {
        "supply:" + s.delivery.id
        for s in inv["supplies"]
        if s.delivery.outstanding_quantity
    }
    if set(p.asset_terms) - required_assets:
        raise ValueError("Unknown asset valuation identity")
    if set(p.asset_terms) != required_assets:
        findings.add(Finding("MISSING_ASSET_VALUATION", "assets"))
    for key, terms in p.asset_terms.items():
        _quantity(terms.unit_cost)
        _quantity(terms.incremental_disposal_rate)
        findings.update(evidence_findings(key, terms.evidence, known, revision))
    resources: list[_Resource] = []
    for lot in inv["opening_lots"]:
        key = "opening:" + lot.id
        if key in p.asset_terms:
            terms = p.asset_terms[key]
            resources.append(
                _Resource(
                    key,
                    lot.id,
                    lot.ingredient_id,
                    lot.unit,
                    "OPENING",
                    _aware(lot.received_at),
                    _expiry(lot.expiry_date),
                    Fraction(lot.quantity),
                    terms.unit_cost,
                    terms.incremental_disposal_rate,
                    balance=Fraction(lot.quantity),
                    admitted=True,
                )
            )
    for supply in inv["supplies"]:
        d = supply.delivery
        if not d.outstanding_quantity:
            continue
        key = "supply:" + d.id
        findings.update(
            evidence_findings(key + ":expiry", supply.expiry_evidence, known, revision)
        )
        if supply.expiry_date is None or not supply.projected_lot_id:
            findings.add(Finding("MISSING_EXPECTED_EXPIRY_OR_LOT_ID", key))
        elif key in p.asset_terms:
            terms = p.asset_terms[key]
            if _expiry(supply.expiry_date) <= _aware(d.expected_at):
                raise ValueError("Incoming asset expires before expected arrival")
            resources.append(
                _Resource(
                    key,
                    supply.projected_lot_id,
                    d.ingredient_id,
                    units[d.ingredient_id],
                    "FIXED_COMMITMENT",
                    _aware(d.expected_at),
                    _expiry(supply.expiry_date),
                    Fraction(d.outstanding_quantity),
                    terms.unit_cost,
                    terms.incremental_disposal_rate,
                )
            )
    purchase_ids: set[str] = set()
    groups: dict[str, tuple[str, datetime]] = {}
    for purchase in p.purchases:
        a = purchase.addition
        for key in (a.opportunity_id, a.offer_id, a.supplier_id, a.shipment_group_id):
            _id(key)
        _quantity(a.quantity)
        _quantity(purchase.unit_price)
        _quantity(purchase.incremental_disposal_rate)
        if a.opportunity_id in purchase_ids or a.quantity == 0:
            raise ValueError("Duplicate or zero hypothetical purchase")
        purchase_ids.add(a.opportunity_id)
        if a.ingredient_id not in units or a.unit != units[a.ingredient_id]:
            raise ValueError("Hypothetical purchase ingredient/unit mismatch")
        if purchase.origin not in ("NEW_PURCHASE", "CONTINUATION"):
            raise ValueError("Invalid hypothetical purchase origin")
        if not issue <= _aware(a.ordered_at) < end or _aware(a.arrival_at) < _aware(
            a.ordered_at
        ):
            raise ValueError("Hypothetical order outside scoring horizon")
        if _aware(a.ordered_at) > _aware(a.latest_placement_at):
            raise ValueError("Hypothetical purchase misses placement deadline")
        if purchase.origin == "NEW_PURCHASE" and _aware(a.ordered_at) != issue:
            raise ValueError("Current action must be placed at the issue time")
        if purchase.origin == "CONTINUATION" and _aware(a.ordered_at) <= issue:
            raise ValueError("Continuation must follow the issue time")
        if _expiry(a.expiry_date) <= _aware(a.arrival_at):
            raise ValueError("Hypothetical supply expires before arrival")
        if any(b.start < a.arrival_at < b.end for b in buckets):
            findings.add(Finding("UNSUPPORTED_MID_BUCKET_ARRIVAL", a.opportunity_id))
        findings.update(
            evidence_findings(a.opportunity_id, purchase.evidence, known, revision)
        )
        group = (a.supplier_id, _aware(a.arrival_at))
        if a.shipment_group_id in groups and groups[a.shipment_group_id] != group:
            raise ValueError("Shipment group mixes suppliers or arrivals")
        groups[a.shipment_group_id] = group
        # Explicit projected identity, stable across input order and distinct from
        # real lot IDs. Shared FEFO policy remains unchanged in Backend code.
        key = "hypothetical:" + a.opportunity_id
        resources.append(
            _Resource(
                key,
                key,
                a.ingredient_id,
                a.unit,
                purchase.origin,
                _aware(a.arrival_at),
                _expiry(a.expiry_date),
                Fraction(a.quantity),
                purchase.unit_price,
                purchase.incremental_disposal_rate,
            )
        )
    if len({r.lot_id for r in resources}) != len(resources):
        raise ValueError("Actual/projected lot identity collision")
    fee_ids = [s.shipment_group_id for s in p.shipments]
    if len(set(fee_ids)) != len(fee_ids):
        raise ValueError("Duplicate hypothetical shipment charge")
    if set(fee_ids) != set(groups):
        findings.add(Finding("SHIPMENT_COVERAGE_MISMATCH", "fees"))
    for fee in p.shipments:
        if fee.shipment_group_id in groups and groups[fee.shipment_group_id] != (
            fee.supplier_id,
            _aware(fee.arrival_at),
        ):
            raise ValueError("Shipment charge disagrees with hypothetical supply")
    if findings:
        return EconomicRollout(
            False,
            tuple(sorted(findings)),
            tuple(sorted(warnings)),
            None,
            None,
            None,
            (),
            (),
            projection,
            work.used,
            _context(p),
        )
    usage = {
        dish: calculate_requirements(
            {dish: Decimal(1)},
            inv["menu_items"],
            inv["ingredients"],
            inv["recipes"],
            sparse=True,
        )
        for dish in dishes
    }
    windows = {w.ingredient_id: w.end for w in coverage.windows}
    resources.sort(key=lambda r: (r.expiry, r.arrival, r.lot_id))
    service: list[DishService] = []

    def totals() -> dict[str, Fraction]:
        return {
            i: sum((r.balance for r in resources if r.ingredient == i), Fraction(0))
            for i in units
        }

    def boundary(at: datetime) -> None:
        work.charge(len(resources) + 1)
        for r in resources:
            if not r.admitted and r.arrival <= at:
                r.balance = r.quantity
                r.admitted = True
                movements.append(
                    ExpectedMovement(
                        r.arrival,
                        r.key,
                        r.ingredient,
                        "EXPECTED_ARRIVAL",
                        _decimal(r.quantity),
                    )
                )
            if r.balance and r.expiry <= at:
                r.expired += r.balance
                movements.append(
                    ExpectedMovement(
                        r.expiry,
                        r.key,
                        r.ingredient,
                        "PROJECTED_EXPIRY",
                        _decimal(r.balance),
                    )
                )
                r.balance = Fraction(0)
        for i, q in totals().items():
            if q > Fraction(inv["storage"][i]):
                breaches.append(
                    Breach(
                        "STORAGE",
                        i,
                        at,
                        at,
                        _decimal(q),
                        inv["storage"][i],
                        "PROTECTED" if at < windows[i] else "ASSESSMENT",
                    )
                )

    # Every arrival and expiry is processed even during closed service periods.
    timeline = {issue, end, *(b.start for b in buckets), *(b.end for b in buckets)}
    timeline.update(r.arrival for r in resources if issue < r.arrival <= end)
    timeline.update(r.expiry for r in resources if issue < r.expiry <= end)
    by_start = {b.start: b for b in buckets}
    for at in sorted(timeline):
        boundary(at)
        bucket = by_start.get(at)
        if bucket is None:
            continue
        required_ingredients = calculate_requirements(
            bucket.expected_portions,
            inv["menu_items"],
            inv["ingredients"],
            inv["recipes"],
        )
        opening_available = totals()
        for dish in dishes:
            work.charge(len(resources) + len(units) + 1)
            required = bucket.expected_portions[dish]
            available = totals()
            possible = min(
                [
                    Fraction(required),
                    *(available[i] / Fraction(q) for i, q in usage[dish].items() if q),
                ]
            )
            served = _finite_portions(possible)
            if Fraction(served) != possible:
                warnings.add(Finding("FRACTIONAL_REPRESENTATION_RESIDUAL", dish))
            consumed = calculate_requirements(
                {dish: served},
                inv["menu_items"],
                inv["ingredients"],
                inv["recipes"],
                sparse=True,
            )
            for i, q in consumed.items():
                allocations = _take(resources, i, Fraction(q))
                assert sum((q for _, q in allocations), Fraction(0)) == Fraction(q)
                movements.extend(
                    ExpectedMovement(
                        at, r.key, i, "PROJECTED_USE", _decimal(taken), dish
                    )
                    for r, taken in allocations
                )
            price = p.dish_terms[at, dish]
            service.append(
                DishService(
                    at,
                    bucket.end,
                    dish,
                    required,
                    served,
                    price.effective_net_price,
                    price.noningredient_variable_cost,
                )
            )
        # An unserved dish does not mean every ingredient in its recipe is
        # physically short. Keep dish unmet demand in service; physical shortage
        # compares raw recipe demand with usable stock at this bucket's opening.
        for i, needed in required_ingredients.items():
            shortfall = _decimal(
                max(Fraction(0), Fraction(needed) - opening_available[i])
            )
            if shortfall:
                breaches.append(
                    Breach(
                        "SHORTAGE",
                        i,
                        at,
                        bucket.end,
                        shortfall,
                        ZERO,
                        "PROTECTED" if at < windows[i] else "ASSESSMENT",
                    )
                )
        for i, q in totals().items():
            if at < windows[i] and q < Fraction(inv["safety"][i]):
                breaches.append(
                    Breach(
                        "SAFETY",
                        i,
                        at,
                        bucket.end,
                        _decimal(q),
                        inv["safety"][i],
                        "PROTECTED",
                    )
                )
    assets = tuple(
        AssetFlow(
            r.key,
            r.ingredient,
            r.unit,
            r.origin,
            _decimal(r.quantity),
            _decimal(r.allocated),
            _decimal(r.expired),
            _decimal(r.balance),
            ZERO if r.admitted else _decimal(r.quantity),
            r.cost,
            r.disposal,
        )
        for r in sorted(resources, key=lambda r: r.key)
    )
    ledger = score_ledger(
        assets,
        service,
        p.shipments,
        inv["ingredients"],
        inv["menu_items"],
        asset_manifest=[r.reference for r in assets],
        service_manifest=[(b.start, b.end, d) for b in buckets for d in dishes],
        shipment_manifest=sorted(groups),
        start=issue,
        end=end,
        known_at=known,
        captured_revision=revision,
        evidence=p.evidence,
        ledger_policy=p.ledger_policy,
        terminal_policy=p.terminal_policy,
        money_policy=p.money_policy,
        provenance="PROJECTED",
    )
    return EconomicRollout(
        ledger.complete,
        ledger.findings,
        tuple(sorted(warnings)),
        ledger if ledger.complete else None,
        assets if ledger.complete else None,
        tuple(service) if ledger.complete else None,
        tuple(movements),
        tuple(breaches),
        projection,
        work.used,
        _context(p),
    )

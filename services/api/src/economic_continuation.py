"""Bounded greedy routine replenishment of one frozen 21-date forecast.

Hypothetical future additions remain separate from the current recommendation.
The policy considers single-offer pack quantities at each ingredient occasion;
failure may miss a feasible split and is explicitly a heuristic shortage.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from math import isfinite
from time import monotonic

from src.contingency import _op_violations
from src.coverage import evidence_findings
from src.economic_rollout import (
    EconomicRollout,
    RolloutInputs,
    _Limit,
    _Resource,
    _take,
    _Work,
    rollout_economics,
)
from src.economic_supply import (
    EconomicSupply,
    supply_findings,
    validate_economic_supply,
)
from src.forecasting import SINGAPORE
from src.inventory_projection import Finding, SourceEvidence, _aware, _expiry, _quantity
from src.procurement import PurchaseCandidate, PurchaseLine, _decimal, _q
from src.requirements import calculate_requirements

CONTINUATION_POLICY = "GREEDY_ROUTINE_CONTINUATION_V1"


@dataclass(frozen=True)
class RoutineOccasion:
    ingredient_id: str
    ordered_at: datetime
    # Explicit next routine receipt boundary; only this future closure is capped.
    protect_until: datetime
    opportunity_ids: tuple[str, ...] | None
    evidence: SourceEvidence | None


@dataclass(frozen=True)
class ContinuationInputs:
    rollout: RolloutInputs
    supply: EconomicSupply
    decision_times: Mapping[str, time]
    occasions: Sequence[RoutineOccasion] | None
    # Total NEW current + hypothetical future cash, excluding fixed commitments.
    incremental_budget: Decimal | None
    policy: str | None
    evidence: SourceEvidence | None
    work_limit: int
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class RoutineDecision:
    ingredient_id: str
    ordered_at: datetime
    protected_end: datetime
    line: PurchaseLine | None
    status: str
    tested: int


@dataclass(frozen=True)
class ContinuationResult:
    complete: bool
    findings: tuple[Finding, ...]
    limitations: tuple[Finding, ...]
    # Never actionable; these lines describe a scoring-only policy trajectory.
    future_lines: tuple[PurchaseLine, ...] | None
    decisions: tuple[RoutineDecision, ...]
    rollout: EconomicRollout | None
    work_used: int
    actionable: bool = False


def continuation_findings(p: ContinuationInputs) -> tuple[Finding, ...]:
    c = p.rollout.inventory["coverage"]
    issue, end, known = map(_aware, (c.issue_time, p.rollout.horizon_end, c.known_at))
    if end - issue > timedelta(days=31):
        return (Finding("UNSUPPORTED_SCOPE", "continuation horizon"),)
    findings = set(supply_findings(p.supply))
    if p.timeout_seconds is None:
        findings.add(Finding("MISSING_HOST_DEADLINE", "continuation"))
    elif (
        isinstance(p.timeout_seconds, bool)
        or not isfinite(p.timeout_seconds)
        or not 0 < p.timeout_seconds <= 3600
    ):
        raise ValueError("Positive finite host timeout at most3600 seconds required")
    if (issue, end, known, c.captured_revision) != (
        _aware(p.supply.issue_time),
        _aware(p.supply.horizon_end),
        _aware(p.supply.known_at),
        p.supply.captured_revision,
    ):
        raise ValueError("Supply and rollout clocks/revision disagree")
    ingredients = {i.id: i for i in p.rollout.inventory["ingredients"]}
    if ingredients != {i.id: i for i in p.supply.ingredients}:
        raise ValueError("Supply and rollout catalogue disagree")
    if p.rollout.purchases or p.rollout.shipments:
        raise ValueError("Continuation base must contain fixed inventory only")
    if p.policy != CONTINUATION_POLICY:
        findings.add(Finding("MISSING_OR_UNSUPPORTED_POLICY", "continuation"))
    findings.update(
        evidence_findings("continuation", p.evidence, known, c.captured_revision)
    )
    if p.incremental_budget is None:
        findings.add(Finding("MISSING_REQUIRED_DATA", "incremental_budget"))
    else:
        _quantity(p.incremental_budget)
    if set(p.decision_times) - set(ingredients):
        raise ValueError("Unknown ingredient decision time")
    if set(p.decision_times) != set(ingredients) or p.occasions is None:
        findings.add(Finding("MISSING_ROUTINE_CALENDAR", "continuation"))
        return tuple(sorted(findings))
    expected = set()
    day = issue.date()
    while day <= end.date():
        for i, ingredient in ingredients.items():
            t = p.decision_times[i]
            if not isinstance(t, time) or t.tzinfo is not None:
                raise ValueError("Explicit Singapore local decision time required")
            at = datetime.combine(day, t, SINGAPORE)
            days = (day - ingredient.starting_date).days
            if issue < at < end and days >= 0 and days % ingredient.interval_days == 0:
                expected.add((i, at))
        day += timedelta(days=1)
    actual = {(o.ingredient_id, _aware(o.ordered_at)) for o in p.occasions}
    if len(actual) != len(p.occasions):
        raise ValueError("Duplicate routine occasion")
    if actual - expected:
        raise ValueError("Routine occasion is not on the anchored ingredient calendar")
    if actual != expected:
        findings.add(Finding("INCOMPLETE_ROUTINE_CALENDAR", "continuation"))
    ops = {o.id: o for o in p.supply.opportunities or ()}
    offers = {o.id: o for o in p.supply.offers}
    assigned: set[str] = set()
    buckets = [b for f in p.rollout.inventory["forecasts"] for b in f.buckets]
    for o in p.occasions:
        at, finish = _aware(o.ordered_at), min(_aware(o.protect_until), end)
        if finish <= at:
            raise ValueError("Future protection must follow its decision")
        if any(b.start < at < b.end or b.start < finish < b.end for b in buckets):
            findings.add(Finding("UNSUPPORTED_BUCKET_CUTOFF", o.ingredient_id))
        findings.update(
            evidence_findings(
                o.ingredient_id + "@" + at.isoformat(),
                o.evidence,
                known,
                c.captured_revision,
            )
        )
        if o.opportunity_ids is None:
            findings.add(Finding("MISSING_ROUTINE_DOMAIN", o.ingredient_id))
            continue
        if len(set(o.opportunity_ids)) != len(o.opportunity_ids):
            raise ValueError("Duplicate routine opportunity")
        suppliers: dict[str, int] = {}
        for key in o.opportunity_ids:
            if key not in ops or key in assigned:
                raise ValueError("Unknown or multiply assigned routine opportunity")
            assigned.add(key)
            op = ops[key]
            offer = offers[op.offer_id]
            if any(b.start < _aware(op.arrival_at) < b.end for b in buckets):
                findings.add(Finding("UNSUPPORTED_MID_BUCKET_ARRIVAL", op.id))
            if _aware(op.ordered_at) != at or offer.ingredient_id != o.ingredient_id:
                raise ValueError("Routine opportunity does not match occasion")
            suppliers[offer.supplier_id] = suppliers.get(offer.supplier_id, 0) + 1
        if len(suppliers) > 3 or any(n > 2 for n in suppliers.values()):
            findings.add(Finding("UNSUPPORTED_ROUTINE_DOMAIN", o.ingredient_id))
    if assigned != {o.id for o in ops.values() if _aware(o.ordered_at) > issue}:
        findings.add(Finding("ROUTINE_DOMAIN_COVERAGE_MISMATCH", "continuation"))
    if not findings:
        windows = {w.id: w for w in p.supply.windows or ()}
        # Protection is bounded by the next *feasible* ordinary receipt, not an
        # arbitrary short caller-supplied interval. The last future window alone
        # closes at score_end; it never shortens actual current protection.
        for occasion in p.occasions:
            future_arrivals = [
                _aware(op.arrival_at)
                for later in p.occasions
                if later.ingredient_id == occasion.ingredient_id
                and _aware(later.ordered_at) > _aware(occasion.ordered_at)
                for key in later.opportunity_ids or ()
                if not _op_violations(op := ops[key], offers[op.offer_id])
                and (
                    Fraction(windows[p.supply.capacity_window[key]].available_quantity)
                    // Fraction(_q(offers[op.offer_id], "pack_size"))
                )
                * Fraction(_q(offers[op.offer_id], "pack_size"))
                >= max(
                    _q(offers[op.offer_id], "moq"), _q(offers[op.offer_id], "pack_size")
                )
            ]
            boundary = min([end, *future_arrivals])
            if min(_aware(occasion.protect_until), end) != boundary:
                findings.add(
                    Finding(
                        "ROUTINE_PROTECTION_MISMATCH",
                        occasion.ingredient_id + "@" + occasion.ordered_at.isoformat(),
                    )
                )
    return tuple(sorted(findings))


def _resources_at(
    p: RolloutInputs, trajectory: EconomicRollout, at: datetime
) -> list[_Resource]:
    """Private projected state just before service at a routine decision.

    Use the already calculated coupled-dish prefix, not a new observed replayer.
    Fixed quantities are outstanding only; receipts already belong to opening.
    """
    resources = []
    for lot in p.inventory["opening_lots"]:
        resources.append(
            _Resource(
                "opening:" + lot.id,
                lot.id,
                lot.ingredient_id,
                lot.unit,
                "OPENING",
                _aware(lot.received_at),
                _expiry(lot.expiry_date),
                Fraction(lot.quantity),
                Decimal(0),
                Decimal(0),
            )
        )
    units = {i.id: i.unit for i in p.inventory["ingredients"]}
    for s in p.inventory["supplies"]:
        d = s.delivery
        if d.outstanding_quantity:
            assert s.expiry_date is not None and s.projected_lot_id is not None
            resources.append(
                _Resource(
                    "supply:" + d.id,
                    s.projected_lot_id,
                    d.ingredient_id,
                    units[d.ingredient_id],
                    "FIXED_COMMITMENT",
                    _aware(d.expected_at),
                    _expiry(s.expiry_date),
                    Fraction(d.outstanding_quantity),
                    Decimal(0),
                    Decimal(0),
                )
            )
    for purchase in p.purchases:
        a = purchase.addition
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
    by_key = {r.key: r for r in resources}
    for r in resources:
        if r.arrival <= at:
            r.admitted = True
            r.balance = r.quantity
    for movement in trajectory.movements:
        if movement.at < at and movement.kind in ("PROJECTED_USE", "PROJECTED_EXPIRY"):
            by_key[movement.resource].balance -= Fraction(movement.quantity)
    for r in resources:
        if r.expiry <= at:
            r.balance = Fraction(0)
    return resources


def _protection_findings(
    p: RolloutInputs,
    trajectory: EconomicRollout,
    occasion: RoutineOccasion,
    work: _Work,
) -> tuple[Finding, ...]:
    """Check raw forecast ingredient needs, not sales limited by other ingredients.

    The coupled prefix is fixed. Forward FEFO uses the shared depletion helper;
    requested recipe demand is never reduced because another dish input is absent.
    """
    at = _aware(occasion.ordered_at)
    end = min(_aware(occasion.protect_until), _aware(p.horizon_end))
    ingredient = occasion.ingredient_id
    resources = [
        r for r in _resources_at(p, trajectory, at) if r.ingredient == ingredient
    ]
    buckets = {
        b.start: b
        for f in p.inventory["forecasts"]
        for b in f.buckets
        if at <= b.start < end
    }
    timeline = {at, *(buckets.keys()), *(b.end for b in buckets.values())}
    timeline.update(r.arrival for r in resources if at <= r.arrival < end)
    timeline.update(r.expiry for r in resources if at <= r.expiry < end)
    safety = Fraction(p.inventory["safety"][ingredient])
    storage = Fraction(p.inventory["storage"][ingredient])
    for moment in sorted(timeline):
        work.charge(len(resources) + 1)
        for r in resources:
            if not r.admitted and r.arrival <= moment:
                r.balance, r.admitted = r.quantity, True
            if r.expiry <= moment:
                r.balance = Fraction(0)
        if sum((r.balance for r in resources), Fraction(0)) > storage:
            return (Finding("STORAGE", ingredient + "@" + moment.isoformat()),)
        bucket = buckets.get(moment)
        if bucket is None:
            continue
        needs = calculate_requirements(
            bucket.expected_portions,
            p.inventory["menu_items"],
            p.inventory["ingredients"],
            p.inventory["recipes"],
        )
        requested = Fraction(needs[ingredient])
        allocated = sum(
            (q for _, q in _take(resources, ingredient, requested)), Fraction(0)
        )
        if allocated != requested:
            return (Finding("SHORTAGE", ingredient + "@" + moment.isoformat()),)
        if sum((r.balance for r in resources), Fraction(0)) < safety:
            return (Finding("SAFETY", ingredient + "@" + moment.isoformat()),)
    return ()


def _can_protect(
    p: RolloutInputs,
    trajectory: EconomicRollout,
    occasion: RoutineOccasion,
    work: _Work,
) -> bool:
    return not _protection_findings(p, trajectory, occasion, work)


def continue_routine(
    p: ContinuationInputs, current: PurchaseCandidate
) -> ContinuationResult:
    """One deterministic single-offer greedy choice per anchored future occasion.

    Missing inputs/work exhaustion are incomplete, with no cost or future lines.
    A modelled greedy shortage remains a fully scored risk, not supplier proof.
    This function neither selects the current action nor certifies its feasibility.
    """
    if type(p.work_limit) is not int or not 1 <= p.work_limit <= 1000000:
        raise ValueError("Explicit continuation work_limit must be in [1,1000000]")
    started = monotonic()
    work = _Work(
        p.work_limit,
        deadline=started + p.timeout_seconds if p.timeout_seconds is not None else None,
    )
    decisions: list[RoutineDecision] = []
    limitations: set[Finding] = set()
    findings = continuation_findings(p)
    if findings:
        return ContinuationResult(False, findings, (), None, (), None, work.used)
    ops = {o.id: o for o in p.supply.opportunities or ()}
    offers = {o.id: o for o in p.supply.offers}
    windows = {w.id: w for w in p.supply.windows or ()}
    issue = _aware(p.supply.issue_time)
    if any(
        line.opportunity_id in ops
        and _aware(ops[line.opportunity_id].ordered_at) != issue
        for line in current.lines
    ):
        raise ValueError("Current action cannot smuggle in continuation lines")
    lines = list(current.lines)

    def resolve(candidate: PurchaseCandidate):
        work.charge(len(lines) + len(ops) + 1)
        return validate_economic_supply(p.supply, candidate)

    def run(inputs: RolloutInputs) -> EconomicRollout:
        work.charge()
        result = rollout_economics(
            replace(
                inputs,
                work_limit=min(inputs.work_limit, max(1, work.limit - work.used)),
            )
        )
        work.charge(result.work_used)
        if any(f.code == "SEARCH_LIMIT_REACHED" for f in result.findings):
            raise _Limit
        return result

    try:
        supply = resolve(current)
        if not supply.complete or not supply.feasible:
            return ContinuationResult(
                False,
                supply.findings + supply.violations,
                (),
                None,
                (),
                None,
                work.used,
            )
        assert supply.cash is not None and p.incremental_budget is not None
        if supply.cash.total > p.incremental_budget:
            return ContinuationResult(
                False,
                (Finding("CURRENT_BUDGET", "current"),),
                (),
                None,
                (),
                None,
                work.used,
            )
        active = replace(
            p.rollout, purchases=supply.purchases, shipments=supply.shipments
        )
        trajectory = run(active)
        if not trajectory.complete:
            return ContinuationResult(
                False, trajectory.findings, (), None, (), trajectory, work.used
            )
        for occasion in sorted(
            p.occasions or (), key=lambda o: (_aware(o.ordered_at), o.ingredient_id)
        ):
            work.charge()
            finish = min(_aware(occasion.protect_until), _aware(p.rollout.horizon_end))
            if _can_protect(active, trajectory, occasion, work):
                decisions.append(
                    RoutineDecision(
                        occasion.ingredient_id,
                        occasion.ordered_at,
                        finish,
                        None,
                        "NO_PURCHASE_NEEDED",
                        0,
                    )
                )
                continue
            tested = 0
            choices: list[tuple[Fraction, str, Decimal, PurchaseLine]] = []
            used = dict(supply.capacity_used)
            for op_id in sorted(occasion.opportunity_ids or ()):
                op = ops[op_id]
                offer = offers[op.offer_id]
                if _op_violations(op, offer):
                    continue
                window = p.supply.capacity_window[op_id]
                remaining = Fraction(windows[window].available_quantity) - Fraction(
                    used.get(window, Decimal(0))
                )
                pack = Fraction(_q(offer, "pack_size"))
                for count in range(1, int(remaining // pack) + 1):
                    work.charge()
                    quantity = _decimal(count * pack)
                    if quantity < _q(offer, "moq"):
                        continue
                    line = PurchaseLine(
                        op_id,
                        quantity,
                        next(
                            i.unit
                            for i in p.supply.ingredients
                            if i.id == occasion.ingredient_id
                        ),
                    )
                    tested += 1
                    trial = resolve(PurchaseCandidate((*lines, line)))
                    assert trial.cash is not None
                    if not trial.feasible or trial.cash.total > p.incremental_budget:
                        continue
                    trial_inputs = replace(
                        p.rollout, purchases=trial.purchases, shipments=trial.shipments
                    )
                    # Future additions cannot alter the already verified prefix.
                    if _can_protect(trial_inputs, trajectory, occasion, work):
                        assert supply.cash is not None
                        choices.append(
                            (
                                Fraction(trial.cash.total)
                                - Fraction(supply.cash.total),
                                op_id,
                                quantity,
                                line,
                            )
                        )
                        break  # First feasible pack for this offer is cheapest (nonnegative prices).
            if choices:
                line = min(choices, key=lambda row: row[:3])[3]
                lines.append(line)
                supply = resolve(PurchaseCandidate(tuple(lines)))
                active = replace(
                    p.rollout, purchases=supply.purchases, shipments=supply.shipments
                )
                trajectory = run(active)
                if not trajectory.complete:
                    return ContinuationResult(
                        False,
                        trajectory.findings,
                        tuple(sorted(limitations)),
                        None,
                        tuple(decisions),
                        trajectory,
                        work.used,
                    )
                status = "HYPOTHETICAL_PURCHASE"
            else:
                line = None
                status = "CONTINUATION_HEURISTIC_SHORTAGE"
                limitations.add(
                    Finding(
                        status,
                        occasion.ingredient_id + "@" + occasion.ordered_at.isoformat(),
                    )
                )
            decisions.append(
                RoutineDecision(
                    occasion.ingredient_id,
                    occasion.ordered_at,
                    finish,
                    line,
                    status,
                    tested,
                )
            )
        future = tuple(
            line
            for line in lines
            if _aware(ops[line.opportunity_id].ordered_at) > issue
        )
        return ContinuationResult(
            True,
            (),
            tuple(sorted(limitations)),
            future,
            tuple(decisions),
            trajectory,
            work.used,
        )
    except _Limit:
        return ContinuationResult(
            False,
            (Finding("SEARCH_LIMIT_REACHED", "continuation"),),
            tuple(sorted(limitations)),
            None,
            tuple(decisions),
            None,
            work.used,
        )

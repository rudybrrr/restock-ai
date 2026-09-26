"""Finite current-action economic search and independently callable validation.

Full enumeration is deliberately limited to small explicit domains. A work/score
cap never certifies an incumbent; ordinary future replenishment remains the same
frozen greedy policy for every current action and the diagnostic no-action path.
No persistence, approval, external order placement or runtime adapter is provided.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import product
from math import isfinite, prod
from time import monotonic

from src.economic_continuation import (
    ContinuationInputs,
    ContinuationResult,
    RoutineOccasion,
    _protection_findings,
    continuation_findings,
    continue_routine,
)
from src.economic_ledger import EconomicComponents
from src.economic_rollout import (
    EconomicRollout,
    RolloutContext,
    _context,
    _Limit,
    _Work,
    rollout_economics,
)
from src.economic_supply import validate_economic_supply
from src.inventory_projection import Finding, SourceEvidence, _aware
from src.procurement import PurchaseCandidate, PurchaseLine, _decimal, _q

SEARCH_POLICY = "EXHAUSTIVE_CURRENT_GREEDY_ROUTINE_V1"
OBJECTIVE_POLICY = "PROJECTED_OPERATING_COST_V2"
TIE_POLICY = "ECONOMIC_CENTS_WASTE_CASH_SHIPMENTS_SUPPLIERS_IDS_V1"


@dataclass(frozen=True)
class EconomicSearchInputs:
    continuation: ContinuationInputs
    # Explicit current decision authorisation, separate from future routine scope.
    current_ingredient_manifest: Sequence[str] | None
    search_policy: str | None
    objective_policy: str | None
    tie_policy: str | None
    work_limit: int
    # v2's maximum fully scored finalists, including no-action.
    score_limit: int
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class EconomicCandidate:
    purchase: PurchaseCandidate
    claimed_future_lines: tuple[PurchaseLine, ...] | None = None
    claimed_components: EconomicComponents | None = None


@dataclass(frozen=True)
class EconomicContext:
    """Evidence declarations, not proof of persisted/source-selected authority.

    Backend must preserve/hash the complete request. References here prevent an
    incomplete numerical result from losing its clocks, policies or source scope.
    """

    rollout: RolloutContext
    policies: tuple[tuple[str, str | None], ...]
    current_ingredients: tuple[str, ...] | None
    sources: tuple[tuple[str, SourceEvidence | None], ...]
    limits: tuple[tuple[str, str], ...]


def _economic_context(p: EconomicSearchInputs) -> EconomicContext:
    c = p.continuation
    supply = c.supply
    sources = {"continuation": c.evidence}
    sources.update(("supply:" + k, v) for k, v in supply.evidence.items())
    sources.update(
        ("offer:" + k, supply.offer_evidence.get(k))
        for k in sorted(o.id for o in supply.offers)
    )
    sources.update(("window:" + w.id, w.evidence) for w in supply.windows or ())
    sources.update(
        (
            "occasion:" + o.ingredient_id + "@" + _aware(o.ordered_at).isoformat(),
            o.evidence,
        )
        for o in c.occasions or ()
    )
    return EconomicContext(
        _context(c.rollout),
        (
            ("search", p.search_policy),
            ("objective", p.objective_policy),
            ("tie", p.tie_policy),
            ("continuation", c.policy),
            ("supply", supply.supply_policy),
            ("fee", supply.fee_policy),
            ("reliability", supply.reliability_policy),
        ),
        None
        if p.current_ingredient_manifest is None
        else tuple(sorted(p.current_ingredient_manifest)),
        tuple(sorted(sources.items())),
        (
            ("search_work", str(p.work_limit)),
            ("score_limit", str(p.score_limit)),
            ("search_timeout_seconds", str(p.timeout_seconds)),
            ("continuation_work", str(c.work_limit)),
            ("continuation_timeout_seconds", str(c.timeout_seconds)),
            ("incremental_budget", str(c.incremental_budget)),
        ),
    )


@dataclass(frozen=True)
class EconomicValidation:
    complete: bool
    feasible: bool | None
    findings: tuple[Finding, ...]
    violations: tuple[Finding, ...]
    current_projection: EconomicRollout | None
    continuation: ContinuationResult | None
    work_used: int
    # Public entry points always attach context, including incomplete results.
    context: EconomicContext | None = None


@dataclass(frozen=True)
class EconomicSearchResult:
    status: str
    reason: str | None
    search_complete: bool
    optimal_in_domain: bool
    candidate: EconomicCandidate | None
    validation: EconomicValidation | None
    no_action: ContinuationResult | None
    domain_size: int | None
    evaluated: int
    scored: int
    work_used: int
    findings: tuple[Finding, ...]
    rejection_counts: tuple[tuple[str, int], ...]
    diagnostic_incumbent: EconomicCandidate | None
    optimality_scope: str = "Declared current-action domain under fixed greedy continuation; not global future-order optimality"
    context: EconomicContext | None = None


def search_findings(p: EconomicSearchInputs) -> tuple[Finding, ...]:
    if type(p.work_limit) is not int or not 1 <= p.work_limit <= 1000000:
        raise ValueError("Explicit search work_limit must be in [1,1000000]")
    if type(p.score_limit) is not int or not 1 <= p.score_limit <= 33:
        raise ValueError("Score limit must include no-action and be in [1,33]")
    findings = set(continuation_findings(p.continuation))
    if p.timeout_seconds is None:
        findings.add(Finding("MISSING_HOST_DEADLINE", "search"))
    elif (
        isinstance(p.timeout_seconds, bool)
        or not isfinite(p.timeout_seconds)
        or not 0 < p.timeout_seconds <= 3600
    ):
        raise ValueError("Positive finite host timeout at most3600 seconds required")
    for name, actual, expected in (
        ("search", p.search_policy, SEARCH_POLICY),
        ("objective", p.objective_policy, OBJECTIVE_POLICY),
        ("tie", p.tie_policy, TIE_POLICY),
    ):
        if actual != expected:
            findings.add(Finding("MISSING_OR_UNSUPPORTED_POLICY", name))
    ingredients = {i.id for i in p.continuation.supply.ingredients}
    if p.current_ingredient_manifest is None:
        findings.add(Finding("MISSING_CURRENT_AUTHORIZATION", "ingredients"))
    elif (
        len(set(p.current_ingredient_manifest)) != len(p.current_ingredient_manifest)
        or set(p.current_ingredient_manifest) - ingredients
    ):
        raise ValueError("Duplicate or unknown current ingredient")
    else:
        supply = p.continuation.supply
        offers = {o.id: o for o in supply.offers}
        counts: dict[tuple[str, str], int] = {}
        for op in supply.opportunities or ():
            if _aware(op.ordered_at) != _aware(supply.issue_time):
                continue
            offer = offers[op.offer_id]
            if offer.ingredient_id not in p.current_ingredient_manifest:
                raise ValueError(
                    "Current opportunity is outside authorised ingredient scope"
                )
            key = (offer.ingredient_id, offer.supplier_id)
            counts[key] = counts.get(key, 0) + 1
        if any(n > 2 for n in counts.values()) or any(
            sum(key[0] == i for key in counts) > 3 for i in ingredients
        ):
            findings.add(Finding("UNSUPPORTED_CURRENT_DOMAIN", "supplier/slot limits"))
    return tuple(sorted(findings))


def validate_economic_candidate(
    p: EconomicSearchInputs, candidate: EconomicCandidate
) -> EconomicValidation:
    """Independently assess a supplied current action and retain input provenance."""
    return replace(
        _validate_economic_candidate(p, candidate), context=_economic_context(p)
    )


def _validate_economic_candidate(
    p: EconomicSearchInputs, candidate: EconomicCandidate
) -> EconomicValidation:
    """Recompute terms, current protection and the ledger; never calls search.

    The continuation generator is the deterministic evaluator policy, not another
    current-action optimisation. Supplied future-line/cost claims are compared with
    its recomputed trajectory. Current protection is checked BEFORE continuation,
    so a future hypothetical purchase cannot certify an insufficient current plan.
    """
    started = monotonic()
    findings = search_findings(p)
    if findings:
        return EconomicValidation(False, None, findings, (), None, None, 0)
    assert p.timeout_seconds is not None and p.continuation.timeout_seconds is not None
    deadline = started + p.timeout_seconds
    supply = p.continuation.supply
    ops = {o.id: o for o in supply.opportunities or ()}
    violations = set()
    for line in candidate.purchase.lines:
        if line.opportunity_id in ops and _aware(
            ops[line.opportunity_id].ordered_at
        ) != _aware(supply.issue_time):
            violations.add(
                Finding("FUTURE_LINE_IN_CURRENT_ACTION", line.opportunity_id)
            )
    terms = validate_economic_supply(supply, candidate.purchase)
    violations.update(terms.violations)
    if not terms.complete:
        return EconomicValidation(False, None, terms.findings, (), None, None, 1)
    assert terms.cash is not None and p.continuation.incremental_budget is not None
    if terms.cash.total > p.continuation.incremental_budget:
        violations.add(Finding("BUDGET", "current"))
    if violations:
        return EconomicValidation(
            True, False, (), tuple(sorted(violations)), None, None, 1
        )
    base = p.continuation.rollout
    current = rollout_economics(
        replace(
            base,
            purchases=terms.purchases,
            shipments=terms.shipments,
            work_limit=min(base.work_limit, p.work_limit),
        )
    )
    used = current.work_used
    if not current.complete:
        return EconomicValidation(
            False, None, current.findings, (), current, None, used
        )
    work = _Work(p.work_limit, used, deadline)
    current_inputs = replace(base, purchases=terms.purchases, shipments=terms.shipments)
    try:
        for window in base.inventory["coverage"].windows:
            violations.update(
                _protection_findings(
                    current_inputs,
                    current,
                    RoutineOccasion(
                        window.ingredient_id, supply.issue_time, window.end, (), None
                    ),
                    work,
                )
            )
    except _Limit:
        return EconomicValidation(
            False,
            None,
            (Finding("SEARCH_LIMIT_REACHED", "protection"),),
            (),
            current,
            None,
            work.used,
        )
    used = work.used
    if violations:
        return EconomicValidation(
            True, False, (), tuple(sorted(violations)), current, None, used
        )
    if used >= p.work_limit:
        return EconomicValidation(
            False,
            None,
            (Finding("SEARCH_LIMIT_REACHED", "validation"),),
            (),
            current,
            None,
            used,
        )
    result = continue_routine(
        replace(
            p.continuation,
            work_limit=min(p.continuation.work_limit, p.work_limit - used),
            timeout_seconds=min(
                p.continuation.timeout_seconds, max(1e-9, deadline - monotonic())
            ),
        ),
        candidate.purchase,
    )
    used += result.work_used
    if not result.complete:
        return EconomicValidation(
            False, None, result.findings, (), current, result, used
        )
    assert result.rollout and result.rollout.ledger and result.rollout.ledger.components
    for breach in result.rollout.breaches:
        if breach.kind == "STORAGE":
            violations.add(
                Finding(
                    breach.kind, breach.ingredient_id + "@" + breach.start.isoformat()
                )
            )
    if (
        candidate.claimed_future_lines is not None
        and candidate.claimed_future_lines != result.future_lines
    ):
        violations.add(Finding("CONTINUATION_CLAIM_MISMATCH", "candidate"))
    if (
        candidate.claimed_components is not None
        and candidate.claimed_components != result.rollout.ledger.components
    ):
        violations.add(Finding("ECONOMIC_CLAIM_MISMATCH", "candidate"))
    return EconomicValidation(
        True, not violations, (), tuple(sorted(violations)), current, result, used
    )


def _rank(
    candidate: EconomicCandidate,
    validation: EconomicValidation,
    p: EconomicSearchInputs,
):
    result = validation.continuation
    assert (
        result
        and result.rollout
        and result.rollout.ledger
        and result.rollout.ledger.components
    )
    components = result.rollout.ledger.components
    terms = validate_economic_supply(p.continuation.supply, candidate.purchase)
    assert terms.immediate_cash is not None
    return (
        components.primary_sgd,
        components.expired_book,
        terms.immediate_cash.total,
        len(terms.shipments),
        len({x.addition.supplier_id for x in terms.purchases}),
        tuple(
            sorted(
                (
                    x.addition.supplier_id,
                    x.addition.ingredient_id,
                    x.addition.ordered_at,
                    x.addition.arrival_at,
                    x.addition.offer_id,
                    x.addition.opportunity_id,
                    x.addition.quantity,
                )
                for x in terms.purchases
            )
        ),
    )


def search_economics(p: EconomicSearchInputs) -> EconomicSearchResult:
    """Search the declared domain; retain evidence even when no result is actionable."""
    return replace(_search_economics(p), context=_economic_context(p))


def _search_economics(p: EconomicSearchInputs) -> EconomicSearchResult:
    """Enumerate every pack count allowed by explicit current NEW capacity.

    No quantity pruning or omitted alternative is labelled proven infeasible.
    Exceeding work/fully-scored limits returns INCOMPLETE, with an incumbent only
    as diagnostic evidence. Infeasibility is restricted to this finite domain.
    """
    started = monotonic()
    findings = search_findings(p)
    if findings:
        return EconomicSearchResult(
            "INCOMPLETE",
            "INCOMPLETE_DATA",
            False,
            False,
            None,
            None,
            None,
            None,
            0,
            0,
            0,
            findings,
            (),
            None,
        )
    assert p.timeout_seconds is not None and p.continuation.timeout_seconds is not None
    deadline = started + p.timeout_seconds
    supply = p.continuation.supply
    offers = {o.id: o for o in supply.offers}
    windows = {w.id: w for w in supply.windows or ()}
    ops = sorted(
        (
            o
            for o in supply.opportunities or ()
            if _aware(o.ordered_at) == _aware(supply.issue_time)
        ),
        key=lambda o: o.id,
    )
    bounds = [
        int(
            Fraction(windows[supply.capacity_window[o.id]].available_quantity)
            // Fraction(_q(offers[o.offer_id], "pack_size"))
        )
        for o in ops
    ]
    size = prod(n + 1 for n in bounds)
    used, evaluated, scored = 0, 0, 0
    best: EconomicCandidate | None = None
    best_validation: EconomicValidation | None = None
    no_action: ContinuationResult | None = None
    rejected: dict[str, int] = {}

    def incomplete(
        reason: str, extra: tuple[Finding, ...] = ()
    ) -> EconomicSearchResult:
        return EconomicSearchResult(
            "INCOMPLETE",
            reason,
            False,
            False,
            None,
            None,
            no_action,
            size,
            evaluated,
            scored,
            used,
            extra or (Finding(reason, "economic_search"),),
            tuple(sorted(rejected.items())),
            best,
        )

    # itertools.product materialises its ranges. Do not allocate an enormous
    # domain that cannot possibly fit even one charged unit per candidate.
    if size > p.work_limit:
        return incomplete("SEARCH_LIMIT_REACHED")

    # Diagnostic no-action intentionally ignores current hard feasibility but uses
    # precisely the same ordinary continuation, frozen demand and economic policy.
    no_action = continue_routine(
        replace(
            p.continuation,
            work_limit=min(p.continuation.work_limit, p.work_limit),
            timeout_seconds=min(
                p.continuation.timeout_seconds, max(1e-9, deadline - monotonic())
            ),
        ),
        PurchaseCandidate(()),
    )
    used += no_action.work_used
    if not no_action.complete:
        reason = (
            "SEARCH_LIMIT_REACHED"
            if any(f.code == "SEARCH_LIMIT_REACHED" for f in no_action.findings)
            else "INCOMPLETE_DATA"
        )
        return incomplete(reason, no_action.findings)
    scored += 1
    units = {i.id: i.unit for i in supply.ingredients}
    for counts in product(*(range(n + 1) for n in bounds)):
        if used >= p.work_limit or scored >= p.score_limit or monotonic() >= deadline:
            return incomplete("SEARCH_LIMIT_REACHED")
        lines = tuple(
            PurchaseLine(
                op.id,
                _decimal(count * Fraction(_q(offers[op.offer_id], "pack_size"))),
                units[offers[op.offer_id].ingredient_id],
            )
            for op, count in zip(ops, counts, strict=True)
            if count
        )
        candidate = EconomicCandidate(PurchaseCandidate(lines))
        validation = validate_economic_candidate(
            replace(
                p,
                work_limit=p.work_limit - used,
                timeout_seconds=max(1e-9, deadline - monotonic()),
            ),
            candidate,
        )
        # The returned assessment belongs to the parent search request. Runtime
        # remaining seconds are execution machinery, not a new frozen policy or
        # nondeterministic evidence value for the selected candidate.
        validation = replace(validation, context=_economic_context(p))
        used += max(1, validation.work_used)
        evaluated += 1
        if not validation.complete:
            reason = (
                "SEARCH_LIMIT_REACHED"
                if any(f.code == "SEARCH_LIMIT_REACHED" for f in validation.findings)
                else "INCOMPLETE_DATA"
            )
            return incomplete(reason, validation.findings)
        if validation.continuation is not None:
            scored += 1
            if scored > p.score_limit:
                return incomplete(
                    "SEARCH_LIMIT_REACHED",
                    (Finding("SEARCH_LIMIT_REACHED", "fully_scored_candidate_cap"),),
                )
        if not validation.feasible:
            for code in {f.code for f in validation.violations}:
                rejected[code] = rejected.get(code, 0) + 1
            continue
        if (
            best is None
            or best_validation is None
            or _rank(candidate, validation, p) < _rank(best, best_validation, p)
        ):
            assert validation.continuation and validation.continuation.rollout
            ledger = validation.continuation.rollout.ledger
            assert ledger is not None
            best = replace(
                candidate,
                claimed_future_lines=validation.continuation.future_lines,
                claimed_components=ledger.components,
            )
            best_validation = validation
    if monotonic() >= deadline:
        return incomplete("SEARCH_LIMIT_REACHED")
    return EconomicSearchResult(
        "OK" if best else "INFEASIBLE",
        None if best else "NO_FEASIBLE_CANDIDATE_IN_DOMAIN",
        True,
        best is not None,
        best,
        best_validation,
        no_action,
        size,
        evaluated,
        scored,
        used,
        (),
        tuple(sorted(rejected.items())),
        None,
    )

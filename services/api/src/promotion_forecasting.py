"""Pure promotion application and immutable forecast differences, not API transport.

PromotionEvent is the canonical multiplier/revision contract. Complete frozen
event history and resolved elapsed SalesBatch coverage must be supplied by the
caller. Neither persistence, history replay nor materiality decisions live here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from typing import Literal

from src.inventory_projection import Finding, SourceEvidence, _aware, _id, _quantity
from src.operations_schemas import PromotionEvent, SalesBatch
from src.procurement import _decimal
from src.schemas import MenuItem
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

SOURCES = frozenset(
    {"catalogue", "recipe", "history", "model", "profile", "policy", "other_context"}
)
APPLICATION_POLICY = "EXPLICIT_PORTION_MULTIPLIER_V1"


@dataclass(frozen=True)
class PromotionUse:
    event_id: str
    promotion_id: str
    revision: int
    recorded_at: datetime
    effective_at: datetime
    assumption_source: str
    multiplier: Decimal
    start: datetime
    end: datetime
    dish_ids: tuple[str, ...]


@dataclass(frozen=True)
class ObservedPortions:
    """Resolved actual interval; never passed to the projector as future demand."""

    start: datetime
    end: datetime
    portions: tuple[tuple[str, int], ...]
    batch_id: str
    revision: int
    evidence: SourceEvidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "portions", tuple(tuple(row) for row in self.portions))


@dataclass(frozen=True)
class ForecastVersion:
    """Caller-referenced immutable result; references are not persisted by this kernel.

    EXCLUDED declares an original normal basis, not a forecast that was already
    adjusted elsewhere. Sources bind catalogue/recipes, history, model, service
    profile, application policy and other forecast context. The backend/adapter
    must resolve these declarations against actual immutable artifacts.
    """

    reference: str
    as_of: datetime
    known_at: datetime
    target_date: date
    profile: tuple[ServicePeriod, ...]
    sources: tuple[tuple[str, SourceEvidence], ...]
    buckets: tuple[ProjectedDemandBucket, ...]
    promotion_state: Literal["EXCLUDED", "APPLIED", "UNKNOWN"]
    base_reference: str
    actuals: tuple[ObservedPortions, ...] = ()
    promotions: tuple[PromotionUse, ...] = ()
    context_evidence: SourceEvidence | None = None
    actual_coverage: SourceEvidence | None = None
    units: str = "PORTIONS"
    application_policy: str = APPLICATION_POLICY
    # All visible revisions, including cancellations and not-yet-effective changes.
    # Entries are (promotion_id, revision, canonical event_id), resolvable through
    # context_evidence. Numerical overlap records alone cannot preserve cancellations.
    revision_evidence: tuple[tuple[str, int, str], ...] = ()

    def __post_init__(self) -> None:
        # Canonical transport models are mutable; artifacts only retain immutable
        # numerical values and references, never a caller's event or sales model.
        for name in ("profile", "sources", "buckets", "actuals", "promotions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "sources", tuple((k, v) for k, v in self.sources))
        object.__setattr__(
            self, "revision_evidence", tuple(tuple(r) for r in self.revision_evidence)
        )


@dataclass(frozen=True)
class PromotionApplication:
    complete: bool
    forecast: ForecastVersion | None
    findings: tuple[Finding, ...]
    # Relevant overlaps are evidence for reassessment, not a threshold or decision.
    overlaps: tuple[PromotionUse, ...]


@dataclass(frozen=True)
class ForecastDelta:
    start: datetime
    end: datetime
    dish_id: str
    old: Decimal
    new: Decimal
    delta: Decimal
    absolute_delta: Decimal
    relative_delta: Decimal | None
    relative_reason: str | None


@dataclass(frozen=True)
class ForecastComparison:
    status: Literal["COMPARED", "NO_PREVIOUS_VERSION", "INCOMPATIBLE"]
    previous: ForecastVersion | None
    current: ForecastVersion
    deltas: tuple[ForecastDelta, ...] | None
    findings: tuple[Finding, ...]
    changed_context: tuple[str, ...]
    attribution: str


def _evidence(value: SourceEvidence | None, known_at: datetime) -> None:
    if value is None or value.reference is None or value.captured_revision is None:
        raise ValueError("Missing evidence reference or captured revision")
    _id(value.reference)
    _id(value.captured_revision)
    if value.available_at is None or _aware(value.available_at) > known_at:
        raise ValueError("Missing or late evidence availability")


def _validate_forecast(
    forecast: ForecastVersion, menu_items: Sequence[MenuItem]
) -> None:
    _id(forecast.reference)
    _id(forecast.base_reference)
    as_of, known_at = _aware(forecast.as_of), _aware(forecast.known_at)
    if (
        forecast.units != "PORTIONS"
        or forecast.application_policy != APPLICATION_POLICY
    ):
        raise ValueError("Unsupported units or application policy")
    if len(forecast.sources) != len(SOURCES) or set(dict(forecast.sources)) != SOURCES:
        raise ValueError("Missing/duplicate forecast source manifest")
    for _, evidence in forecast.sources:
        _evidence(evidence, known_at)
    ids = {m.id for m in menu_items}
    # Reuse the dated allocator to expand and validate the full service profile.
    expected = allocate_service_buckets(
        {i: Decimal(0) for i in ids},
        menu_items,
        target_date=forecast.target_date,
        profile=forecast.profile,
    )
    if any(b.start < as_of < b.end for b in expected):
        raise ValueError("Unsupported partial-bucket observation cutoff")
    if [(b.start, b.end) for b in forecast.buckets] != [
        (b.start, b.end) for b in expected if b.start >= as_of
    ]:
        raise ValueError("Incomplete future bucket coverage")
    for bucket in forecast.buckets:
        if set(bucket.expected_portions) != ids:
            raise ValueError("Missing/unknown forecast dish")
        for quantity in bucket.expected_portions.values():
            _quantity(quantity)
    elapsed = [(b.start, b.end) for b in expected if b.end <= as_of]
    if [(a.start, a.end) for a in forecast.actuals] != elapsed:
        raise ValueError("Incomplete actual elapsed coverage")
    for actual in forecast.actuals:
        if (
            len(actual.portions) != len(ids)
            or set(dict(actual.portions)) != ids
            or any(type(q) is not int or q < 0 for _, q in actual.portions)
            or type(actual.revision) is not int
            or actual.revision < 1
        ):
            raise ValueError("Invalid actual portions/revision")
        _id(actual.batch_id)
        _evidence(actual.evidence, known_at)
    if elapsed:
        _evidence(forecast.actual_coverage, known_at)
    if forecast.promotion_state == "APPLIED":
        _evidence(forecast.context_evidence, known_at)
    elif forecast.promotion_state != "EXCLUDED":
        raise ValueError("Unknown promotion basis state")
    elif (
        forecast.promotions
        or forecast.revision_evidence
        or forecast.base_reference != forecast.reference
    ):
        raise ValueError("Ambiguous unadjusted forecast basis")


def _visible_events(
    events: Sequence[PromotionEvent], known_at: datetime, ids: set[str]
) -> tuple[PromotionEvent, ...]:
    visible: list[PromotionEvent] = []
    identities: set[str] = set()
    for original in events:
        if _aware(original.timestamp) > known_at:
            continue
        event = original.model_copy(deep=True)
        p = event.payload
        _id(event.id)
        _id(event.source)
        _id(p.promotion_id)
        _id(p.name)
        _aware(p.effective_at)
        _quantity(p.demand_multiplier)
        if (
            event.id in identities
            or type(p.revision) is not int
            or p.revision < 1
            or type(p.active) is not bool
            or not Decimal(0) < p.demand_multiplier <= Decimal(10)
            or not p.menu_item_ids
            or len(set(p.menu_item_ids)) != len(p.menu_item_ids)
            or not set(p.menu_item_ids) <= ids
            or type(p.start_date) is not date
            or type(p.end_date) is not date
            or p.start_date > p.end_date
        ):
            raise ValueError("Invalid promotion adjustment, identity or dish coverage")
        identities.add(event.id)
        visible.append(event)
    for identity in sorted({e.payload.promotion_id for e in visible}):
        rows = sorted(
            (e for e in visible if e.payload.promotion_id == identity),
            key=lambda e: e.payload.revision,
        )
        if [e.payload.revision for e in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("Incomplete/duplicate promotion revision history")
        for i, event in enumerate(rows):
            if event.type != ("PROMOTION_CREATED" if i == 0 else "PROMOTION_CHANGED"):
                raise ValueError("Promotion event type/revision conflict")
            if i and (
                event.timestamp < rows[i - 1].timestamp
                or event.payload.effective_at < rows[i - 1].payload.effective_at
            ):
                raise ValueError("Non-monotone promotion revisions")
    return tuple(
        sorted(visible, key=lambda e: (e.payload.promotion_id, e.payload.revision))
    )


def _actuals(
    sales: Sequence[tuple[SalesBatch, SourceEvidence]],
    *,
    expected: tuple[ProjectedDemandBucket, ...],
    as_of: datetime,
    known_at: datetime,
    ids: set[str],
) -> tuple[ObservedPortions, ...]:
    actuals = []
    seen: set[str] = set()
    logical: set[tuple[str, str]] = set()
    for batch, evidence in sales:
        start, end = _aware(batch.period_start), _aware(batch.period_end)
        _evidence(evidence, known_at)
        _id(batch.id)
        _id(batch.source)
        _id(batch.batch_id)
        if (
            batch.id in seen
            or (batch.source, batch.batch_id) in logical
            or not batch.active
            or type(batch.revision) is not int
            or batch.revision < 1
            or not start < end <= as_of
            or not set(batch.sales) <= ids
            or any(type(q) is not int or q < 0 for q in batch.sales.values())
        ):
            raise ValueError("Invalid/unresolved actual sales batch")
        seen.add(batch.id)
        logical.add((batch.source, batch.batch_id))
        actuals.append(
            ObservedPortions(
                start,
                end,
                tuple((i, batch.sales.get(i, 0)) for i in sorted(ids)),
                batch.id,
                batch.revision,
                evidence,
            )
        )
    actuals.sort(key=lambda a: a.start)
    if [(a.start, a.end) for a in actuals] != [
        (b.start, b.end) for b in expected if b.end <= as_of
    ]:
        raise ValueError(
            "Actual sales must completely cover elapsed service half-hours"
        )
    return tuple(actuals)


def apply_promotions(
    basis: ForecastVersion,
    menu_items: Sequence[MenuItem],
    *,
    events: Sequence[PromotionEvent],
    context_evidence: SourceEvidence | None,
    context_complete: bool,
    as_of: datetime,
    known_at: datetime,
    result_reference: str,
    sales: Sequence[tuple[SalesBatch, SourceEvidence]] = (),
    actual_coverage: SourceEvidence | None = None,
) -> PromotionApplication:
    """Apply known revisions to future buckets of an explicit original basis.

    Full revision histories are evaluated by (effective_at, revision) at each
    bucket start. A change strictly inside a relevant bucket is unsupported.
    Inclusive campaign dates and revision clocks are separate. Cancellation or
    amendment always starts from the original EXCLUDED basis. No stacking,
    observed-sales uplift, daily-final/batch summation or hidden factor is used.

    Invalid numerical inputs/evidence yield incomplete with no forecast. A
    complete empty context explicitly asserts that no promotions were supplied.
    """
    overlaps: list[PromotionUse] = []
    try:
        _validate_forecast(basis, menu_items)
        if basis.promotion_state != "EXCLUDED" or basis.actuals:
            raise ValueError("Original unadjusted full-service basis required")
        as_of, known_at = _aware(as_of), _aware(known_at)
        _id(result_reference)
        if (
            basis.as_of > as_of
            or basis.known_at > known_at
            or result_reference == basis.reference
        ):
            raise ValueError("Invalid issue clocks or reused result identity")
        _evidence(context_evidence, known_at)
        if context_complete is not True:
            raise ValueError("Complete frozen promotion context required")
        ids = {m.id for m in menu_items}
        events = _visible_events(events, known_at, ids)
        if any(b.start < as_of < b.end for b in basis.buckets):
            raise ValueError("Unsupported partial-bucket observation cutoff")
        actuals = _actuals(
            sales, expected=basis.buckets, as_of=as_of, known_at=known_at, ids=ids
        )
        if actuals:
            _evidence(actual_coverage, known_at)
        projected = []
        for bucket in basis.buckets:
            if bucket.end <= as_of:
                continue
            portions = dict(bucket.expected_portions)
            applied: set[str] = set()
            for identity in sorted({e.payload.promotion_id for e in events}):
                rows = [e for e in events if e.payload.promotion_id == identity]
                # A revision may remove dishes/change dates/cancel. Inspect both
                # sides so a removal inside the bucket cannot silently disappear.
                for index, event in enumerate(rows):
                    if bucket.start < event.payload.effective_at < bucket.end:
                        neighbors = rows[max(0, index - 1) : index + 1]
                        if any(
                            e.payload.active
                            and e.payload.start_date
                            <= basis.target_date
                            <= e.payload.end_date
                            for e in neighbors
                        ):
                            raise ValueError(
                                "Unsupported promotion change inside service bucket"
                            )
                effective = [e for e in rows if e.payload.effective_at <= bucket.start]
                if not effective:
                    continue
                event = effective[-1]
                p = event.payload
                if not p.active or not p.start_date <= basis.target_date <= p.end_date:
                    continue
                use = PromotionUse(
                    event.id,
                    identity,
                    p.revision,
                    event.timestamp,
                    p.effective_at,
                    event.source,
                    p.demand_multiplier,
                    bucket.start,
                    bucket.end,
                    tuple(sorted(p.menu_item_ids)),
                )
                overlaps.append(use)
                if applied.intersection(p.menu_item_ids):
                    raise ValueError("Unsupported overlapping promotion stacking")
                applied.update(p.menu_item_ids)
                for dish in p.menu_item_ids:
                    portions[dish] = _decimal(
                        Fraction(portions[dish]) * Fraction(p.demand_multiplier)
                    )
            projected.append(ProjectedDemandBucket(bucket.start, bucket.end, portions))
        result = ForecastVersion(
            result_reference,
            as_of,
            known_at,
            basis.target_date,
            basis.profile,
            basis.sources,
            tuple(projected),
            "APPLIED",
            basis.reference,
            actuals,
            tuple(overlaps),
            context_evidence,
            actual_coverage,
            revision_evidence=tuple(
                (e.payload.promotion_id, e.payload.revision, e.id) for e in events
            ),
        )
        _validate_forecast(result, menu_items)
        return PromotionApplication(True, result, (), tuple(overlaps))
    except (ValueError, TypeError, AttributeError) as error:
        return PromotionApplication(
            False,
            None,
            (Finding("INCOMPLETE_PROMOTION_INPUT", str(error)),),
            tuple(overlaps),
        )


def compare_forecast_versions(
    previous: ForecastVersion | None,
    current: ForecastVersion,
    menu_items: Sequence[MenuItem],
) -> ForecastComparison:
    """Diff frozen artifacts only; never rerun a forecast or make a plan decision.

    Relative signed change uses 28 significant decimal digits, half-even.
    Quantities and absolute/signed deltas remain exact. Context differences are
    recorded, never converted into a causal claim.
    """
    findings = []
    try:
        _validate_forecast(current, menu_items)
        if previous is not None:
            _validate_forecast(previous, menu_items)
    except (ValueError, TypeError, AttributeError) as error:
        findings.append(Finding("INVALID_FORECAST_ARTIFACT", str(error)))
    if findings:
        return ForecastComparison(
            "INCOMPATIBLE",
            previous,
            current,
            None,
            tuple(findings),
            (),
            "NO_CAUSAL_CLAIM",
        )
    if previous is None:
        return ForecastComparison(
            "INCOMPATIBLE" if findings else "NO_PREVIOUS_VERSION",
            None,
            current,
            None,
            tuple(findings),
            (),
            "NO_CAUSAL_CLAIM",
        )
    old_sources, new_sources = dict(previous.sources), dict(current.sources)
    changed = tuple(
        sorted(
            name for name in SOURCES if old_sources.get(name) != new_sources.get(name)
        )
    )
    for name in ("catalogue", "recipe", "model", "profile", "policy"):
        if name in changed:
            findings.append(Finding("INCOMPATIBLE_BASIS", name))
    # Semantic profile equality, independent of caller list ordering.
    old_profile = sorted((p.start, p.end, p.weight) for p in previous.profile)
    new_profile = sorted((p.start, p.end, p.weight) for p in current.profile)
    if (
        previous.target_date != current.target_date
        or previous.as_of != current.as_of
        or old_profile != new_profile
        or previous.units != current.units
        or previous.application_policy != current.application_policy
        or [(b.start, b.end) for b in previous.buckets]
        != [(b.start, b.end) for b in current.buckets]
    ):
        findings.append(
            Finding("INCOMPATIBLE_COVERAGE", "horizon/units/profile/cutoff")
        )
    if previous.actuals != current.actuals:
        changed += ("actuals",)
    if previous.actual_coverage != current.actual_coverage:
        changed += ("actual_coverage",)
    if previous.known_at != current.known_at:
        changed += ("knowledge_cutoff",)
    if previous.promotions != current.promotions:
        changed += ("promotions",)
    if previous.context_evidence != current.context_evidence:
        changed += ("promotion_context",)
    if previous.revision_evidence != current.revision_evidence:
        changed += ("promotion_revisions",)
    if previous.base_reference != current.base_reference:
        changed += ("unadjusted_basis",)
    if previous.reference == current.reference and previous != current:
        findings.append(Finding("CONFLICTING_IMMUTABLE_REFERENCE", current.reference))
    if findings:
        return ForecastComparison(
            "INCOMPATIBLE",
            previous,
            current,
            None,
            tuple(findings),
            changed,
            "NO_CAUSAL_CLAIM",
        )
    deltas = []
    for old, new in zip(previous.buckets, current.buckets, strict=True):
        for dish in sorted(old.expected_portions):
            before, after = old.expected_portions[dish], new.expected_portions[dish]
            delta = _decimal(Fraction(after) - Fraction(before))
            with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
                relative = delta / before if before else None
            deltas.append(
                ForecastDelta(
                    old.start,
                    old.end,
                    dish,
                    before,
                    after,
                    delta,
                    _decimal(abs(Fraction(delta))),
                    relative,
                    None if before else "ZERO_BASELINE",
                )
            )
    return ForecastComparison(
        "COMPARED", previous, current, tuple(deltas), (), changed, "NO_CAUSAL_CLAIM"
    )

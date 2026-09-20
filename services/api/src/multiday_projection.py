"""Continuous forecast projection with ingredient windows and honest partial risk.

No observed replay, renewal, transport schema, purchase search or policy ranking.
Each ingredient uses the same validated depletion kernel as the one-day API.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction

from src.coverage import CoverageResult, evidence_findings
from src.forecasting import SINGAPORE
from src.inventory_projection import (
    FEFO_POLICY,
    SOURCE_NAMES,
    ExpectedSupply,
    Finding,
    InventoryProjection,
    SourceEvidence,
    _aware,
    _project_inventory,
    _quantity,
)
from src.procurement import _decimal
from src.promotion_forecasting import APPLICATION_POLICY, SOURCES, ForecastVersion
from src.requirements import calculate_requirements
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import ServicePeriod, allocate_service_buckets

CONSTRAINT_POLICY = "SERVICE_END_SAFETY_RECEIPT_STORAGE_V1"


@dataclass(frozen=True, order=True)
class Breach:
    kind: str
    ingredient_id: str
    start: datetime
    end: datetime
    quantity: Decimal
    limit: Decimal
    scope: str


@dataclass(frozen=True)
class DatedBalance:
    at: datetime
    opening: Decimal
    allocated: Decimal
    expired: Decimal
    admitted: Decimal
    closing: Decimal


@dataclass(frozen=True)
class IngredientProjection:
    ingredient_id: str
    protected_end: datetime
    assessment_end: datetime
    verified_until: datetime | None
    complete: bool
    projection: InventoryProjection | None
    movements: tuple[DatedBalance, ...] = ()


@dataclass(frozen=True)
class MultiDayProjection:
    coverage: CoverageResult
    complete: bool
    findings: tuple[Finding, ...]
    ingredients: tuple[IngredientProjection, ...]
    breaches: tuple[Breach, ...]
    evidence: tuple[tuple[str, SourceEvidence], ...]
    constraint_policy: str | None
    provenance: str = "PROJECTED"


def project_multiday(
    coverage: CoverageResult,
    forecasts: Sequence[ForecastVersion],
    menu_items: Sequence[MenuItem],
    ingredients: Sequence[Ingredient],
    recipes: Sequence[RecipeItem],
    opening_lots: Sequence[EstimatedInventoryLot],
    supplies: Sequence[ExpectedSupply],
    *,
    opening_manifest: Mapping[str, Sequence[str]],
    supply_manifest: Sequence[str],
    recipe_manifest: Sequence[tuple[str, str]],
    evidence: Mapping[str, SourceEvidence],
    safety: Mapping[str, Decimal],
    storage: Mapping[str, Decimal],
    assessment_end: Mapping[str, datetime],
    constraint_policy: str | None,
    fefo_policy: str | None,
) -> MultiDayProjection:
    """Project independently verified ingredient prefixes without filling gaps.

    Protection ends immediately before the boundary receipt. Additional explicit
    assessment consumes forecast demand but labels risks ASSESSMENT, not purchase
    requirements. Every retained number has verified_until; incomplete is never
    evidence of safety. Source declarations cannot repair incorrect Backend input
    selection. Forecast actuals are never consumed a second time.
    """
    issue, known = map(_aware, (coverage.issue_time, coverage.known_at))
    if type(coverage.max_horizon_days) is not int or coverage.max_horizon_days < 1:
        raise ValueError("Explicit positive maximum horizon required")
    revision = coverage.captured_revision
    units = {i.id: i.unit for i in ingredients}
    calculate_requirements(
        {d.id: Decimal(0) for d in menu_items}, menu_items, ingredients, recipes
    )
    if set(coverage.ingredient_ids) != set(units):
        raise ValueError("Coverage/catalogue mismatch")
    for mapping in (opening_manifest, safety, storage, assessment_end):
        if set(mapping) - set(units):
            raise ValueError("Unknown ingredient input")
    for q in [*safety.values(), *storage.values()]:
        _quantity(q)
    findings = set(coverage.findings)
    sources = dict(coverage.evidence)
    sources.update(evidence)
    common = set()
    if dict(coverage.evidence).get("catalogue") != evidence.get("catalogue"):
        common.add(Finding("COVERAGE_CATALOGUE_MISMATCH", "catalogue"))
    for name in SOURCE_NAMES - {"forecast", "profile"}:
        common.update(evidence_findings(name, evidence.get(name), known, revision))
    constraint_findings = set(
        evidence_findings("constraints", evidence.get("constraints"), known, revision)
    )
    if constraint_policy != CONSTRAINT_POLICY:
        constraint_findings.add(Finding("UNSUPPORTED_CONSTRAINT_POLICY", "policy"))
    findings.update(constraint_findings)
    if fefo_policy != FEFO_POLICY:
        common.add(Finding("UNSUPPORTED_FEFO_POLICY", "policy"))
    if len(set(supply_manifest)) != len(supply_manifest) or len(
        {s.delivery.id for s in supplies}
    ) != len(supplies):
        raise ValueError("Duplicate supply identity")
    if set(supply_manifest) != {s.delivery.id for s in supplies}:
        common.add(Finding("SUPPLY_COVERAGE_MISMATCH", "supply"))
    if any(l.ingredient_id not in units for l in opening_lots) or any(
        s.delivery.ingredient_id not in units for s in supplies
    ):
        raise ValueError("Unknown stock/supply ingredient")
    lot_ids = [l.id for l in opening_lots]
    projected_ids = [
        s.projected_lot_id
        for s in supplies
        if s.delivery.outstanding_quantity and s.projected_lot_id
    ]
    receipt_ids = [r.id for s in supplies for r in s.delivery.receipts]
    receipt_lots = [r.lot_id for s in supplies for r in s.delivery.receipts]
    for keys in (lot_ids + projected_ids, receipt_ids, receipt_lots):
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate stock/receipt identity")
    declared = [key for values in opening_manifest.values() for key in values]
    if len(set(declared)) != len(declared):
        raise ValueError("Duplicate opening manifest lot")
    days = {f.target_date: f for f in forecasts}
    if len(days) != len(forecasts):
        raise ValueError("Duplicate forecast date")
    for f in forecasts:
        if type(f.target_date) is not date:
            raise ValueError("Invalid forecast date")
    findings.update(common)
    results = []
    breaches = []
    windows = {w.ingredient_id: w for w in coverage.windows}
    if len(windows) != len(coverage.windows) or set(windows) - set(units):
        raise ValueError("Duplicate or unknown protected window")
    for ingredient in sorted(units):
        if ingredient not in windows:
            findings.add(Finding("MISSING_PROTECTED_WINDOW", ingredient))
            continue
        window = windows[ingredient]
        if _aware(window.start) != issue or _aware(window.end) <= issue:
            raise ValueError("Invalid protected window")
        missing = [
            name
            for name, mapping in (
                ("safety", safety),
                ("storage", storage),
                ("assessment", assessment_end),
                ("opening", opening_manifest),
            )
            if ingredient not in mapping
        ]
        if missing:
            findings.update(
                Finding("MISSING_INGREDIENT_INPUT", name + ":" + ingredient)
                for name in missing
            )
        end = (
            _aware(assessment_end[ingredient])
            if ingredient in assessment_end
            else window.end
        )
        if end < window.end:
            raise ValueError("Assessment cannot truncate protected demand")
        own: set[Finding] = set()
        if end > issue + timedelta(days=coverage.max_horizon_days):
            own.add(Finding("UNSUPPORTED_HORIZON", ingredient))
        own_supplies = [s for s in supplies if s.delivery.ingredient_id == ingredient]
        for s in own_supplies:
            if s.delivery.outstanding_quantity and _aware(s.delivery.expected_at) > end:
                own.add(
                    Finding(
                        "DELAYED_COMMITMENT_BEYOND_ASSESSMENT",
                        ingredient
                        + ":"
                        + s.delivery.id
                        + "@"
                        + s.delivery.expected_at.isoformat(),
                    )
                )
        if (
            common
            or "opening" in missing
            or any(f.code == "UNSUPPORTED_HORIZON" for f in own)
        ):
            findings.update(own)
            results.append(
                IngredientProjection(ingredient, window.end, end, None, False, None)
            )
            continue
        profiles: dict[date, Sequence[ServicePeriod]] = {}
        buckets = []
        verified = issue
        day = issue.date()
        while datetime.combine(day, time.min, SINGAPORE) < end:
            f = days.get(day)
            name = "forecast:" + str(day)
            if f is None:
                own.add(Finding("MISSING_FORECAST_DAY", name))
                break
            bad = set()
            if _aware(f.as_of) != issue or _aware(f.known_at) > known:
                bad.add(Finding("FORECAST_CLOCK_MISMATCH", name))
            if (
                not f.reference
                or not f.base_reference
                or f.units != "PORTIONS"
                or f.application_policy != APPLICATION_POLICY
                or f.promotion_state not in ("EXCLUDED", "APPLIED")
            ):
                bad.add(Finding("UNSUPPORTED_FORECAST_VERSION", name))
            fs = dict(f.sources)
            if len(fs) != len(f.sources) or set(fs) != SOURCES:
                bad.add(Finding("FORECAST_SOURCE_COVERAGE", name))
            for key in SOURCES:
                bad.update(
                    evidence_findings(
                        name + ":" + key,
                        fs.get(key),
                        min(known, _aware(f.known_at)),
                        revision,
                    )
                )
            for key in ("catalogue", "recipe"):
                if fs.get(key) != evidence.get(key):
                    bad.add(Finding("FORECAST_PROVENANCE_MISMATCH", name + ":" + key))
            if f.promotion_state == "APPLIED":
                bad.update(
                    evidence_findings(
                        name + ":promotions",
                        f.context_evidence,
                        min(known, _aware(f.known_at)),
                        revision,
                    )
                )
            elif f.promotions or f.revision_evidence or f.base_reference != f.reference:
                bad.add(Finding("AMBIGUOUS_UNADJUSTED_FORECAST", name))
            if not f.profile:
                bad.add(Finding("MISSING_SERVICE_PROFILE", name))
            if bad:
                own.update(bad)
                break
            for key, ev in f.sources:
                sources[name + ":" + key] = ev
            if f.context_evidence is not None:
                sources[name + ":promotions"] = f.context_evidence
            # Record the actual version identity separately from its source refs.
            sources[name] = SourceEvidence(f.reference, f.known_at, revision)
            expected = allocate_service_buckets(
                {d.id: Decimal(0) for d in menu_items},
                menu_items,
                target_date=day,
                profile=f.profile,
            )
            actual = {(b.start, b.end): b for b in f.buckets}
            if len(actual) != len(f.buckets):
                raise ValueError("Duplicate forecast bucket")
            if set(actual) - {(b.start, b.end) for b in expected if b.start >= issue}:
                raise ValueError("Forecast contains unknown or elapsed interval")
            profiles[day] = f.profile
            for expected_bucket in expected:
                start, finish = expected_bucket.start, expected_bucket.end
                if start < issue < finish or start < end < finish:
                    own.add(Finding("UNSUPPORTED_BUCKET_CUTOFF", name))
                    break
                if start < issue or start >= end:
                    continue
                b = actual.get((start, finish))
                if b is None or set(b.expected_portions) != {d.id for d in menu_items}:
                    own.add(
                        Finding(
                            "INCOMPLETE_FORECAST_BUCKET", name + "@" + start.isoformat()
                        )
                    )
                    verified = start
                    break
                calculate_requirements(
                    b.expected_portions, menu_items, ingredients, recipes
                )
                buckets.append(b)
                verified = finish
            if any(finding.source.startswith(name) for finding in own):
                break
            verified = min(
                end, datetime.combine(day + timedelta(days=1), time.min, SINGAPORE)
            )
            day += timedelta(days=1)
        # Preserve a verified prefix before a later unresolved receipt. Do not
        # remove the commitment or silently treat its remaining quantity as zero.
        for supply in own_supplies:
            if not supply.delivery.outstanding_quantity:
                continue
            arrival = _aware(supply.delivery.expected_at)
            if supply.expiry_evidence is not None:
                sources["expiry:" + supply.delivery.id] = supply.expiry_evidence
            bad = set(
                evidence_findings(
                    "expiry:" + supply.delivery.id,
                    supply.expiry_evidence,
                    known,
                    revision,
                )
            )
            if supply.expiry_date is None:
                bad.add(Finding("MISSING_EXPECTED_EXPIRY", supply.delivery.id))
            if not supply.projected_lot_id:
                bad.add(Finding("MISSING_PROJECTED_LOT_ID", supply.delivery.id))
            if any(b.start < arrival < b.end for b in buckets):
                bad.add(Finding("UNSUPPORTED_MID_BUCKET_ARRIVAL", supply.delivery.id))
            if bad:
                own.update(bad)
                cutoff = min(
                    (b.start for b in buckets if b.start < arrival <= b.end),
                    default=arrival - timedelta(microseconds=1),
                )
                verified = min(verified, max(issue, cutoff))
        buckets = [b for b in buckets if b.end <= verified]
        projection = None
        movements: tuple[DatedBalance, ...] = ()
        if verified > issue:
            # Same pure validation and FEFO executor; all real recipe lines remain
            # intact. Ingredient scope only factors independent stock arithmetic.
            projection = _project_inventory(
                [l for l in opening_lots if l.ingredient_id == ingredient],
                buckets,
                menu_items,
                ingredients,
                recipes,
                own_supplies,
                as_of=issue,
                target_date=issue.date(),
                horizon_end=verified,
                known_at=known,
                captured_revision=revision,
                opening_manifest={ingredient: opening_manifest[ingredient]},
                supply_manifest=[s.delivery.id for s in own_supplies],
                recipe_manifest=recipe_manifest,
                service_profile=(),
                evidence={
                    k: evidence[k]
                    if k not in ("forecast", "profile")
                    else dict(days[issue.date()].sources)[
                        "profile" if k == "profile" else "model"
                    ]
                    for k in SOURCE_NAMES
                },
                fixture_fefo=FEFO_POLICY,
                _profiles=profiles,
                _ingredient_ids=frozenset({ingredient}),
            )
            own.update(projection.findings)
            if projection.complete:
                own_breaches, movements = _boundaries(
                    projection,
                    ingredient,
                    window.end,
                    safety.get(ingredient) if not constraint_findings else None,
                    storage.get(ingredient) if not constraint_findings else None,
                    own_supplies,
                )
                breaches.extend(own_breaches)
        findings.update(own)
        results.append(
            IngredientProjection(
                ingredient,
                window.end,
                end,
                verified if projection is not None and projection.complete else None,
                not own and not missing and not constraint_findings and verified == end,
                projection,
                movements,
            )
        )
    return MultiDayProjection(
        coverage,
        not findings and len(results) == len(units),
        tuple(sorted(findings)),
        tuple(results),
        tuple(sorted(breaches)),
        tuple(sorted(sources.items())),
        constraint_policy,
    )


def _boundaries(
    projection: InventoryProjection,
    ingredient: str,
    protected_end: datetime,
    safety: Decimal | None,
    storage: Decimal | None,
    supplies: Sequence[ExpectedSupply],
) -> tuple[list[Breach], tuple[DatedBalance, ...]]:
    """Reconstruct event-boundary stock from the kernel ledger (exact rationals).

    Same timing as candidate validation: consume ending interval, expire, admit
    simultaneous receipts, check storage before subsequent consumption.
    """
    assert projection.ingredients is not None and projection.buckets is not None
    assert projection.expiries is not None
    result = []
    changes: dict[datetime, dict[str, Fraction]] = {}

    def move(at: datetime, kind: str, q: Fraction) -> None:
        row = changes.setdefault(at, {})
        row[kind] = row.get(kind, Fraction(0)) + q

    def breach(
        kind: str, start: datetime, end: datetime, quantity: Decimal, limit: Decimal
    ) -> None:
        result.append(
            Breach(
                kind,
                ingredient,
                start,
                end,
                quantity,
                limit,
                "PROTECTED" if start < protected_end else "ASSESSMENT",
            )
        )

    balance = Fraction(projection.ingredients[0].opening)
    movements = [
        DatedBalance(
            projection.as_of,
            _decimal(balance),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            _decimal(balance),
        )
    ]
    if storage is not None and balance > Fraction(storage):
        breach(
            "STORAGE", projection.as_of, projection.as_of, _decimal(balance), storage
        )
    for b in projection.buckets:
        r = b.ingredients[0]
        if r.unmet:
            breach("SHORTAGE", b.start, b.end, r.unmet, Decimal(0))
        if safety is not None and b.start < protected_end and r.closing < safety:
            breach("SAFETY", b.start, b.end, r.closing, safety)
        move(b.end, "allocated", Fraction(r.allocated))
    for expiry in projection.expiries:
        move(expiry.at, "expired", Fraction(expiry.quantity))
    for s in supplies:
        if (
            s.delivery.outstanding_quantity
            and s.delivery.expected_at <= projection.horizon_end
        ):
            move(
                _aware(s.delivery.expected_at),
                "admitted",
                Fraction(s.delivery.outstanding_quantity),
            )
    for at, change in sorted(changes.items()):
        opening = balance
        allocated = change.get("allocated", Fraction(0))
        expired = change.get("expired", Fraction(0))
        admitted = change.get("admitted", Fraction(0))
        balance += admitted - allocated - expired
        movements.append(
            DatedBalance(
                at,
                _decimal(opening),
                _decimal(allocated),
                _decimal(expired),
                _decimal(admitted),
                _decimal(balance),
            )
        )
        if storage is not None and balance > Fraction(storage):
            breach("STORAGE", at, at, _decimal(balance), storage)
    return result, tuple(movements)

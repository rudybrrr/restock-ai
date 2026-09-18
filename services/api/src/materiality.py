"""Pure sales materiality against an issued forecast and frozen Backend contract.

No ingestion, historical inventory replay, forecast adjustment, approval or IO.
Selected snapshot rows already embody Backend correction selection; when several
revisions are supplied, the latest visible replacement wins. References attest
to caller-resolved artifacts, not proof that those artifacts were persisted.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise

from src.history_dataset import Catalogue
from src.inventory_projection import (
    FEFO_POLICY,
    Finding,
    InventoryProjection,
    ShortageInterval,
    SourceEvidence,
    _aware,
    _id,
    _quantity,
    project_inventory,
)
from src.operations_schemas import DailyDraft, DailyRevision, Delivery, SalesBatch
from src.procurement import ProjectionInputs, _decimal
from src.procurement_contract_schemas import (
    ForecastActivitySemantics,
    ForecastInputArtifact,
    ProcurementContract,
)
from src.promotion_forecasting import (
    ForecastVersion,
    ObservedPortions,
    _validate_forecast,
)
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import (
    ProjectedDemandBucket,
    ServicePeriod,
    allocate_service_buckets,
)

RULE = "V2_DEMO_ABSOLUTE_OR_RELATIVE_V1"
SAFETY_POLICY = "AFTER_EACH_SERVICE_BUCKET_V1"
CHECKS = ("SALES_DEVIATION", "PHYSICAL_SHORTAGE", "SAFETY_STOCK")


@dataclass(frozen=True)
class SalesThresholdPolicy:
    """Resolved policy values, not defaults or a new Backend transport schema."""

    version: str | None
    rule: str | None
    absolute_floor: Decimal | None
    relative_threshold: Decimal | None
    minimum_expected_portions: Decimal | None
    minimum_complete_buckets: int | None
    evidence: SourceEvidence | None


SALES_MATERIALITY_V1 = SalesThresholdPolicy(
    version="SALES_MATERIALITY_V1",
    rule=RULE,
    absolute_floor=Decimal(5),
    relative_threshold=Decimal("0.2"),
    minimum_expected_portions=Decimal(20),
    minimum_complete_buckets=2,
    evidence=None,
)
"""Aniq-approved one-day demo definition; NOT a selected/persisted run policy.

Approval: 18 September 2026, after explicit review of low-volume assessment
delays. Cumulative per-dish expected served portions >=20 AND >=2 completed
half-hours, with every elapsed service interval covered. Both deviation signs
use inclusive max(5, 0.2 * expected); known stock/safety risk remains independent.
Changed parameters or exposure semantics require a new policy version.
"""


@dataclass(frozen=True)
class SalesPolicyResolution:
    """Internal numerical validation result, not a Backend transport artifact."""

    policy: SalesThresholdPolicy | None
    findings: tuple[Finding, ...]

    @property
    def complete(self) -> bool:
        return self.policy is not None and not self.findings


@dataclass(frozen=True)
class RiskSnapshot:
    """Reuse the existing projector's explicit input bundle and opening manifests."""

    inventory: ProjectionInputs
    plan_evidence: SourceEvidence | None
    safety: Mapping[str, Decimal]
    safety_policy: str | None
    safety_evidence: SourceEvidence | None


@dataclass(frozen=True)
class SalesDeviation:
    dish_id: str
    expected: Decimal | None
    observed: Decimal | None
    deviation: Decimal | None
    threshold: Decimal | None
    adequate_exposure: bool | None
    material: bool | None


@dataclass(frozen=True)
class SafetyBreach:
    ingredient_id: str
    at: datetime
    deficit: Decimal


@dataclass(frozen=True)
class AuthoritativeDay:
    day: date
    revision_id: str
    revision: int
    cutoff: datetime
    recorded_at: datetime
    portions: tuple[tuple[str, int], ...]
    reconciliation_json: str | None


@dataclass(frozen=True)
class RemainingDemand:
    """Actuals stay separate; only future_buckets may enter forward projection."""

    comparison_forecast_reference: str
    baseline_reference: str
    input_artifact_id: str
    input_version: int
    frozen_input_json: str
    as_of: datetime
    known_at: datetime
    captured_state_revision: str
    actuals: tuple[ObservedPortions, ...]
    future_buckets: tuple[ProjectedDemandBucket, ...]
    sources: tuple[tuple[str, SourceEvidence], ...]


@dataclass(frozen=True)
class MaterialityResult:
    material_change: bool | None
    complete: bool
    feasible_under_observed_state: bool | None
    inventory_feasible: bool | None
    assessed_scope: tuple[str, ...]
    sales: tuple[SalesDeviation, ...]
    projection: InventoryProjection | None
    safety_breaches: tuple[SafetyBreach, ...]
    first_stockout_interval: ShortageInterval | None
    first_safety_breach_at: datetime | None
    first_risk_at: datetime | None
    affected_ids: tuple[str, ...]
    compared_intervals: tuple[tuple[datetime, datetime], ...]
    missing_intervals: tuple[tuple[datetime, datetime], ...]
    remainder: RemainingDemand | None
    daily_history: tuple[AuthoritativeDay, ...] | None
    findings: tuple[Finding, ...]
    material_findings: tuple[Finding, ...]
    evidence_refs: tuple[str, ...]
    required_follow_up: tuple[str, ...]
    run_id: str | None
    snapshot_reference: str | None
    as_of: datetime
    known_at: datetime
    captured_state_revision: str
    forecast_reference: str | None
    forecast_input_reference: str
    threshold_policy_version: str | None
    coverage_through: datetime
    limitations: tuple[str, ...] = (
        "ONE_DAY_DECLARED_SCOPE_ONLY",
        "SERVED_PORTIONS_NOT_LATENT_DEMAND",
        "NO_INTRADAY_FORECAST_ADJUSTMENT",
        "NOT_GENERAL_PLAN_FEASIBILITY_OR_FRESHNESS",
        "REFERENCES_REQUIRE_CALLER_PERSISTENCE",
    )


def _ref(e: SourceEvidence | None) -> str | None:
    return e.reference if e else None


def _evidence(
    value: SourceEvidence | None, name: str, revision: str, known_at: datetime
) -> set[Finding]:
    # Adapted from the preserved, unpublished materiality evidence helper.
    issues: set[Finding] = set()
    if value is None or not value.reference or value.available_at is None:
        issues.add(Finding("MISSING_EVIDENCE", name))
    else:
        _id(value.reference)
        if _aware(value.available_at) > known_at:
            issues.add(Finding("EVIDENCE_NOT_YET_AVAILABLE", name))
    if value is None or value.captured_revision != revision:
        issues.add(Finding("CAPTURED_REVISION_MISMATCH", name))
    return issues


def _clock(value: object) -> datetime:
    if isinstance(value, str):
        return _aware(datetime.fromisoformat(value))
    if isinstance(value, datetime):
        return _aware(value)
    raise ValueError("Explicit aware recording time required")


def select_sales_revisions(
    rows: Sequence[Mapping], *, as_of: datetime, known_at: datetime
) -> tuple[tuple[SalesBatch, datetime], ...]:
    """Select canonical frozen sales rows, retaining their recorded_at metadata.

    Supports Backend-selected latest rows (a correction's predecessor need not
    be present) or a full revision list. Missing predecessor evidence is NOT
    reconstructed; Backend owns authoritative snapshot membership. Identical
    retries collapse; conflicting identities/overlapping additive rows reject.
    Future recordings are filtered before revision selection, ignoring active.
    """
    as_of, known_at = _aware(as_of), _aware(known_at)
    chains: dict[tuple[str, str], dict[int, tuple[SalesBatch, datetime]]] = {}
    identities: dict[str, tuple[SalesBatch, datetime]] = {}
    for raw in rows:
        recorded = _clock(raw.get("recorded_at"))
        if recorded > known_at:
            continue
        batch = SalesBatch.model_validate(dict(raw))
        start, end = _aware(batch.period_start), _aware(batch.period_end)
        if start >= end or type(batch.revision) is not int or batch.revision < 1:
            raise ValueError("Invalid sales interval/revision")
        if end > as_of:
            continue
        for identifier in (batch.id, batch.source, batch.batch_id):
            _id(identifier)
        if (batch.revision == 1) != (
            batch.replaces_id is None
        ) or batch.replaces_id == batch.id:
            raise ValueError("Invalid correction identity")
        # active is current mutable state, not recording-time authority.
        batch = batch.model_copy(update={"active": True}, deep=True)
        row = (batch, recorded)
        if batch.id in identities and identities[batch.id] != row:
            raise ValueError("Conflicting duplicate batch identity")
        identities[batch.id] = row
        chain = chains.setdefault((batch.source, batch.batch_id), {})
        if batch.revision in chain and chain[batch.revision] != row:
            raise ValueError("Conflicting sales revision")
        chain[batch.revision] = row
    selected = []
    for chain in chains.values():
        ordered = [chain[v] for v in sorted(chain)]
        first = ordered[0][0]
        for index, (batch, recorded) in enumerate(ordered):
            if (batch.period_start, batch.period_end) != (
                first.period_start,
                first.period_end,
            ):
                raise ValueError("Corrections must preserve their exact interval")
            if batch.replaces_id in identities:
                predecessor, previous_time = identities[batch.replaces_id]
                if (
                    (predecessor.source, predecessor.batch_id)
                    != (batch.source, batch.batch_id)
                    or predecessor.revision != batch.revision - 1
                    or (predecessor.period_start, predecessor.period_end)
                    != (batch.period_start, batch.period_end)
                    or previous_time > recorded
                ):
                    raise ValueError(
                        "Correction must replace the preceding same-identity revision"
                    )
            if index and (
                batch.revision != ordered[index - 1][0].revision + 1
                or batch.replaces_id != ordered[index - 1][0].id
            ):
                raise ValueError("Conflicting or incomplete supplied correction chain")
        selected.append(ordered[-1])
    selected.sort(key=lambda r: (r[0].period_start, r[0].id))
    if any(a[0].period_end > b[0].period_start for a, b in pairwise(selected)):
        raise ValueError("Overlapping additive sales intervals")
    return tuple(selected)


def select_daily_history(
    revisions: Sequence[DailyRevision],
    menu_items: Sequence[MenuItem],
    *,
    as_of: datetime,
    known_at: datetime,
) -> tuple[AuthoritativeDay, ...]:
    """Latest available canonical final revision; batches cannot be passed or added.

    Preserves reconciliation as evidence. No training eligibility flags are
    invented: caller still needs promotional/censor provenance for a new artifact.
    """
    as_of, known_at = _aware(as_of), _aware(known_at)
    dishes = {d.id for d in menu_items}
    selected: dict[date, DailyRevision] = {}
    seen: dict[tuple[date, int], DailyRevision] = {}
    ids: set[str] = set()
    for supplied in revisions:
        r = DailyRevision.model_validate(supplied.model_dump())
        if r.recorded_at > known_at or r.cutoff > as_of:
            continue
        _id(r.id)
        if r.revision < 1 or set(r.sales) != dishes:
            raise ValueError(
                "Complete daily dish manifest and positive revision required"
            )
        key = (r.day, r.revision)
        if key in seen:
            if seen[key] != r:
                raise ValueError("Conflicting daily revision")
            continue
        if r.id in ids:
            raise ValueError("Duplicate daily identity")
        ids.add(r.id)
        seen[key] = r
        if r.day not in selected or selected[r.day].revision < r.revision:
            selected[r.day] = r
    for day in selected:
        ordered = sorted(
            (r for (d, _), r in seen.items() if d == day), key=lambda r: r.revision
        )
        if any(
            a.cutoff != b.cutoff or a.recorded_at > b.recorded_at
            for a, b in pairwise(ordered)
        ):
            raise ValueError("Daily correction cutoff/recording order mismatch")
    return tuple(
        AuthoritativeDay(
            r.day,
            r.id,
            r.revision,
            r.cutoff,
            r.recorded_at,
            tuple(sorted(r.sales.items())),
            r.reconciliation.model_dump_json() if r.reconciliation else None,
        )
        for _, r in sorted(selected.items())
    )


def resolve_sales_threshold_policy(
    policy: SalesThresholdPolicy | None,
    *,
    known_at: datetime,
    captured_revision: str,
) -> SalesPolicyResolution:
    """Validate explicitly selected values and evidence against the frozen version.

    No default selection, coercion, evidence generation, persistence or IO.
    Missing/unknown/fixture/conflicting policies yield no usable policy plus
    findings. Malformed quantities/clocks raise ValueError/TypeError. Backend
    must still establish effective applicability and authoritative selection;
    matching reference strings alone cannot prove either fact.
    """
    known_at = _aware(known_at)
    _id(captured_revision)
    if policy is None:
        return SalesPolicyResolution(
            None, (Finding("MISSING_THRESHOLD_OR_EXPOSURE_POLICY", "policy"),)
        )
    issues = _evidence(
        policy.evidence,
        "threshold_policy",
        captured_revision,
        known_at,
    )
    if not policy.version or any(
        v is None
        for v in (
            policy.rule,
            policy.absolute_floor,
            policy.relative_threshold,
            policy.minimum_expected_portions,
            policy.minimum_complete_buckets,
        )
    ):
        issues.add(Finding("MISSING_THRESHOLD_OR_EXPOSURE_POLICY", "policy"))
        return SalesPolicyResolution(None, tuple(sorted(issues)))
    _id(policy.version)
    for value in (
        policy.absolute_floor,
        policy.relative_threshold,
        policy.minimum_expected_portions,
    ):
        assert value is not None
        _quantity(value)
    if (
        type(policy.minimum_complete_buckets) is not int
        or policy.minimum_complete_buckets < 1
    ):
        raise ValueError("Positive integer exposure bucket count required")
    if (policy.rule, policy.absolute_floor, policy.relative_threshold) != (
        RULE,
        Decimal(5),
        Decimal("0.2"),
    ):
        issues.add(Finding("UNSUPPORTED_THRESHOLD_POLICY", policy.version))
    if policy.version != SALES_MATERIALITY_V1.version:
        issues.add(Finding("UNSUPPORTED_SALES_POLICY_VERSION", policy.version))
    elif (
        policy.rule,
        policy.absolute_floor,
        policy.relative_threshold,
        policy.minimum_expected_portions,
        policy.minimum_complete_buckets,
    ) != (
        SALES_MATERIALITY_V1.rule,
        SALES_MATERIALITY_V1.absolute_floor,
        SALES_MATERIALITY_V1.relative_threshold,
        SALES_MATERIALITY_V1.minimum_expected_portions,
        SALES_MATERIALITY_V1.minimum_complete_buckets,
    ):
        issues.add(Finding("SALES_POLICY_VERSION_CONFLICT", policy.version))
    return SalesPolicyResolution(None if issues else policy, tuple(sorted(issues)))


def _policy(
    policy: SalesThresholdPolicy | None, contract: ProcurementContract
) -> set[Finding]:
    return set(
        resolve_sales_threshold_policy(
            policy,
            known_at=contract.known_at,
            captured_revision=contract.captured_state_revision,
        ).findings
    )


def _profile(profile: Sequence[ServicePeriod]) -> tuple:
    return tuple(sorted((p.start, p.end, p.weight) for p in profile))


def _basis(
    contract: ProcurementContract,
    issued: ForecastVersion | None,
    issued_input: ForecastInputArtifact | None,
    catalogue: Catalogue,
) -> set[Finding]:
    issues: set[Finding] = set()
    if contract.activity_semantics != ForecastActivitySemantics():
        issues.add(Finding("UNSUPPORTED_ACTIVITY_SEMANTICS", "contract"))
    if contract.policy.recorded_at > contract.known_at:
        issues.add(Finding("POLICY_NOT_YET_AVAILABLE", contract.policy.id))
    state = contract.frozen_state
    if state is None:
        return issues | {Finding("MISSING_FROZEN_STATE", "contract")}
    if not all(k in state for k in ("menu_items", "ingredients", "recipes")):
        return issues | {Finding("MISSING_CATALOGUE_RECIPE", "frozen_state")}
    current = Catalogue(
        menu_items=tuple(MenuItem.model_validate(r) for r in state["menu_items"]),
        ingredients=tuple(Ingredient.model_validate(r) for r in state["ingredients"]),
        recipes=tuple(RecipeItem.model_validate(r) for r in state["recipes"]),
    )
    if catalogue.content() != current.content():
        issues.add(Finding("CATALOGUE_RECIPE_MISMATCH", "issued_forecast"))
    if issued is None or issued_input is None:
        return issues | {Finding("NO_ISSUED_FORECAST_OR_INPUT", "forecast")}
    try:
        _validate_forecast(issued, catalogue.menu_items)
    except ValueError as exc:
        issues.add(Finding("INCOMPATIBLE_FORECAST", str(exc)))
    if (
        issued.known_at > contract.known_at
        or issued.as_of > contract.as_of
        or issued.as_of > min(p.start for p in issued.profile)
        or issued.actuals
    ):
        issues.add(Finding("UNSUPPORTED_COMPARISON_ORIGIN", "forecast"))
    # A result already reissued after elapsed activity cannot supply that period's
    # original expectation. Do not recalibrate using the sales being tested.
    artifact = contract.forecast_input
    if issued_input != artifact:
        issues.add(Finding("FROZEN_FORECAST_INPUT_CHANGED", artifact.id))
    if (
        artifact.recorded_at > issued.known_at
        or artifact.effective_at > issued.as_of
        or artifact.policy_version_id != contract.policy.id
        or set(artifact.payload.menu_item_ids) != {m.id for m in catalogue.menu_items}
        or artifact.payload.target_date != issued.target_date
        or any(
            r.available_at > issued.as_of or r.service_date >= issued.target_date
            for r in artifact.payload.history
        )
    ):
        issues.add(Finding("INCOMPATIBLE_FORECAST_INPUT", artifact.id))
    if (
        dict(issued.sources).get("history", SourceEvidence(None, None, None)).reference
        != artifact.id
    ):
        issues.add(Finding("FORECAST_INPUT_REFERENCE_MISMATCH", artifact.id))
    p = contract.policy.payload
    if issued.target_date != p.target_date or _profile(issued.profile) != _profile(
        [ServicePeriod(r.start, r.end, r.weight) for r in p.service_profile]
    ):
        issues.add(Finding("PROFILE_OR_TARGET_MISMATCH", contract.policy.id))
    if issued.promotion_state != "APPLIED":
        issues.add(Finding("MISSING_PROMOTION_AWARE_EXPECTATION", issued.reference))
    if not p.issue_time <= contract.as_of <= p.horizon_end:
        issues.add(Finding("UNSUPPORTED_OPERATIONAL_HORIZON", "contract"))
    return issues


def _risk(
    contract: ProcurementContract,
    risk: RiskSnapshot | None,
    issued: ForecastVersion | None,
    catalogue: Catalogue,
    basis_issues: set[Finding],
) -> tuple[
    InventoryProjection | None, tuple[SafetyBreach, ...], set[Finding], bool, bool
]:
    # Retains the earlier materiality prototype's projector and safety arithmetic,
    # now binding it to canonical frozen operational and commitment payloads.
    if risk is None:
        return None, (), {Finding("MISSING_PROJECTION_INPUT", "risk")}, False, False
    inv = risk.inventory
    issues = set(basis_issues)
    rev, known = contract.captured_state_revision, contract.known_at
    plan_issues = _evidence(risk.plan_evidence, "active_plan", rev, known)
    if (
        inv["as_of"] != contract.as_of
        or inv["known_at"] != known
        or inv["captured_revision"] != rev
        or inv["horizon_end"] != contract.policy.payload.horizon_end
        or inv["target_date"] != contract.policy.payload.target_date
    ):
        issues.add(Finding("CURRENT_STATE_MISMATCH", "risk"))
    cat = Catalogue(
        menu_items=tuple(inv["menu_items"]),
        ingredients=tuple(inv["ingredients"]),
        recipes=tuple(inv["recipes"]),
    )
    if cat.content() != catalogue.content():
        issues.add(Finding("CATALOGUE_RECIPE_MISMATCH", "risk"))
    if inv["fixture_fefo"] != FEFO_POLICY:
        issues.add(Finding("UNSUPPORTED_FEFO_POLICY", "risk"))
    if issued:
        if tuple(inv["buckets"]) != tuple(
            b for b in issued.buckets if b.start >= contract.as_of
        ):
            issues.add(Finding("REMAINING_FORECAST_MISMATCH", "risk"))
        if _profile(inv["service_profile"]) != _profile(issued.profile):
            issues.add(Finding("PROFILE_OR_TARGET_MISMATCH", "risk"))
        if _ref(inv["evidence"].get("forecast")) != issued.reference:
            issues.add(Finding("FORECAST_REFERENCE_MISMATCH", "risk"))
        for key in ("catalogue", "recipe", "profile"):
            if _ref(inv["evidence"].get(key)) != _ref(dict(issued.sources).get(key)):
                issues.add(Finding("INCOMPATIBLE_SOURCE_VERSION", key))
    state = contract.frozen_state or {}
    opening = [
        EstimatedInventoryLot.model_validate(r) for r in state.get("inventory", [])
    ]
    if "inventory" not in state or sorted(opening, key=lambda r: r.id) != sorted(
        inv["opening_lots"], key=lambda r: r.id
    ):
        issues.add(Finding("FROZEN_OPENING_MISMATCH", "risk"))
    commitments = contract.commitment_projection
    if commitments is None:
        issues.add(Finding("MISSING_COMMITMENT_PROJECTION", "risk"))
    else:
        frozen_deliveries = {row["id"]: row for row in state.get("commitments", [])}
        if (
            "commitments" not in state
            or len(frozen_deliveries) != len(state["commitments"])
            or set(frozen_deliveries) != set(commitments.supply_manifest)
        ):
            issues.add(Finding("FIXED_COMMITMENTS_MISMATCH", "frozen_state"))
        if (
            commitments.as_of != contract.as_of
            or commitments.known_at != known
            or commitments.captured_state_revision != rev
            or set(commitments.supply_manifest) != set(inv["supply_manifest"])
        ):
            issues.add(Finding("COMMITMENT_CAPTURE_MISMATCH", "risk"))
        if not commitments.complete or commitments.findings:
            issues.add(Finding("INCOMPLETE_COMMITMENT_PROJECTION", "risk"))
        expected = sorted(commitments.supplies, key=lambda r: r.delivery.id)
        actual = sorted(inv["supplies"], key=lambda r: r.delivery.id)
        if len(expected) != len(actual):
            issues.add(Finding("FIXED_COMMITMENTS_MISMATCH", "risk"))
        for a, b in zip(expected, actual):
            raw_delivery = frozen_deliveries.get(a.delivery.id)
            if raw_delivery is None or a.delivery != Delivery.model_validate(
                raw_delivery
            ):
                issues.add(Finding("FIXED_COMMITMENTS_MISMATCH", a.delivery.id))
            if (a.delivery, a.expiry_date, a.projected_lot_id) != (
                b.delivery,
                b.expiry_date,
                b.projected_lot_id,
            ):
                issues.add(Finding("FIXED_COMMITMENTS_MISMATCH", a.delivery.id))
            # The transport expiry evidence retains the original offer revision;
            # projector capture evidence must resolve that reference in this bundle.
            if a.delivery.outstanding_quantity and (
                a.expiry_evidence is None
                or b.expiry_evidence is None
                or a.expiry_evidence.reference != b.expiry_evidence.reference
                or a.expiry_evidence.available_at != b.expiry_evidence.available_at
            ):
                issues.add(Finding("EXPIRY_EVIDENCE_MISMATCH", a.delivery.id))
    if issues:
        return None, (), issues | plan_issues, False, False
    if inv["as_of"] >= inv["horizon_end"]:
        return (
            None,
            (),
            {Finding("NO_REMAINING_PROJECTION_HORIZON", "risk")},
            False,
            False,
        )
    projection = project_inventory(**inv)
    issues.update(projection.findings)
    physical_complete = projection.complete and not issues
    safety_issues = _evidence(risk.safety_evidence, "safety", rev, known)
    if risk.safety_policy != SAFETY_POLICY:
        safety_issues.add(Finding("MISSING_OR_UNSUPPORTED_SAFETY_POLICY", "risk"))
    if dict(risk.safety) != contract.policy.payload.safety_stock:
        safety_issues.add(Finding("SAFETY_POLICY_MISMATCH", "risk"))
    for quantity in risk.safety.values():
        _quantity(quantity)
    safety_complete = physical_complete and not safety_issues
    breaches = tuple(
        SafetyBreach(
            r.ingredient_id,
            b.end,
            _decimal(Fraction(risk.safety[r.ingredient_id]) - Fraction(r.closing)),
        )
        for b in projection.buckets or ()
        for r in b.ingredients
        if safety_complete and r.closing < risk.safety[r.ingredient_id]
    )
    return (
        projection,
        breaches,
        issues | safety_issues | plan_issues,
        physical_complete,
        safety_complete,
    )


def assess_sales_materiality(
    contract: ProcurementContract,
    *,
    issued_forecast: ForecastVersion | None,
    issued_input: ForecastInputArtifact | None,
    issued_catalogue: Catalogue,
    snapshot_evidence: SourceEvidence | None,
    threshold_policy: SalesThresholdPolicy | None,
    risk: RiskSnapshot | None,
) -> MaterialityResult:
    """Assess SALES_UPDATED evidence; never returns an Agent outcome or mutates inputs.

    Invalid structure raises ValueError/TypeError. Missing/incompatible evidence
    yields findings and nullable materiality. Known material evidence wins over
    incomplete other checks. False requires all three complete declared checks.
    """
    # Canonical models are mutable; copy before doing any work, and emit only
    # immutable numerical records or the existing immutable projector result.
    c = ProcurementContract.model_validate(contract.model_dump())
    _id(c.captured_state_revision)
    issues = _evidence(
        snapshot_evidence, "snapshot", c.captured_state_revision, c.known_at
    )
    if not c.run_id:
        issues.add(Finding("MISSING_RUN_REFERENCE", "contract"))
    basis_issues = _basis(c, issued_forecast, issued_input, issued_catalogue)
    issues.update(basis_issues)
    state = c.frozen_state or {}
    sales_issues = set(basis_issues) | set(issues)
    policy_issues = _policy(threshold_policy, c)
    dishes = sorted(m.id for m in issued_catalogue.menu_items)
    expected_intervals = allocate_service_buckets(
        {d: Decimal(0) for d in dishes},
        issued_catalogue.menu_items,
        target_date=c.policy.payload.target_date,
        profile=[
            ServicePeriod(p.start, p.end, p.weight)
            for p in c.policy.payload.service_profile
        ],
    )
    if any(b.start < c.as_of < b.end for b in expected_intervals):
        sales_issues.add(Finding("UNSUPPORTED_PARTIAL_INTERVAL", "as_of"))
    elapsed = tuple((b.start, b.end) for b in expected_intervals if b.end <= c.as_of)
    if "sales_batches" not in state:
        sales_issues.add(Finding("MISSING_SALES_MANIFEST", "frozen_state"))
    raw_sales = state.get("sales_batches", [])
    if any(row.get("recorded_at") is None for row in raw_sales):
        sales_issues.add(Finding("MISSING_SALES_RECORDING_TIME", "sales"))
    selected = select_sales_revisions(
        [row for row in raw_sales if row.get("recorded_at") is not None],
        as_of=c.as_of,
        known_at=c.known_at,
    )
    actuals: list[ObservedPortions] = []
    day_start = _aware(expected_intervals[0].start).replace(hour=0, minute=0)
    for batch, recorded in selected:
        # The canonical snapshot includes historical batches, not only today's.
        # Earlier complete intervals are history, not out-of-profile activity.
        if _aware(batch.period_end) <= day_start:
            continue
        if set(batch.sales) - set(dishes):
            raise ValueError("Unknown sales dish")
        bounds = (batch.period_start, batch.period_end)
        matches = [
            b
            for b in expected_intervals
            if batch.period_start < b.end and b.start < batch.period_end
        ]
        if bounds in elapsed:
            actuals.append(
                ObservedPortions(
                    *bounds,
                    tuple((d, batch.sales.get(d, 0)) for d in dishes),
                    batch.id,
                    batch.revision,
                    SourceEvidence(batch.id, recorded, c.captured_state_revision),
                )
            )
        elif matches or any(batch.sales.values()):
            sales_issues.add(Finding("UNSUPPORTED_SALES_INTERVAL", batch.id))
        # Explicit zero batches wholly outside service may establish Backend
        # midnight/count coverage; they add no forecast exposure.
    missing = tuple(b for b in elapsed if b not in {(a.start, a.end) for a in actuals})
    if missing:
        sales_issues.add(Finding("MISSING_SALES_INTERVALS", "sales"))
    deviations = []
    material_findings: set[Finding] = set()
    for dish in dishes:
        expected = (
            sum(
                (
                    Fraction(b.expected_portions[dish])
                    for b in issued_forecast.buckets
                    if (b.start, b.end) in elapsed
                ),
                Fraction(),
            )
            if issued_forecast and not basis_issues
            else None
        )
        observed = (
            sum((Fraction(dict(a.portions)[dish]) for a in actuals), Fraction())
            if not sales_issues
            else None
        )
        delta = (
            observed - expected
            if observed is not None and expected is not None
            else None
        )
        threshold = adequate = material = None
        if threshold_policy is not None and not policy_issues and expected is not None:
            assert (
                threshold_policy.absolute_floor is not None
                and threshold_policy.relative_threshold is not None
            )
            assert (
                threshold_policy.minimum_expected_portions is not None
                and threshold_policy.minimum_complete_buckets is not None
            )
            threshold = max(
                Fraction(threshold_policy.absolute_floor),
                expected * Fraction(threshold_policy.relative_threshold),
            )
            if not sales_issues:
                adequate = (
                    len(actuals) >= threshold_policy.minimum_complete_buckets
                    and expected >= threshold_policy.minimum_expected_portions
                )
                if adequate and delta is not None:
                    material = abs(delta) >= threshold
                else:
                    issues.add(Finding("INSUFFICIENT_EXPOSURE", dish))
        if material:
            material_findings.add(Finding("SALES_THRESHOLD_REACHED", dish))
        deviations.append(
            SalesDeviation(
                dish,
                _decimal(expected) if expected is not None else None,
                _decimal(observed) if observed is not None else None,
                _decimal(delta) if delta is not None else None,
                _decimal(threshold) if threshold is not None else None,
                adequate,
                material,
            )
        )
    remainder = None
    if not sales_issues and issued_forecast and issued_input:
        remainder = RemainingDemand(
            issued_forecast.reference,
            issued_forecast.base_reference,
            issued_input.artifact_id,
            issued_input.version,
            issued_input.model_dump_json(),
            c.as_of,
            c.known_at,
            c.captured_state_revision,
            tuple(actuals),
            tuple(b for b in issued_forecast.buckets if b.start >= c.as_of),
            issued_forecast.sources,
        )
    daily = None
    if "daily_history" not in state or "authoritative_daily_sales" not in state:
        issues.add(Finding("MISSING_DAILY_HISTORY_MANIFEST", "frozen_state"))
    else:
        revisions = []
        for raw in state["daily_history"]:
            # planning._snapshot freezes raw daily_revisions rows; unlike the
            # daily-history GET response, counts/sales live under payload.
            # Reuse the canonical DailyDraft/Revision models without fetching IO.
            if "payload" in raw:
                payload = DailyDraft.model_validate(raw["payload"])
                if payload.cutoff != _clock(raw["cutoff"]):
                    raise ValueError("Frozen daily payload cutoff mismatch")
                raw = {**raw, **payload.model_dump()}
            revisions.append(DailyRevision.model_validate(raw))
        daily = select_daily_history(
            revisions,
            issued_catalogue.menu_items,
            as_of=c.as_of,
            known_at=c.known_at,
        )
        # Verify the already-selected Backend summary, preserving comparisons.
        summary = {
            r["day"]: (r["revision_id"], _clock(r["cutoff"]), r["sales"], r["source"])
            for r in state["authoritative_daily_sales"]
        }
        selected_daily = {
            r.day.isoformat(): (
                r.revision_id,
                r.cutoff,
                dict(r.portions),
                "DAILY_FINAL",
            )
            for r in daily
        }
        if (
            len(summary) != len(state["authoritative_daily_sales"])
            or summary != selected_daily
        ):
            issues.add(Finding("AUTHORITATIVE_DAILY_MISMATCH", "frozen_state"))
            daily = None
    projection, breaches, risk_issues, physical_complete, safety_complete = _risk(
        c,
        risk,
        issued_forecast,
        issued_catalogue,
        basis_issues
        | _evidence(
            snapshot_evidence, "snapshot", c.captured_state_revision, c.known_at
        ),
    )
    issues.update(sales_issues | policy_issues | risk_issues)
    shortages = (
        projection.first_shortages or () if projection and physical_complete else ()
    )
    for s in shortages:
        material_findings.add(Finding("PHYSICAL_SHORTAGE", s.ingredient_id))
    for b in breaches:
        material_findings.add(Finding("SAFETY_STOCK_BREACH", b.ingredient_id))
    affected = {f.source for f in material_findings}
    affected.update(
        r.ingredient_id for r in issued_catalogue.recipes if r.menu_item_id in affected
    )
    first_shortage = min(
        shortages, key=lambda s: (s.start, s.end, s.ingredient_id), default=None
    )
    first_safety = min((b.at for b in breaches), default=None)
    first_risk = min(
        (
            t
            for t in (first_safety, first_shortage.start if first_shortage else None)
            if t is not None
        ),
        default=None,
    )
    refs = {
        _ref(snapshot_evidence),
        _ref(threshold_policy.evidence) if threshold_policy else None,
        c.forecast_input.id,
        c.policy.id,
    }
    if issued_forecast:
        refs.add(issued_forecast.reference)
        refs.update(e.reference for _, e in issued_forecast.sources)
        refs.add(_ref(issued_forecast.context_evidence))
    refs.update(a.evidence.reference for a in actuals)
    if risk:
        refs.update((_ref(risk.plan_evidence), _ref(risk.safety_evidence)))
        refs.update(e.reference for e in risk.inventory["evidence"].values())
    hard = bool(shortages or breaches)
    assessed = []
    if all(r.material is not None for r in deviations):
        assessed.append(CHECKS[0])
    if physical_complete:
        assessed.append(CHECKS[1])
    if safety_complete:
        assessed.append(CHECKS[2])
    follow_up = {"BACKEND_FRESHNESS_AND_APPROVAL_CHECKS"}
    if issues:
        follow_up.add("RESOLVE_INCOMPLETE_EVIDENCE")
    if material_findings:
        follow_up.add("INVESTIGATE_RISK_OR_DEVIATION")
    return MaterialityResult(
        True if material_findings else None if issues else False,
        not issues,
        False if hard else None,
        False if hard else True if safety_complete and not issues else None,
        tuple(assessed),
        tuple(deviations),
        projection,
        breaches,
        first_shortage,
        first_safety,
        first_risk,
        tuple(sorted(affected)),
        elapsed,
        missing,
        remainder,
        daily,
        tuple(sorted(issues)),
        tuple(sorted(material_findings)),
        tuple(sorted(r for r in refs if r)),
        tuple(sorted(follow_up)),
        c.run_id,
        _ref(snapshot_evidence),
        c.as_of,
        c.known_at,
        c.captured_state_revision,
        issued_forecast.reference if issued_forecast else None,
        c.forecast_input.id,
        threshold_policy.version if threshold_policy else None,
        c.policy.payload.horizon_end,
    )

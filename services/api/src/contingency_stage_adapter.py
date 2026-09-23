"""Read-only numerical check of the exact staged contingency run.

This intentionally cannot publish a plan or authorize the synthetic emergency
offer. It proves that the frozen Backend facts map into the numerical contract.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from src.contingency import (
    EVIDENCE,
    ContingencyInputs,
    MultiDayInputs,
    search_contingency,
    validate_contingency,
)
from src.contingency_run_contracts import StagedContingencyCase
from src.coverage import CoverageResult, ProtectedWindow
from src.errors import ApiError
from src.inventory_projection import SOURCE_NAMES, SourceEvidence
from src.inventory_tools import _commitment_supplies
from src.planning_schemas import PlanningRun
from src.procurement import OrderingOpportunity
from src.promotion_forecasting import SOURCES, ForecastVersion
from src.service_buckets import ProjectedDemandBucket, ServicePeriod


class StagedCandidateLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str
    quantity: Decimal
    unit: str


class StagedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    source: str


class StagedContingencyDiagnostic(BaseModel):
    """A numerical result that is explicitly ineligible for plan publication."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["STAGED_DIAGNOSTIC"] = "STAGED_DIAGNOSTIC"
    actionable: Literal[False] = False
    run_id: str
    captured_state_revision: str
    policy_version_id: str
    case_input_id: str
    search_status: str
    search_complete: bool
    reason: str | None
    findings: list[StagedFinding]
    candidate_lines: list[StagedCandidateLine]
    validation_complete: bool | None
    validation_feasible: bool | None
    cash_total_sgd: Decimal | None


def _inputs(run: PlanningRun, staged: StagedContingencyCase) -> ContingencyInputs:
    if staged.status != "STAGED_MATCH":
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Staged case does not match run")
    policy_version = staged.policy
    case_version = staged.case_input
    opening_lots = staged.opening_lots
    projection = staged.commitment_projection
    if (
        policy_version is None
        or case_version is None
        or opening_lots is None
        or projection is None
        or staged.run_id != run.id
        or staged.captured_state_revision != str(run.input_revision)
        or staged.as_of != run.as_of
        or staged.known_at != datetime.fromisoformat(run.snapshot["known_at"])
    ):
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Staged run evidence is incomplete"
        )
    policy = policy_version.payload
    case = case_version.payload
    menu = case.catalogue_menu_items
    ingredients = case.catalogue_ingredients
    recipes = case.catalogue_recipes
    suppliers = case.catalogue_suppliers
    recipe_manifest = case.recipe_manifest
    if (
        menu is None
        or ingredients is None
        or recipes is None
        or suppliers is None
        or recipe_manifest is None
        or case.catalogue_sha256 is None
        or policy.activation_state != "STAGED"
    ):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Staged catalogue is incomplete")

    revision = staged.captured_state_revision
    known_at = staged.known_at
    policy_evidence = SourceEvidence(
        policy_version.id, policy_version.recorded_at, revision
    )
    case_evidence = SourceEvidence(case_version.id, case_version.recorded_at, revision)
    snapshot_evidence = SourceEvidence(run.id, known_at, revision)
    opening_evidence = SourceEvidence(
        run.snapshot["inventory_snapshot_id"], known_at, revision
    )
    catalogue_evidence = SourceEvidence(
        case.catalogue_sha256, case_version.recorded_at, revision
    )
    supply_evidence = SourceEvidence(
        f"{run.id}:commitment-projection", known_at, revision
    )
    forecast_end = max(day.buckets[-1].end for day in case.forecasts)
    coverage = CoverageResult(
        policy.issue_time,
        known_at,
        revision,
        tuple(case.ingredient_ids),
        True,
        tuple(
            ProtectedWindow(
                ingredient_id,
                policy.issue_time,
                policy.protected_end[ingredient_id],
                None,
                policy.protected_end[ingredient_id].date(),
                policy_version.id,
            )
            for ingredient_id in case.ingredient_ids
        ),
        forecast_end,
        (),
        (),
        (("catalogue", catalogue_evidence), ("policy", policy_evidence)),
        policy.max_horizon_days,
        "EXPLICIT_STAGED_CASE_V2",
        policy.expiry_policy,
    )
    forecasts = [
        ForecastVersion(
            f"{case_version.id}:forecast:{day.target_date.isoformat()}",
            staged.as_of,
            known_at,
            day.target_date,
            tuple(ServicePeriod(row.start, row.end, row.weight) for row in day.profile),
            tuple(
                (
                    source,
                    catalogue_evidence
                    if source in {"catalogue", "recipe"}
                    else case_evidence,
                )
                for source in sorted(SOURCES)
            ),
            tuple(
                ProjectedDemandBucket(row.start, row.end, row.expected_portions)
                for row in day.buckets
            ),
            day.promotion_state,
            f"{case_version.id}:forecast:{day.target_date.isoformat()}",
        )
        for day in case.forecasts
    ]
    supplies, supply_manifest = _commitment_supplies(projection)
    # Backend stores the source delivery-event ID; the numerical kernel expects
    # the enclosing captured state revision. Preserve both in the source ref.
    supplies = [
        replace(
            supply,
            expiry_evidence=SourceEvidence(
                f"{supply.expiry_evidence.reference}:event:"
                f"{supply.expiry_evidence.captured_revision}",
                supply.expiry_evidence.available_at,
                revision,
            ),
        )
        if supply.expiry_evidence is not None
        else supply
        for supply in supplies
    ]
    evidence = {
        "snapshot": snapshot_evidence,
        "opening": opening_evidence,
        "supply": supply_evidence,
        "catalogue": catalogue_evidence,
        "recipe": catalogue_evidence,
        "forecast": case_evidence,
        "profile": case_evidence,
        "constraints": policy_evidence,
    }
    if set(evidence) != SOURCE_NAMES | {"constraints"}:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Projection evidence is incomplete"
        )
    inventory: MultiDayInputs = {
        "coverage": coverage,
        "forecasts": forecasts,
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "opening_lots": opening_lots,
        "supplies": supplies,
        "opening_manifest": {
            ingredient_id: [
                lot.id for lot in opening_lots if lot.ingredient_id == ingredient_id
            ]
            for ingredient_id in case.ingredient_ids
        },
        "supply_manifest": supply_manifest,
        "recipe_manifest": recipe_manifest,
        "evidence": evidence,
        "safety": policy.safety_stock,
        "storage": policy.storage_limits,
        "assessment_end": policy.assessment_end,
        "constraint_policy": policy.constraint_policy,
        "fefo_policy": policy.fefo_policy,
    }
    opportunities = [
        OrderingOpportunity(
            row.opportunity_id,
            row.offer_id,
            row.ordered_at,
            row.arrival_at,
            row.kind,
            row.expiry_date,
            SourceEvidence(row.source_revision, case_version.recorded_at, revision),
        )
        for row in case.opportunities
    ]
    shipment_groups: dict[str, str] = {}
    for row in case.opportunities:
        if row.shipment_group_id is None:
            raise ApiError(409, "MISSING_REQUIRED_DATA", "Shipment group is unknown")
        shipment_groups[row.opportunity_id] = row.shipment_group_id
    offers = {row.offer_id: row.offer for row in case.offers}
    if any(
        offers[row.offer_id].available_quantity is None
        or offers[row.offer_id].pack_size is None
        for row in case.opportunities
    ):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Staged offer capacity is unknown")
    policies = {
        "contingency": policy.objective_policy,
        "search": policy.search_policy,
        "fee": policy.fee_policy,
        "cash": policy.cash_policy,
        "expiry": policy.expiry_policy,
        "tie": policy.tie_break_policy,
        "reliability": policy.reliability_mode,
    }
    evidence_by_name = {
        name: case_evidence if name in {"domain", "shipments"} else policy_evidence
        for name in EVIDENCE
    }
    return ContingencyInputs(
        inventory,
        suppliers,
        [row.offer for row in case.offers],
        case.approved_offer_manifest,
        opportunities,
        case.opportunity_manifest,
        shipment_groups,
        {
            row.opportunity_id: int(
                cast(Decimal, offers[row.offer_id].available_quantity)
                // cast(Decimal, offers[row.offer_id].pack_size)
            )
            for row in case.opportunities
        },
        policy.new_order_budget_sgd,
        policies,
        evidence_by_name,
        {
            row.offer_id: SourceEvidence(
                row.source_revision, case_version.recorded_at, revision
            )
            for row in case.offers
        },
        policy.work_limit,
    )


def evaluate_staged_case(run: PlanningRun) -> StagedContingencyDiagnostic:
    """Calculate from the frozen run only; the output cannot become a plan."""
    raw = run.snapshot.get("staged_contingency_case")
    if raw is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "No staged case for this run")
    staged = StagedContingencyCase.model_validate(raw)
    inputs = _inputs(run, staged)
    result = search_contingency(inputs)
    validation = (
        validate_contingency(inputs, result.candidate)
        if result.candidate is not None
        else None
    )
    if validation is not None and result.validation != validation:
        raise ApiError(409, "POLICY_VIOLATION", "Staged validation result disagrees")
    if staged.policy is None or staged.case_input is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Staged authority is missing")
    return StagedContingencyDiagnostic(
        run_id=run.id,
        captured_state_revision=str(run.input_revision),
        policy_version_id=staged.policy.id,
        case_input_id=staged.case_input.id,
        search_status=result.status,
        search_complete=result.search_complete,
        reason=result.reason,
        findings=[
            StagedFinding(code=row.code, source=row.source) for row in result.findings
        ],
        candidate_lines=[
            StagedCandidateLine(
                opportunity_id=line.opportunity_id,
                quantity=line.quantity,
                unit=line.unit,
            )
            for line in (result.candidate.purchase.lines if result.candidate else ())
        ],
        validation_complete=validation.complete if validation else None,
        validation_feasible=validation.feasible if validation else None,
        cash_total_sgd=validation.cash.total
        if validation and validation.cash
        else None,
    )

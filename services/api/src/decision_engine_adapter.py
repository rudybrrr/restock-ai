"""Backend-owned bridge from a claimed procurement contract to pure kernels."""

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import update
from sqlalchemy.orm import Session

from src import database as db
from src.agent_contracts import (
    AgentToolName,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    ToolRequest,
    ToolResult,
)
from src.errors import ApiError, ErrorDetail, ErrorResponse
from src.forecasting import DailySalesObservation, seasonal_baseline
from src.inventory_projection import SourceEvidence
from src.planning_schemas import Candidate, PlanLine
from src.procurement import (
    EVIDENCE,
    DatedRequirement,
    OrderingOpportunity,
    ProcurementInputs,
    ProjectionInputs,
    search_procurement,
    validate_candidate,
)
from src.procurement_contract_schemas import ProcurementContract
from src.requirements import calculate_requirements
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
)
from src.service_buckets import ServicePeriod, allocate_service_buckets


def _identity(value: object) -> str:
    encoded = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _json(value: object) -> object:
    """Produce PostgreSQL JSON-safe immutable artifact content."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def run_first_slice_engine(session: Session, run) -> dict:
    """Calculate and persist immutable engine artifacts for one claimed run.

    This is the sole production mapping into Aniq's internal numerical types.
    Agent callers receive only references to the persisted Backend artifacts.
    """
    raw_contract = run.snapshot.get("procurement_contract")
    if raw_contract is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Frozen procurement contract missing")
    contract = ProcurementContract.model_validate(raw_contract)
    if contract.run_id != run.id or contract.captured_state_revision != str(run.input_revision):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Frozen contract revision mismatch")
    frozen = contract.frozen_state
    if frozen is None or frozen.get("commitments") or frozen.get("sales_batches"):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Frozen baseline is incomplete")

    policy = contract.policy.payload
    history = [
        DailySalesObservation(
            row.service_date,
            row.available_at,
            row.revision,
            row.portions,
            row.promotion,
            row.censored,
        )
        for row in contract.forecast_input.payload.history
    ]
    menu = [MenuItem.model_validate(row) for row in frozen["menu_items"]]
    ingredients = [Ingredient.model_validate(row) for row in frozen["ingredients"]]
    recipes = [RecipeItem.model_validate(row) for row in frozen["recipes"]]
    forecast = seasonal_baseline(
        history, menu, issue_time=policy.issue_time, target_date=policy.target_date
    )
    if any(row.expected_portions is None for row in forecast.values()):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Forecast history is insufficient")
    daily = {
        key: row.expected_portions
        for key, row in forecast.items()
        if row.expected_portions is not None
    }
    if len(daily) != len(forecast):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Forecast output is incomplete")
    profile = [ServicePeriod(item.start, item.end, item.weight) for item in policy.service_profile]
    buckets = allocate_service_buckets(daily, menu, target_date=policy.target_date, profile=profile)
    revision = contract.captured_state_revision
    available = contract.known_at
    source = SourceEvidence(contract.forecast_input.source_revision, available, revision)
    inventory: ProjectionInputs = {
        "opening_lots": [EstimatedInventoryLot.model_validate(row) for row in frozen["inventory"]],
        "buckets": buckets,
        "menu_items": menu,
        "ingredients": ingredients,
        "recipes": recipes,
        "supplies": [],
        "as_of": contract.as_of,
        "target_date": policy.target_date,
        "horizon_end": policy.horizon_end,
        "known_at": contract.known_at,
        "captured_revision": revision,
        "opening_manifest": {
            item.id: [lot["id"] for lot in frozen["inventory"] if lot["ingredient_id"] == item.id]
            for item in ingredients
        },
        "supply_manifest": [],
        "recipe_manifest": [(item.menu_item_id, item.ingredient_id) for item in recipes],
        "service_profile": profile,
        "evidence": {key: source for key in ("snapshot", "opening", "supply", "catalogue", "recipe", "forecast", "profile")},
        "fixture_fefo": policy.fefo_policy,
    }
    requirements = [
        DatedRequirement(bucket.start, bucket.end, calculate_requirements(bucket.expected_portions, menu, ingredients, recipes))
        for bucket in buckets
    ]
    eligible_domain_offers = [
        row
        for row in contract.domain.offers
        if row.offer.current_status == "AVAILABLE"
        and row.offer.available_quantity is not None
        and row.offer.available_quantity > 0
    ]
    offers = [row.offer for row in eligible_domain_offers]
    offer_by_id = {row.offer_id: row.offer for row in eligible_domain_offers}
    if any(
        offer.available_quantity is None
        or offer.pack_size is None
        or offer.unit_price is None
        for offer in offers
    ):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Approved offer is incomplete")
    opportunities = [
        OrderingOpportunity(row.opportunity_id, row.offer_id, row.ordered_at, row.arrival_at, row.kind, row.expiry_date, SourceEvidence(row.source_revision, available, revision))
        for row in contract.domain.opportunities
        if row.offer_id in offer_by_id
    ]
    inputs = ProcurementInputs(
        inventory=inventory,
        issue_time=policy.issue_time,
        requirements=requirements,
        suppliers=[Supplier(id=row, name=row) for row in policy.approved_supplier_ids],
        offers=offers,
        approved_offer_manifest=[
            (row.offer_id, row.supplier_id, row.ingredient_id)
            for row in eligible_domain_offers
        ],
        opportunities=opportunities,
        safety=policy.safety_stock,
        storage=policy.storage_limits,
        budget=policy.new_order_budget_sgd,
        fee_policy=policy.fee_policy,
        tie_policy=policy.tie_break_policy,
        expiry_policy=policy.new_supply_expiry_policy,
        cash_policy=policy.objective_policy,
        policy_evidence={key: source for key in EVIDENCE},
        offer_evidence={
            row.offer_id: SourceEvidence(row.source_revision, available, revision)
            for row in eligible_domain_offers
        },
        max_packs={
            opportunity.id: int(
                cast(Decimal, offer_by_id[opportunity.offer_id].available_quantity)
                // cast(Decimal, offer_by_id[opportunity.offer_id].pack_size)
            )
            for opportunity in opportunities
        },
        work_limit=10000,
        search_policy=policy.search_policy,
    )
    input_id = "engine-input:" + _identity(contract.model_dump(mode="json"))
    result = search_procurement(inputs)
    if result.status == "INFEASIBLE_IN_DOMAIN":
        raise ApiError(409, "NO_FEASIBLE_SUPPLIER", "Approved procurement domain is infeasible")
    if not result.search_complete or result.candidate is None:
        raise ApiError(
            409, "CALCULATION_INCOMPLETE", "Decision Engine search did not complete"
        )
    validation = validate_candidate(inputs, result.candidate)
    if not validation.complete or not validation.feasible or validation.cash is None:
        raise ApiError(409, "POLICY_VIOLATION", "Independent candidate validation failed")
    opportunity_by_id = {row.opportunity_id: row for row in contract.domain.opportunities}
    candidate = Candidate(
        calculation_mode="ENGINE",
        forecast_id=run.snapshot["forecast_id"],
        inventory_snapshot_id=run.snapshot["inventory_snapshot_id"],
        lines=[PlanLine(ingredient_id=offer_by_id[opportunity_by_id[line.opportunity_id].offer_id].ingredient_id, supplier_id=offer_by_id[opportunity_by_id[line.opportunity_id].offer_id].supplier_id, offer_id=opportunity_by_id[line.opportunity_id].offer_id, opportunity_id=line.opportunity_id, shipment_group_id=f"{offer_by_id[opportunity_by_id[line.opportunity_id].offer_id].supplier_id}:{opportunity_by_id[line.opportunity_id].arrival_at.isoformat()}", quantity=line.quantity, unit_price=cast(Decimal, offer_by_id[opportunity_by_id[line.opportunity_id].offer_id].unit_price), arrival_at=opportunity_by_id[line.opportunity_id].arrival_at) for line in result.candidate.lines],
        total_purchase_cost=validation.cash.acquisition,
        delivery_cost=validation.cash.delivery,
        emergency_penalty=validation.cash.emergency,
        total_expected_cost=validation.cash.total,
    )
    candidate_id = "candidate:" + _identity(candidate.model_dump(mode="json"))
    validation_id = "validation:" + _identity({"candidate": candidate_id, "cash": asdict(validation.cash)})
    artifacts = {"input": {"id": input_id, "contract": contract.model_dump(mode="json")}, "candidate": {"id": candidate_id, "candidate": candidate.model_dump(mode="json"), "engine_lines": [asdict(line) for line in result.candidate.lines]}, "validation": {"id": validation_id, "candidate_id": candidate_id, "complete": True, "feasible": True, "cash": asdict(validation.cash)}}
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run.id)
        .values(
            snapshot={
                **run.snapshot,
                "decision_engine_artifacts": _json(artifacts),
                "calculated_candidate": candidate.model_dump(mode="json"),
            }
        )
    )
    session.commit()
    return artifacts


class BackendProcurementTools:
    """Agent-facing references over Backend-owned engine artifacts only."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _ref(request: ToolRequest, category: EvidenceCategory, source: EvidenceSource, reference_id: str) -> EvidenceRef:
        return EvidenceRef(
            category=category,
            source=source,
            reference_id=reference_id,
            state_revision=request.captured_state_revision,
            run_id=request.run_id,
            specialist_call_id=request.tool_call_id.rsplit("-TOOL-", 1)[0],
            tool_call_id=request.tool_call_id,
            producer_tool=request.tool,
            call_sequence=int(request.tool_call_id.rsplit("-TOOL-", 1)[1]),
        )

    def execute(self, request: ToolRequest) -> ToolResult | ErrorResponse:
        """Expose no numerical input/output surface to the specialist."""
        try:
            from src.planning import get_run

            run = get_run(self._session, request.run_id)
            if str(run.input_revision) != request.captured_state_revision:
                raise ApiError(409, "STATE_REVISION_STALE", "Backend run revision changed")
            if request.tool is AgentToolName.GET_SUPPLIER_OPTIONS:
                contract = ProcurementContract.model_validate(run.snapshot.get("procurement_contract"))
                output = self._ref(
                    request, EvidenceCategory.SUPPLIER_STATE, EvidenceSource.BACKEND,
                    contract.domain.id,
                )
                return ToolResult(tool_call_id=request.tool_call_id, run_id=request.run_id, tool=request.tool, output_ref=output)

            artifacts = run_first_slice_engine(self._session, run)
            if request.tool in (
                AgentToolName.CHECK_SUPPLIER_FEASIBILITY,
                AgentToolName.ENUMERATE_SUPPLIER_ALLOCATIONS,
            ):
                output = self._ref(
                    request, EvidenceCategory.SUPPLIER_STATE, EvidenceSource.DECISION_ENGINE,
                    artifacts["input"]["id"],
                )
                return ToolResult(tool_call_id=request.tool_call_id, run_id=request.run_id, tool=request.tool, output_ref=output)
            if request.tool is AgentToolName.OPTIMISE_PURCHASE_PLAN:
                output = self._ref(
                    request, EvidenceCategory.CANDIDATE_RESULT, EvidenceSource.DECISION_ENGINE,
                    artifacts["candidate"]["id"],
                )
                return ToolResult(
                    tool_call_id=request.tool_call_id, run_id=request.run_id, tool=request.tool,
                    output_ref=output,
                )
            if request.tool is AgentToolName.VALIDATE_PURCHASE_PLAN:
                output = self._ref(
                    request, EvidenceCategory.VALIDATION_RESULT, EvidenceSource.DECISION_ENGINE,
                    artifacts["validation"]["id"],
                )
                return ToolResult(tool_call_id=request.tool_call_id, run_id=request.run_id, tool=request.tool, output_ref=output)
            if request.tool is AgentToolName.GET_APPROVAL_REQUIREMENT:
                output = self._ref(request, EvidenceCategory.APPROVAL_REQUIREMENT, EvidenceSource.POLICY_ENGINE, "MANAGER_APPROVAL_REQUIRED")
                return ToolResult(tool_call_id=request.tool_call_id, run_id=request.run_id, tool=request.tool, output_ref=output)
            raise ApiError(422, "TOOL_NOT_SUPPORTED", "Unsupported Procurement tool")
        except ApiError as error:
            return ErrorResponse(error=ErrorDetail(code=error.detail.code, message=error.detail.message))

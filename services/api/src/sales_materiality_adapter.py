"""Backend adapter for production SALES_UPDATED materiality assessment."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src import planning
from src.demand_tools import BackendDemandTools
from src.errors import ApiError
from src.history_dataset import Catalogue
from src.inventory_projection import FEFO_POLICY, SourceEvidence
from src.inventory_tools import _commitment_supplies
from src.materiality import (
    SAFETY_POLICY,
    RiskSnapshot,
    SalesThresholdPolicy,
    assess_sales_materiality,
)
from src.operations_schemas import PromotionEvent
from src.procurement import ProjectionInputs
from src.procurement_contract_schemas import ProcurementContract
from src.promotion_forecasting import apply_promotions
from src.sales_materiality_contracts import (
    context_from_contract,
    create_request,
    read_assessment,
    required_for_run,
    save_result,
)
from src.sales_materiality_schemas import (
    SalesMaterialityRequestCreate,
    SalesMaterialityResult,
    SalesMaterialityResultWrite,
)
from src.sales_threshold_schemas import FrozenSalesThresholdPolicy
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem


def _json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, BaseModel):
        return _json(value.model_dump(mode="json"))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _catalogue(contract: ProcurementContract) -> Catalogue:
    frozen = contract.frozen_state or {}
    try:
        return Catalogue(
            menu_items=tuple(MenuItem.model_validate(row) for row in frozen["menu_items"]),
            ingredients=tuple(Ingredient.model_validate(row) for row in frozen["ingredients"]),
            recipes=tuple(RecipeItem.model_validate(row) for row in frozen["recipes"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Frozen catalogue is incomplete") from error


def _issued_forecast(run, contract: ProcurementContract):
    """Build the original promotion-aware forecast from frozen state only."""
    origin = run.snapshot.get("issued_forecast_origin")
    if origin is not None:
        contract = ProcurementContract.model_validate(origin["contract"])
        source_run_id = origin["run_id"]
        if contract.run_id != source_run_id:
            raise ApiError(409, "MISSING_REQUIRED_DATA", "Issued forecast origin is inconsistent")
    else:
        source_run_id = run.id
    normal = BackendDemandTools(cast(Session, None))._normal_forecast(
        contract, f"{source_run_id}:forecast:normal"
    )
    frozen = contract.frozen_state or {}
    raw_events = frozen.get("promotions")
    events = (
        [PromotionEvent.model_validate(row) for row in raw_events]
        if isinstance(raw_events, list)
        else []
    )
    context = SourceEvidence(
        f"{source_run_id}:promotion-context",
        contract.known_at,
        contract.captured_state_revision,
    )
    application = apply_promotions(
        normal,
        list(_catalogue(contract).menu_items),
        events=events,
        context_evidence=context,
        context_complete=isinstance(raw_events, list),
        as_of=contract.as_of,
        known_at=contract.known_at,
        result_reference=f"{source_run_id}:forecast:promotion",
    )
    return application.forecast if application.complete and application.forecast else normal


def _projection_inputs(
    contract: ProcurementContract, issued_forecast, catalogue: Catalogue
) -> ProjectionInputs:
    frozen = contract.frozen_state or {}
    policy = contract.policy.payload
    supplies, supply_manifest = _commitment_supplies(contract.commitment_projection)
    lots = [EstimatedInventoryLot.model_validate(row) for row in frozen.get("inventory", [])]
    source = SourceEvidence(
        contract.forecast_input.source_revision,
        contract.known_at,
        contract.captured_state_revision,
    )
    issued_sources = dict(issued_forecast.sources)
    evidence = {
        key: source
        for key in ("snapshot", "opening", "supply")
    }
    for key in ("catalogue", "recipe", "profile"):
        evidence[key] = SourceEvidence(
            issued_sources[key].reference,
            issued_sources[key].available_at,
            contract.captured_state_revision,
        )
    evidence["forecast"] = SourceEvidence(
        issued_forecast.reference,
        issued_forecast.known_at,
        contract.captured_state_revision,
    )
    return {
        "opening_lots": lots,
        "buckets": [b for b in issued_forecast.buckets if b.start >= contract.as_of],
        "menu_items": list(catalogue.menu_items),
        "ingredients": list(catalogue.ingredients),
        "recipes": list(catalogue.recipes),
        "supplies": supplies,
        "as_of": contract.as_of,
        "target_date": policy.target_date,
        "horizon_end": policy.horizon_end,
        "known_at": contract.known_at,
        "captured_revision": contract.captured_state_revision,
        "opening_manifest": {
            item.id: [lot.id for lot in lots if lot.ingredient_id == item.id]
            for item in catalogue.ingredients
        },
        "supply_manifest": supply_manifest,
        "recipe_manifest": [(item.menu_item_id, item.ingredient_id) for item in catalogue.recipes],
        "service_profile": list(issued_forecast.profile),
        "evidence": evidence,
        "fixture_fefo": FEFO_POLICY,
    }


def _threshold_policy(policy: FrozenSalesThresholdPolicy | None):
    if policy is None:
        return None
    evidence = policy.evidence
    return SalesThresholdPolicy(
        policy.version,
        policy.payload.rule,
        policy.payload.absolute_floor,
        policy.payload.relative_threshold,
        policy.payload.minimum_expected_portions,
        policy.payload.minimum_complete_buckets,
        SourceEvidence(evidence.reference, evidence.available_at, evidence.captured_revision),
    )


def _risk_snapshot(
    run, contract: ProcurementContract, forecast, catalogue: Catalogue
) -> RiskSnapshot | None:
    if (
        contract.commitment_projection is None
        or not contract.commitment_projection.complete
    ):
        return None
    plan_reference = run.snapshot.get("plan_version_reference")
    plan_evidence = (
        SourceEvidence(str(plan_reference), contract.known_at, contract.captured_state_revision)
        if plan_reference else None
    )
    try:
        inventory = _projection_inputs(contract, forecast, catalogue)
    except ApiError as error:
        if error.detail.code == "MISSING_REQUIRED_DATA":
            return None
        raise
    return RiskSnapshot(
        inventory,
        plan_evidence,
        dict(contract.policy.payload.safety_stock),
        SAFETY_POLICY,
        SourceEvidence(
            f"{run.id}:safety:{contract.captured_state_revision}",
            contract.known_at,
            contract.captured_state_revision,
        ),
    )


def _result_payload(result) -> SalesMaterialityResult:
    return SalesMaterialityResult.model_validate({
        "material_change": result.material_change,
        "complete": result.complete,
        "feasible_under_observed_state": result.feasible_under_observed_state,
        "inventory_feasible": result.inventory_feasible,
        "assessed_scope": list(result.assessed_scope),
        "sales": [_json(item) for item in result.sales],
        "projection": _json(result.projection),
        "safety_breaches": [_json(item) for item in result.safety_breaches],
        "first_stockout_interval": _json(result.first_stockout_interval),
        "first_safety_breach_at": result.first_safety_breach_at,
        "first_risk_at": result.first_risk_at,
        "affected_ids": list(result.affected_ids),
        "compared_intervals": [_json(item) for item in result.compared_intervals],
        "missing_intervals": [_json(item) for item in result.missing_intervals],
        "remainder": _json(result.remainder),
        "daily_history": _json(result.daily_history),
        "findings": [_json(item) for item in result.findings],
        "material_findings": [_json(item) for item in result.material_findings],
        "evidence_refs": list(result.evidence_refs),
        "required_follow_up": list(result.required_follow_up),
        "run_id": result.run_id,
        "snapshot_reference": result.snapshot_reference,
        "as_of": result.as_of,
        "known_at": result.known_at,
        "captured_state_revision": result.captured_state_revision,
        "forecast_reference": result.forecast_reference,
        "forecast_input_reference": result.forecast_input_reference,
        "threshold_policy_version": result.threshold_policy_version,
        "coverage_through": result.coverage_through,
        "limitations": list(result.limitations),
    })


def ensure_claimed_sales_materiality(session: Session, run_id: str) -> None:
    """Persist one deterministic assessment for a claimed SALES_UPDATED run."""
    if not required_for_run(session, run_id):
        return
    try:
        existing = read_assessment(session, run_id)
    except ApiError as error:
        if error.detail.code != "MATERIALITY_ASSESSMENT_NOT_FOUND":
            raise
        existing = None
    if existing is not None and existing.result is not None:
        return

    run = planning.get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Claimed run is no longer running")
    raw_contract = run.snapshot.get("procurement_contract")
    if raw_contract is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Frozen procurement contract missing")
    contract = ProcurementContract.model_validate(raw_contract)
    if contract.run_id != run.id or contract.captured_state_revision != str(run.input_revision):
        raise ApiError(409, "STATE_REVISION_STALE", "Frozen contract revision mismatch")
    context = context_from_contract(contract)
    catalogue = _catalogue(contract)
    forecast = _issued_forecast(run, contract)
    risk = _risk_snapshot(run, contract, forecast, catalogue)
    request = SalesMaterialityRequestCreate(
        request_id=existing.id if existing is not None else f"{run.id}:sales-materiality",
        captured_state_revision=context.captured_state_revision,
        as_of=context.as_of,
        known_at=context.known_at,
        issued_forecast_reference=forecast.reference,
        issued_forecast=forecast,
        plan_reference=run.snapshot.get("plan_version_reference"),
        safety_reference=f"{run.id}:safety:{context.captured_state_revision}",
        risk=(
            _json(
                {
                    "inventory": risk.inventory,
                    "plan_evidence": risk.plan_evidence,
                    "safety": risk.safety,
                    "safety_policy": risk.safety_policy,
                    "safety_evidence": risk.safety_evidence,
                }
            )
            if risk is not None
            else None
        ),
    )
    persisted = create_request(session, run.id, request)
    if persisted.result is not None:
        return
    numerical = assess_sales_materiality(
        contract,
        issued_forecast=forecast,
        issued_input=contract.forecast_input,
        issued_catalogue=catalogue,
        snapshot_evidence=SourceEvidence(
            context.snapshot_evidence.reference,
            context.snapshot_evidence.available_at,
            context.snapshot_evidence.captured_revision,
        ),
        threshold_policy=_threshold_policy(contract.sales_threshold_policy),
        risk=risk,
    )
    save_result(
        session,
        run.id,
        persisted.id,
        SalesMaterialityResultWrite(
            request_reference=persisted.request_reference,
            result=_result_payload(numerical),
        ),
    )

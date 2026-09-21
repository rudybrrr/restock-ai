"""Read-only Backend adapters for local inventory investigation."""

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from src.agent_contracts import (
    AgentToolName,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    ToolRequest,
    ToolResult,
)
from src.demand_tools import BackendDemandTools
from src.errors import ApiError, ErrorDetail, ErrorResponse
from src.inventory_projection import ExpectedSupply, SourceEvidence, project_inventory
from src.operations_schemas import Delivery
from src.planning import get_run
from src.procurement_contract_schemas import ProcurementContract
from src.promotion_forecasting import apply_promotions
from src.sales import estimated_inventory
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem


def _identity(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _commitment_supplies(projection) -> tuple[list[ExpectedSupply], list[str]]:
    """Adapt Backend's frozen commitment projection without re-counting receipts."""
    if projection is None or not projection.complete:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Frozen commitment projection is incomplete",
        )
    supplies: list[ExpectedSupply] = []
    for frozen in projection.supplies:
        delivery = Delivery.model_validate(frozen.delivery)
        evidence = frozen.expiry_evidence
        expiry_evidence = (
            SourceEvidence(
                evidence.reference,
                evidence.available_at,
                evidence.captured_revision,
            )
            if evidence is not None
            else None
        )
        if delivery.outstanding_quantity and (
            frozen.expiry_date is None
            or expiry_evidence is None
            or frozen.projected_lot_id is None
        ):
            raise ApiError(
                409,
                "MISSING_REQUIRED_DATA",
                "Outstanding commitment is missing projected-lot evidence",
            )
        supplies.append(
            ExpectedSupply(
                delivery,
                frozen.expiry_date,
                expiry_evidence,
                frozen.projected_lot_id,
            )
        )
    return supplies, list(projection.supply_manifest)


class BackendInventoryTools:
    """Read frozen state and call the established inventory projection kernel only."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _ref(
        request: ToolRequest,
        category: EvidenceCategory,
        source: EvidenceSource,
        identifier: str,
    ) -> EvidenceRef:
        return EvidenceRef(
            category=category,
            source=source,
            reference_id=identifier,
            state_revision=request.captured_state_revision,
            run_id=request.run_id,
            specialist_call_id=request.tool_call_id.rsplit("-TOOL-", 1)[0],
            tool_call_id=request.tool_call_id,
            producer_tool=request.tool.value,
            call_sequence=int(request.tool_call_id.rsplit("-TOOL-", 1)[1]),
        )

    def _result(
        self,
        request: ToolRequest,
        category: EvidenceCategory,
        source: EvidenceSource,
        identifier: str,
        data: dict,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            tool=request.tool,
            output_ref=self._ref(request, category, source, identifier),
            output_data=data,
        )

    def execute(self, request: ToolRequest) -> ToolResult | ErrorResponse:
        try:
            run = get_run(self._session, request.run_id)
            if str(run.input_revision) != request.captured_state_revision:
                raise ApiError(
                    409, "STATE_REVISION_STALE", "Backend run revision changed"
                )
            snapshot = run.snapshot
            if request.tool is AgentToolName.GET_INVENTORY_SNAPSHOT:
                if run.trigger == "INVENTORY_ADJUSTED":
                    from src.inventory_adjustment_contracts import context_from_run

                    context = context_from_run(run)
                    return self._result(
                        request,
                        EvidenceCategory.INVENTORY_SNAPSHOT,
                        EvidenceSource.BACKEND,
                        context.snapshot_reference,
                        {
                            "physical_fresh": True,
                            "investigation_required": False,
                            "authoritative_assessment_required": True,
                            "inventory_adjustment_context": context.snapshot_reference,
                            "adjustment_event_ids": [
                                event.id for event in context.adjustment_events
                            ],
                            "assessed_lot_ids": context.assessed_lot_ids,
                            "assessed_ingredient_ids": context.assessed_ingredient_ids,
                        },
                    )
                physical = snapshot.get("daily_history")
                if not isinstance(physical, list):
                    return self._result(
                        request,
                        EvidenceCategory.INVENTORY_SNAPSHOT,
                        EvidenceSource.BACKEND,
                        f"{run.id}:physical-inventory",
                        {"missing_required_data": True},
                    )
                # A normal manual check with an immutable snapshot does not need to
                # replay or project. Event runs are the authoritative reason to inspect.
                return self._result(
                    request,
                    EvidenceCategory.INVENTORY_SNAPSHOT,
                    EvidenceSource.BACKEND,
                    f"{run.id}:physical-inventory",
                    {
                        "physical_fresh": bool(physical),
                        "investigation_required": run.trigger
                        in {
                            "INVENTORY_ADJUSTED",
                            "INVENTORY_WASTED",
                            "DAILY_UPDATE_SUBMITTED",
                            "DAILY_UPDATE_CORRECTED",
                            "PROMOTION_CREATED",
                            "PROMOTION_CHANGED",
                            "SALES_UPDATED",
                            "DELIVERY_DELAYED",
                            "DELIVERY_SHORT",
                            "DELIVERY_CANCELLED",
                        },
                    },
                )
            if request.tool is AgentToolName.CALCULATE_ESTIMATED_INVENTORY:
                rows = estimated_inventory(
                    self._session, run.as_of, self._known_at(snapshot)
                )
                return self._result(
                    request,
                    EvidenceCategory.INVENTORY_SNAPSHOT,
                    EvidenceSource.BACKEND,
                    f"estimated:{_identity(rows)}",
                    {"estimated_available": bool(rows), "provenance": "ESTIMATED"},
                )
            projection = self._projection(
                run, snapshot, request.captured_state_revision
            )
            projection_id = f"inventory-projection:{_identity(self._projection_identity(projection))}"
            if request.tool is AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS:
                return self._result(
                    request,
                    EvidenceCategory.INVENTORY_PROJECTION,
                    EvidenceSource.DECISION_ENGINE,
                    f"requirements:{projection_id}",
                    {
                        "requirements_complete": projection.complete,
                        "provenance": "PROJECTED",
                    },
                )
            if request.tool is AgentToolName.PROJECT_INVENTORY:
                return self._result(
                    request,
                    EvidenceCategory.INVENTORY_PROJECTION,
                    EvidenceSource.DECISION_ENGINE,
                    projection_id,
                    {
                        "projection_complete": projection.complete,
                        "provenance": "PROJECTED",
                    },
                )
            if request.tool is AgentToolName.CALCULATE_EXPIRY_RISK:
                return self._result(
                    request,
                    EvidenceCategory.EXPIRY_RISK,
                    EvidenceSource.DECISION_ENGINE,
                    f"expiry:{projection_id}",
                    {
                        "projection_complete": projection.complete,
                        "provenance": "PROJECTED",
                    },
                )
            if request.tool is AgentToolName.CALCULATE_STOCKOUT_RISK:
                shortages = projection.first_shortages or ()
                stockout_exposure = bool(shortages)
                if run.trigger == "SALES_UPDATED":
                    from src.sales_materiality_contracts import result_for_completion

                    materiality = result_for_completion(self._session, run.id)
                    if (
                        materiality is None
                        or not materiality.complete
                        or materiality.material_change is None
                    ):
                        raise ApiError(
                            409,
                            "MISSING_REQUIRED_DATA",
                            "Sales materiality is incomplete",
                        )
                    stockout_exposure = (
                        materiality.inventory_feasible is not True
                        or materiality.first_stockout_interval is not None
                        or bool(materiality.safety_breaches)
                    )
                return self._result(
                    request,
                    EvidenceCategory.STOCKOUT_RISK,
                    EvidenceSource.DECISION_ENGINE,
                    f"stockout:{projection_id}",
                    {"stockout_exposure": stockout_exposure, "provenance": "PROJECTED"},
                )
            raise ApiError(422, "TOOL_NOT_SUPPORTED", "Unsupported Inventory tool")
        except ApiError as error:
            return ErrorResponse(
                error=ErrorDetail(code=error.detail.code, message=error.detail.message)
            )
        except (KeyError, TypeError, ValueError) as error:
            return ErrorResponse(
                error=ErrorDetail(code="MISSING_REQUIRED_DATA", message=str(error))
            )

    @staticmethod
    def _known_at(snapshot: dict):
        value = snapshot.get("known_at")
        if not isinstance(value, str):
            raise TypeError("Frozen known_at is unavailable")
        return datetime.fromisoformat(value)

    def _projection(self, run, snapshot: dict, revision: str):
        contract = self._contract(snapshot, run.id, revision)
        frozen = contract.frozen_state or snapshot
        supplies, supply_manifest = _commitment_supplies(contract.commitment_projection)
        menu = [MenuItem.model_validate(row) for row in frozen.get("menu_items", [])]
        ingredients = [
            Ingredient.model_validate(row) for row in frozen.get("ingredients", [])
        ]
        recipes = [RecipeItem.model_validate(row) for row in frozen.get("recipes", [])]
        policy = contract.policy.payload
        forecast_adapter = BackendDemandTools(self._session)
        normal = forecast_adapter._normal_forecast(contract, f"{run.id}:forecast:normal")
        if run.trigger in {"PROMOTION_CREATED", "PROMOTION_CHANGED"}:
            application = apply_promotions(
                normal,
                menu,
                events=forecast_adapter._promotion_events(run.id, contract.known_at),
                context_evidence=SourceEvidence(
                    f"{run.id}:promotion-context",
                    contract.known_at,
                    contract.captured_state_revision,
                ),
                context_complete=isinstance(snapshot.get("promotions"), list),
                as_of=contract.as_of,
                known_at=contract.known_at,
                result_reference=f"{run.id}:forecast:promotion",
            )
            if not application.complete or application.forecast is None:
                raise ApiError(
                    409,
                    "CALCULATION_INCOMPLETE",
                    "Frozen promotion forecast application is incomplete",
                )
            buckets = list(application.forecast.buckets)
            profile = list(application.forecast.profile)
        else:
            buckets = list(normal.buckets)
            profile = list(normal.profile)
        lots = [
            EstimatedInventoryLot.model_validate(row)
            for row in frozen.get("inventory", [])
        ]
        source = SourceEvidence(
            contract.forecast_input.source_revision, contract.known_at, revision
        )
        return project_inventory(
            lots,
            buckets,
            menu,
            ingredients,
            recipes,
            supplies,
            as_of=contract.as_of,
            target_date=policy.target_date,
            horizon_end=policy.horizon_end,
            known_at=contract.known_at,
            captured_revision=revision,
            opening_manifest={
                item.id: [lot.id for lot in lots if lot.ingredient_id == item.id]
                for item in ingredients
            },
            supply_manifest=supply_manifest,
            recipe_manifest=[
                (item.menu_item_id, item.ingredient_id) for item in recipes
            ],
            service_profile=profile,
            evidence={
                key: source
                for key in (
                    "snapshot",
                    "opening",
                    "supply",
                    "catalogue",
                    "recipe",
                    "forecast",
                    "profile",
                )
            },
            fixture_fefo=policy.fefo_policy,
        )

    @staticmethod
    def _contract(snapshot: dict, run_id: str, revision: str) -> ProcurementContract:
        raw = snapshot.get("procurement_contract")
        if raw is None:
            raise ApiError(
                409, "MISSING_REQUIRED_DATA", "Frozen inventory inputs are unavailable"
            )
        contract = ProcurementContract.model_validate(raw)
        if contract.run_id != run_id or contract.captured_state_revision != revision:
            raise ApiError(
                409, "STATE_REVISION_STALE", "Frozen inventory input revision changed"
            )
        return contract

    @staticmethod
    def _projection_identity(projection) -> dict:
        return {
            "complete": projection.complete,
            "findings": [(item.code, item.source) for item in projection.findings],
            "shortages": [
                (item.ingredient_id, item.start.isoformat(), item.end.isoformat())
                for item in projection.first_shortages or ()
            ],
            "expiries": [
                (item.at.isoformat(), item.lot_key, str(item.quantity))
                for item in projection.expiries or ()
            ],
        }

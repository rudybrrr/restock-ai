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
from src.errors import ApiError, ErrorDetail, ErrorResponse
from src.forecasting import DailySalesObservation, seasonal_baseline
from src.inventory_projection import SourceEvidence, project_inventory
from src.planning import get_run
from src.procurement_contract_schemas import ProcurementContract
from src.sales import estimated_inventory
from src.schemas import EstimatedInventoryLot, Ingredient, MenuItem, RecipeItem
from src.service_buckets import ServicePeriod, allocate_service_buckets


def _identity(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
                return self._result(
                    request,
                    EvidenceCategory.STOCKOUT_RISK,
                    EvidenceSource.DECISION_ENGINE,
                    f"stockout:{projection_id}",
                    {"stockout_exposure": bool(shortages), "provenance": "PROJECTED"},
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
        if snapshot.get("commitments"):
            raise ApiError(
                409,
                "MISSING_REQUIRED_DATA",
                "Frozen commitments need an inventory projection contract",
            )
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
        frozen = contract.frozen_state or snapshot
        menu = [MenuItem.model_validate(row) for row in frozen.get("menu_items", [])]
        ingredients = [
            Ingredient.model_validate(row) for row in frozen.get("ingredients", [])
        ]
        recipes = [RecipeItem.model_validate(row) for row in frozen.get("recipes", [])]
        policy = contract.policy.payload
        forecast = seasonal_baseline(
            history, menu, issue_time=policy.issue_time, target_date=policy.target_date
        )
        if any(item.expected_portions is None for item in forecast.values()):
            raise ApiError(
                409, "MISSING_REQUIRED_DATA", "Forecast history is insufficient"
            )
        profile = [
            ServicePeriod(item.start, item.end, item.weight)
            for item in policy.service_profile
        ]
        buckets = allocate_service_buckets(
            {
                key: value.expected_portions
                for key, value in forecast.items()
                if value.expected_portions is not None
            },
            menu,
            target_date=policy.target_date,
            profile=profile,
        )
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
            [],
            as_of=contract.as_of,
            target_date=policy.target_date,
            horizon_end=policy.horizon_end,
            known_at=contract.known_at,
            captured_revision=revision,
            opening_manifest={
                item.id: [lot.id for lot in lots if lot.ingredient_id == item.id]
                for item in ingredients
            },
            supply_manifest=[],
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

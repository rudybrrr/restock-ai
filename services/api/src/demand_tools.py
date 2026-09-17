"""Read-only Backend adapters for the local Demand specialist."""

import hashlib
import json

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
from src.planning import get_run
from src.procurement_contract_schemas import ProcurementContract
from src.schemas import MenuItem


def _identity(value: object) -> str:
    raw = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class BackendDemandTools:
    """Expose frozen Backend evidence and Aniq's forecast kernel without writes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _ref(
        request: ToolRequest,
        category: EvidenceCategory,
        source: EvidenceSource,
        reference_id: str,
    ) -> EvidenceRef:
        return EvidenceRef(
            category=category,
            source=source,
            reference_id=reference_id,
            state_revision=request.captured_state_revision,
            run_id=request.run_id,
            specialist_call_id=request.tool_call_id.rsplit("-TOOL-", 1)[0],
            tool_call_id=request.tool_call_id,
            producer_tool=request.tool.value,
            call_sequence=int(request.tool_call_id.rsplit("-TOOL-", 1)[1]),
        )

    @staticmethod
    def _result(request: ToolRequest, ref: EvidenceRef, data: dict) -> ToolResult:
        return ToolResult(
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            tool=request.tool,
            output_ref=ref,
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
            if request.tool is AgentToolName.GET_SALES_CONTEXT:
                relevant = run.trigger in {
                    "SALES_UPDATED",
                    "PROMOTION_CREATED",
                    "PROMOTION_CHANGED",
                }
                return self._result(
                    request,
                    self._ref(
                        request,
                        EvidenceCategory.SALES_CONTEXT,
                        EvidenceSource.BACKEND,
                        f"{run.id}:sales-context",
                    ),
                    {
                        "forecast_required": relevant,
                        "promotion_context_required": run.trigger
                        in {"PROMOTION_CREATED", "PROMOTION_CHANGED"},
                        "missing_required_data": "authoritative_daily_sales"
                        not in snapshot,
                    },
                )
            if request.tool is AgentToolName.GET_PROMOTION_CONTEXT:
                promotions = snapshot.get("promotions")
                return self._result(
                    request,
                    self._ref(
                        request,
                        EvidenceCategory.PROMOTION_CONTEXT,
                        EvidenceSource.BACKEND,
                        f"{run.id}:promotions",
                    ),
                    {"missing_required_data": not isinstance(promotions, list)},
                )
            contract = self._contract(snapshot, run.id, request.captured_state_revision)
            if request.tool is AgentToolName.GET_HISTORICAL_DEMAND:
                history = contract.forecast_input.payload.history
                return self._result(
                    request,
                    self._ref(
                        request,
                        EvidenceCategory.DEMAND_HISTORY,
                        EvidenceSource.BACKEND,
                        contract.forecast_input.id,
                    ),
                    {"history_available": bool(history)},
                )
            if request.tool is AgentToolName.FORECAST_DEMAND:
                return self._forecast(request, snapshot, contract)
            if request.tool is AgentToolName.COMPARE_FORECAST_VERSIONS:
                raise ApiError(
                    409,
                    "MISSING_REQUIRED_DATA",
                    "No authoritative immutable forecast comparison contract exists",
                )
            raise ApiError(422, "TOOL_NOT_SUPPORTED", "Unsupported Demand tool")
        except ApiError as error:
            return ErrorResponse(
                error=ErrorDetail(code=error.detail.code, message=error.detail.message)
            )
        except (TypeError, ValueError, KeyError) as error:
            return ErrorResponse(
                error=ErrorDetail(code="MISSING_REQUIRED_DATA", message=str(error))
            )

    @staticmethod
    def _contract(snapshot: dict, run_id: str, revision: str) -> ProcurementContract:
        raw = snapshot.get("procurement_contract")
        if raw is None:
            raise ApiError(
                409, "MISSING_REQUIRED_DATA", "Frozen forecast input is unavailable"
            )
        contract = ProcurementContract.model_validate(raw)
        if contract.run_id != run_id or contract.captured_state_revision != revision:
            raise ApiError(
                409, "STATE_REVISION_STALE", "Frozen forecast input revision changed"
            )
        return contract

    def _forecast(
        self,
        request: ToolRequest,
        snapshot: dict,
        contract: ProcurementContract,
    ) -> ToolResult:
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
        menu_rows = (
            contract.frozen_state.get("menu_items", [])
            if contract.frozen_state is not None
            else snapshot.get("menu_items", [])
        )
        menu = [MenuItem.model_validate(row) for row in menu_rows]
        policy = contract.policy.payload
        forecast = seasonal_baseline(
            history,
            menu,
            issue_time=policy.issue_time,
            target_date=policy.target_date,
        )
        artifact = {
            "method": "SEASONAL_BASELINE_V1",
            "input": contract.forecast_input.id,
            "target_date": policy.target_date.isoformat(),
            "forecast": {
                dish_id: {
                    "expected_portions": str(value.expected_portions)
                    if value.expected_portions is not None
                    else None,
                    "method": value.method,
                    "coverage_flags": value.coverage_flags,
                }
                for dish_id, value in forecast.items()
            },
        }
        complete = all(
            value.expected_portions is not None for value in forecast.values()
        )
        return self._result(
            request,
            self._ref(
                request,
                EvidenceCategory.FORECAST_RESULT,
                EvidenceSource.DECISION_ENGINE,
                f"forecast:{_identity(artifact)}",
            ),
            {"forecast_complete": complete},
        )

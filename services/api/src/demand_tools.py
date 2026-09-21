"""Read-only Backend adapters for the local Demand specialist."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
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
from src.operations_schemas import PromotionEvent
from src.planning import get_run
from src.procurement_contract_schemas import ProcurementContract
from src.promotion_forecasting import (
    SOURCES,
    ForecastVersion,
    apply_promotions,
    compare_forecast_versions,
)
from src.schemas import MenuItem
from src.service_buckets import ServicePeriod, allocate_service_buckets


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
                if run.trigger == "SALES_UPDATED":
                    from src.sales_materiality_contracts import result_for_completion

                    result = result_for_completion(self._session, run.id)
                    if result is None or not result.complete or result.material_change is None:
                        return self._result(
                            request,
                            self._ref(
                                request,
                                EvidenceCategory.SALES_CONTEXT,
                                EvidenceSource.BACKEND,
                                f"{run.id}:sales-materiality",
                            ),
                            {
                                "missing_required_data": True,
                                "sales_materiality_supported": True,
                            },
                        )
                    has_stock_exposure = (
                        result.inventory_feasible is not True
                        or result.first_stockout_interval is not None
                        or bool(result.safety_breaches)
                    )
                    return self._result(
                        request,
                        self._ref(
                            request,
                            EvidenceCategory.SALES_CONTEXT,
                            EvidenceSource.BACKEND,
                            f"{run.id}:sales-materiality",
                        ),
                        {
                            "forecast_required": result.material_change,
                            "sales_materiality_supported": True,
                            "sales_materiality_complete": True,
                            "sales_material": result.material_change,
                            "inventory_required": result.material_change,
                            "stockout_exposure": has_stock_exposure,
                        },
                    )
                promotion_context_required = run.trigger in {
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
                        "forecast_required": promotion_context_required,
                        "promotion_context_required": promotion_context_required,
                        "sales_materiality_supported": False,
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
                return self._compare(request, run, snapshot, contract)
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

    @staticmethod
    def _menu(contract: ProcurementContract) -> list[MenuItem]:
        frozen = contract.frozen_state or {}
        return [MenuItem.model_validate(row) for row in frozen.get("menu_items", [])]

    @staticmethod
    def _history(contract: ProcurementContract) -> list[DailySalesObservation]:
        return [
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

    @staticmethod
    def _profile(contract: ProcurementContract) -> tuple[ServicePeriod, ...]:
        return tuple(
            ServicePeriod(item.start, item.end, item.weight)
            for item in contract.policy.payload.service_profile
        )

    def _normal_forecast(
        self, contract: ProcurementContract, reference: str
    ) -> ForecastVersion:
        menu = self._menu(contract)
        policy = contract.policy.payload
        baseline = seasonal_baseline(
            self._history(contract),
            menu,
            issue_time=policy.issue_time,
            target_date=policy.target_date,
        )
        if any(value.expected_portions is None for value in baseline.values()):
            raise ApiError(409, "MISSING_REQUIRED_DATA", "Forecast history is insufficient")
        profile = self._profile(contract)
        buckets = allocate_service_buckets(
            {
                dish_id: value.expected_portions
                for dish_id, value in baseline.items()
                if value.expected_portions is not None
            },
            menu,
            target_date=policy.target_date,
            profile=profile,
        )
        evidence = tuple(
            (
                name,
                SourceEvidence(
                    f"{contract.forecast_input.id}:{name}",
                    contract.known_at,
                    contract.captured_state_revision,
                ),
            )
            for name in sorted(SOURCES)
        )
        return ForecastVersion(
            reference=reference,
            as_of=contract.as_of,
            known_at=contract.known_at,
            target_date=policy.target_date,
            profile=profile,
            sources=evidence,
            buckets=tuple(buckets),
            promotion_state="EXCLUDED",
            base_reference=reference,
        )

    def _promotion_events(self, run_id: str, known_at: datetime) -> list[PromotionEvent]:
        rows = self._session.execute(
            select(db.events)
            .join(
                db.assessment_requests,
                db.assessment_requests.c.event_id == db.events.c.id,
            )
            .where(
                db.assessment_requests.c.run_id == run_id,
                db.events.c.type.in_(
                    ("PROMOTION_CREATED", "PROMOTION_CHANGED")
                ),
                db.events.c.timestamp <= known_at,
            )
            .order_by(db.events.c.timestamp, db.events.c.id)
        ).mappings()
        return [PromotionEvent.model_validate(dict(row)) for row in rows]

    def _compare(
        self,
        request: ToolRequest,
        run,
        snapshot: dict,
        contract: ProcurementContract,
    ) -> ToolResult:
        menu = self._menu(contract)
        previous = self._normal_forecast(contract, f"{run.id}:forecast:normal")
        events = self._promotion_events(run.id, contract.known_at)
        context = SourceEvidence(
            f"{run.id}:promotion-context",
            contract.known_at,
            contract.captured_state_revision,
        )
        application = apply_promotions(
            previous,
            menu,
            events=events,
            context_evidence=context,
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
        comparison = compare_forecast_versions(previous, application.forecast, menu)
        if comparison.status not in {"COMPARED", "NO_PREVIOUS_VERSION"}:
            raise ApiError(
                409,
                "CALCULATION_INCOMPLETE",
                "Frozen forecast versions are incompatible",
            )
        changed = any(delta.absolute_delta != 0 for delta in comparison.deltas or ())
        artifact = {
            "previous": previous.reference,
            "current": application.forecast.reference,
            "status": comparison.status,
            "changed_context": comparison.changed_context,
            "deltas": [
                {
                    "start": delta.start.isoformat(),
                    "end": delta.end.isoformat(),
                    "dish_id": delta.dish_id,
                    "delta": str(delta.delta),
                }
                for delta in comparison.deltas or ()
            ],
        }
        return self._result(
            request,
            self._ref(
                request,
                EvidenceCategory.FORECAST_RESULT,
                EvidenceSource.BACKEND,
                f"forecast-comparison:{_identity(artifact)}",
            ),
            {
                "comparison_complete": True,
                "forecast_material": changed,
            },
        )

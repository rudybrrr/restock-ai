"""Static, rule-based, scripted-Agent, and real Backend Agent adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import ClassVar, Protocol, cast

from sqlalchemy.orm import Session

from src.agent_contracts import (
    AgentToolName,
    EscalationDetail,
    EscalationReason,
    EventType,
    RecommendedNextStep,
    SpecialistType,
)
from src.backend_control_plane import run_backend_coordinator
from src.decision_engine_adapter import BackendProcurementTools
from src.errors import ApiError
from src.evaluation.contracts import (
    EvaluationOutcome,
    EvidenceExpectation,
    FailureRecord,
    MetricStatus,
    MetricValue,
    ObservedBoundary,
    SystemResult,
)
from src.evaluation.manifests import assert_no_evaluator_truth
from src.operations import record_event
from src.operations_schemas import EventType as BackendEventType
from src.planning import PlanningRun, claim_run, request_run
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
    ProcurementReasoningModel,
)


class PlanningKernel(Protocol):
    def plan(self, boundary: ObservedBoundary) -> KernelResult: ...


class RoutingRule(Protocol):
    def should_replan(self, boundary: ObservedBoundary) -> bool: ...

    def routing(self, boundary: ObservedBoundary) -> Sequence[SpecialistType]: ...


class AgentExecutor(Protocol):
    def run(self, boundary: ObservedBoundary) -> SystemResult: ...


class KernelResult:
    """Small callback result used by deterministic baseline integrations."""

    def __init__(
        self,
        outcome: EvaluationOutcome,
        *,
        routing: Sequence[SpecialistType] = (),
        deterministic_evidence: Sequence[EvidenceExpectation] = (),
        specialist_calls: int = 0,
        tool_calls: int = 0,
        retries: int = 0,
        structured_output_valid: bool | None = True,
        failure: FailureRecord | None = None,
        escalation_reason: EscalationReason | None = None,
        escalation_detail: EscalationDetail | None = None,
        business_metrics: Mapping[str, MetricValue] | None = None,
    ) -> None:
        self.outcome = outcome
        self.routing = tuple(routing)
        self.deterministic_evidence = tuple(deterministic_evidence)
        self.specialist_calls = specialist_calls
        self.tool_calls = tool_calls
        self.retries = retries
        self.structured_output_valid = structured_output_valid
        self.failure = failure
        self.escalation_reason = escalation_reason
        self.escalation_detail = escalation_detail
        self.business_metrics = dict(business_metrics or {})


def unsupported_business_metrics(reason: str = "Canonical simulator output is not available") -> dict[str, MetricValue]:
    return {
        name: MetricValue(status=MetricStatus.UNSUPPORTED, reason=reason)
        for name in (
            "food_waste",
            "stockouts",
            "lost_sales",
            "procurement_cost",
            "emergency_order_cost",
            "total_operational_cost",
            "manual_interventions",
        )
    }


def _result(
    system: str,
    configuration_version: str,
    boundary: ObservedBoundary,
    started: float,
    result: KernelResult,
) -> SystemResult:
    return SystemResult(
        system=system,
        scenario_id=boundary.scenario_id,
        configuration_version=configuration_version,
        observed_boundary_fingerprint=boundary.fingerprint,
        outcome=result.outcome,
        routing=result.routing,
        deterministic_evidence=result.deterministic_evidence,
        specialist_calls=result.specialist_calls,
        tool_calls=result.tool_calls,
        retries=result.retries,
        structured_output_valid=result.structured_output_valid,
        failure=result.failure,
        escalation_reason=result.escalation_reason,
        escalation_detail=result.escalation_detail,
        business_metrics=result.business_metrics or unsupported_business_metrics(),
        elapsed_ms=(perf_counter() - started) * 1000,
    )


class StaticBaselineAdapter:
    """Fair one-shot planner over the same observed boundary as every system."""

    name = "static"

    def __init__(self, kernel: PlanningKernel, configuration_version: str = "static-v1") -> None:
        self._kernel = kernel
        self._configuration_version = configuration_version

    def run(self, boundary: ObservedBoundary) -> SystemResult:
        started = perf_counter()
        try:
            result = self._kernel.plan(boundary)
        except Exception as exc:  # noqa: BLE001 - preserve every failed scenario
            result = KernelResult(
                EvaluationOutcome.FAILED,
                structured_output_valid=False,
                failure=FailureRecord(code=type(exc).__name__, detail=str(exc) or "Static baseline failed"),
            )
        return _result(self.name, self._configuration_version, boundary, started, result)


class RuleBaselineAdapter:
    """Deterministic event routing/replanning rules over the same kernel."""

    name = "rule"

    def __init__(
        self,
        kernel: PlanningKernel,
        rules: RoutingRule,
        configuration_version: str = "rule-v1",
    ) -> None:
        self._kernel = kernel
        self._rules = rules
        self._configuration_version = configuration_version

    def run(self, boundary: ObservedBoundary) -> SystemResult:
        started = perf_counter()
        try:
            routing = tuple(self._rules.routing(boundary))
            if not self._rules.should_replan(boundary):
                return _result(
                    self.name,
                    self._configuration_version,
                    boundary,
                    started,
                    KernelResult(
                        EvaluationOutcome.KEEP_CURRENT_PLAN,
                        routing=routing,
                        specialist_calls=0,
                        tool_calls=0,
                    ),
                )
            planned = self._kernel.plan(boundary)
            planned.routing = routing
            return _result(self.name, self._configuration_version, boundary, started, planned)
        except Exception as exc:  # noqa: BLE001 - preserve every failed scenario
            return _result(
                self.name,
                self._configuration_version,
                boundary,
                started,
                KernelResult(
                    EvaluationOutcome.FAILED,
                    structured_output_valid=False,
                    failure=FailureRecord(code=type(exc).__name__, detail=str(exc) or "Rule baseline failed"),
                ),
            )


class ScriptedAgentAdapter:
    """Adapter for the local deterministic scripted Agent stack."""

    name = "adaptive_restock"

    def __init__(self, executor: AgentExecutor, configuration_version: str = "adaptive-local-v1") -> None:
        self._executor = executor
        self._configuration_version = configuration_version

    def run(self, boundary: ObservedBoundary) -> SystemResult:
        runtime_inputs = boundary.as_runtime_inputs()
        assert_no_evaluator_truth(runtime_inputs, _scenario_for_boundary(boundary))
        result = self._executor.run(boundary)
        if result.configuration_version != self._configuration_version:
            return result.model_copy(update={"configuration_version": self._configuration_version})
        return result


@dataclass(frozen=True)
class BackendRunContext:
    run: PlanningRun
    session: Session


class BackendScenarioPreparer(Protocol):
    def prepare(self, session: Session, boundary: ObservedBoundary) -> PlanningRun: ...


class SeededBackendScenarioPreparer:
    """Materialize observed events with the existing Backend event service."""

    def prepare(self, session: Session, boundary: ObservedBoundary) -> PlanningRun:
        for event in boundary.observed_events:
            payload = dict(event.payload)
            payload.setdefault("effective_at", event.occurred_at.isoformat())
            record_event(
                session,
                cast(BackendEventType, EventType(event.event_type).value),
                "evaluation",
                payload,
            )
        raw_as_of = boundary.initial_authoritative_state.get("as_of")
        if not isinstance(raw_as_of, str):
            raise TypeError("scenario initial_authoritative_state.as_of is required")
        requested = request_run(session, datetime.fromisoformat(raw_as_of))
        return claim_run(session) if requested.status == "QUEUED" else requested


class EventRoutingClassifier:
    """Deterministic manual route for a prepared scenario boundary."""

    _routes: ClassVar[dict[EventType, SpecialistType]] = {
        EventType.SALES_UPDATED: SpecialistType.DEMAND,
        EventType.PROMOTION_CREATED: SpecialistType.DEMAND,
        EventType.PROMOTION_CHANGED: SpecialistType.DEMAND,
        EventType.DAILY_UPDATE_SUBMITTED: SpecialistType.INVENTORY,
        EventType.DAILY_UPDATE_CORRECTED: SpecialistType.INVENTORY,
        EventType.INVENTORY_ADJUSTED: SpecialistType.INVENTORY,
        EventType.INVENTORY_WASTED: SpecialistType.INVENTORY,
        EventType.SUPPLIER_AVAILABILITY_CHANGED: SpecialistType.PROCUREMENT,
        EventType.SUPPLIER_PRICE_CHANGED: SpecialistType.PROCUREMENT,
        EventType.SUPPLIER_STATUS_CHANGED: SpecialistType.PROCUREMENT,
        EventType.DELIVERY_DELAYED: SpecialistType.INVENTORY,
        EventType.DELIVERY_SHORT: SpecialistType.INVENTORY,
        EventType.DELIVERY_CANCELLED: SpecialistType.INVENTORY,
    }

    def __init__(self, boundary: ObservedBoundary) -> None:
        self._boundary = boundary

    def classify(self, invocation, context_refs):
        routes = []
        for event in self._boundary.observed_events:
            try:
                route = self._routes.get(EventType(event.event_type))
            except ValueError:
                route = None
            if route is not None and route not in routes:
                routes.append(route)
        if not routes:
            return list(SpecialistType)
        return routes


class FirstSliceProcurementScript:
    """Provider-free script that delegates all arithmetic to Backend tools."""

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        if not context.tool_results:
            tool = AgentToolName.OPTIMISE_PURCHASE_PLAN
            inputs = [context.delegation.trigger_ref]
            summary = "Run the frozen deterministic procurement search."
        elif len(context.tool_results) == 1:
            tool = AgentToolName.VALIDATE_PURCHASE_PLAN
            inputs = [context.tool_results[-1].output_ref]
            summary = "Validate the frozen deterministic candidate."
        else:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.COMPLETE,
                interpreted_impact="Backend evidence is complete.",
                recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
                summary="Submit the validated deterministic candidate.",
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.CALL_TOOL,
            tool=tool,
            input_refs=inputs,
            interpreted_impact="Use only frozen Backend evidence.",
            summary=summary,
        )


class BackendPlanningKernel:
    """One-shot bridge for Static and Rule baselines to the real engine."""

    def __init__(self, session_factory: Callable[[], Session], preparer: BackendScenarioPreparer) -> None:
        self._session_factory = session_factory
        self._preparer = preparer

    def plan(self, boundary: ObservedBoundary) -> KernelResult:
        with self._session_factory() as session:
            run = self._preparer.prepare(session, boundary)
            from src.decision_engine_adapter import run_first_slice_engine

            try:
                artifacts = run_first_slice_engine(session, run)
            except ApiError as error:
                reasons = {reason.value: reason for reason in EscalationReason}
                details = error.detail.details or {}
                return KernelResult(
                    EvaluationOutcome.ESCALATE,
                    escalation_reason=reasons.get(error.detail.code, EscalationReason.TOOL_FAILURE),
                    escalation_detail=(
                        EscalationDetail.SEARCH_LIMIT_REACHED
                        if details.get("termination_code") == EscalationDetail.SEARCH_LIMIT_REACHED.value
                        else None
                    ),
                    structured_output_valid=True,
                )
            return KernelResult(
                EvaluationOutcome.REVISE_PLAN,
                deterministic_evidence=(
                    EvidenceExpectation(
                        category="CANDIDATE_RESULT",
                        source="DECISION_ENGINE",
                        reference=artifacts["candidate"]["id"],
                    ),
                    EvidenceExpectation(
                        category="VALIDATION_RESULT",
                        source="DECISION_ENGINE",
                        reference=artifacts["validation"]["id"],
                    ),
                ),
            )


class BackendAgentAdapter:
    """Run the real Backend lifecycle, deterministic tools, and local Agent."""

    name = "adaptive_restock"

    def __init__(
        self,
        session_factory: Callable[[], Session],
        preparer: BackendScenarioPreparer,
        procurement_model: ProcurementReasoningModel,
        *,
        configuration_version: str = "adaptive-local-v1",
        demand_model=None,
        inventory_model=None,
        manual_classifier=None,
    ) -> None:
        self._session_factory = session_factory
        self._preparer = preparer
        self._procurement_model = procurement_model
        self._configuration_version = configuration_version
        self._demand_model = demand_model
        self._inventory_model = inventory_model
        self._manual_classifier = manual_classifier

    def run(self, boundary: ObservedBoundary) -> SystemResult:
        started = perf_counter()
        try:
            with self._session_factory() as session:
                run = self._preparer.prepare(session, boundary)
                tools = _RecordingBackendTools(session)
                execution = run_backend_coordinator(
                    session,
                    run.id,
                    self._procurement_model,
                    tools,
                    demand_model=self._demand_model,
                    inventory_model=self._inventory_model,
                    manual_classifier=self._manual_classifier,
                )
                completion = execution.completion
                outcome = EvaluationOutcome(completion.outcome.value)
                routing = tuple(
                    event.specialist
                    for event in execution.trace
                    if event.specialist is not None and event.action.value == "SPECIALIST_CALLED"
                )
                tool_calls = len(tools.calls)
                retries = 0
                return SystemResult(
                    system=self.name,
                    scenario_id=boundary.scenario_id,
                    configuration_version=self._configuration_version,
                    observed_boundary_fingerprint=boundary.fingerprint,
                    outcome=outcome,
                    routing=routing,
                    deterministic_evidence=(),
                    specialist_calls=len(routing),
                    tool_calls=tool_calls,
                    retries=retries,
                    structured_output_valid=True,
                    escalation_reason=completion.escalation_reason,
                    escalation_detail=completion.escalation_detail,
                    business_metrics=unsupported_business_metrics(),
                    elapsed_ms=(perf_counter() - started) * 1000,
                )
        except Exception as exc:  # noqa: BLE001 - preserve every failed scenario
            return SystemResult(
                system=self.name,
                scenario_id=boundary.scenario_id,
                configuration_version=self._configuration_version,
                observed_boundary_fingerprint=boundary.fingerprint,
                outcome=EvaluationOutcome.FAILED,
                specialist_calls=0,
                tool_calls=0,
                retries=0,
                structured_output_valid=False,
                failure=FailureRecord(code=type(exc).__name__, detail=str(exc) or "Backend run failed"),
                business_metrics=unsupported_business_metrics(),
                elapsed_ms=(perf_counter() - started) * 1000,
            )


class _RecordingBackendTools(BackendProcurementTools):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return super().execute(request)


def _scenario_for_boundary(boundary: ObservedBoundary):
    """Create the narrow validation view needed by the leakage guard."""

    from src.evaluation.contracts import (
        EvaluationSplit,
        ExpectedScenario,
        ScenarioManifest,
    )

    return ScenarioManifest(
        schema_version="restock-evaluation-scenario/1",
        scenario_id=boundary.scenario_id,
        scenario_version=boundary.scenario_version,
        split=EvaluationSplit.DEVELOPMENT,
        family="runtime",
        initial_authoritative_state=boundary.initial_authoritative_state,
        observed_events=boundary.observed_events,
        policy_config_versions=boundary.policy_config_versions,
        expected=ExpectedScenario(final_outcome=EvaluationOutcome.KEEP_CURRENT_PLAN),
    )

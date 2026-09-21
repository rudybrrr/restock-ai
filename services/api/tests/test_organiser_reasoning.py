import json
from collections.abc import Mapping, Sequence
from http.client import HTTPMessage
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from src.agent_contracts import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    SpecialistDelegation,
    SpecialistStatus,
    SpecialistType,
)
from src.config import Settings
from src.demand_specialist import (
    DemandDecisionAction,
    DemandModelDecision,
    DemandReasoningContext,
)
from src.inventory_specialist import (
    InventoryDecisionAction,
    InventoryModelDecision,
    InventoryReasoningContext,
)
from src.organiser_gateway import (
    OrganiserAuthenticationError,
    OrganiserChatModel,
    OrganiserDemandReasoning,
    OrganiserGatewaySettings,
    OrganiserGatewayUnavailableError,
    OrganiserInventoryReasoning,
    OrganiserModelOutputMalformedError,
    OrganiserModelOutputValidationError,
    OrganiserProcurementReasoning,
    OrganiserReasoningModels,
    build_organiser_reasoning_model,
    build_organiser_reasoning_models,
)
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
    ProcurementSpecialist,
)

GATEWAY_URL = "https://api.softwaresystems.app"
API_KEY = "typed-reasoning-secret"
MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"


class FakeResponse:
    status = 200

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class RecordingChatModel:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[Sequence[Mapping[str, str]], type[Any]]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        response_model: type[Any],
    ) -> Any:
        self.calls.append((messages, response_model))
        return response_model.model_validate(self.payload)


class NoCallTools:
    def execute(self, request: Any) -> Any:
        raise AssertionError("synthetic typed call must not invoke a tool")


class NoopAudit:
    def record(self, event: Any) -> None:
        pass


def gateway_settings() -> OrganiserGatewaySettings:
    return OrganiserGatewaySettings(
        gateway_url=GATEWAY_URL,
        api_key=SecretStr(API_KEY),
        model=MODEL,
    )


def delegation(specialist: SpecialistType = SpecialistType.PROCUREMENT) -> SpecialistDelegation:
    event_ref = EvidenceRef(
        category=EvidenceCategory.EVENT_CONTEXT,
        source=EvidenceSource.BACKEND,
        reference_id="EVENT-TYPED-1",
        state_revision="STATE-TYPED-1",
    )
    return SpecialistDelegation(
        run_id="RUN-TYPED-1",
        task_id="TASK-TYPED-1",
        specialist=specialist,
        objective=(
            "Assess whether this informational supplier-status event requires a "
            "procurement investigation. It contains no authoritative supplier values."
        ),
        trigger_ref=event_ref,
        captured_state_revision="STATE-TYPED-1",
        context_refs=[event_ref],
    )


def context() -> ProcurementReasoningContext:
    current = delegation()
    return ProcurementReasoningContext(
        delegation=current,
        available_evidence_refs=(current.trigger_ref,),
        remaining_logical_tool_calls=6,
    )


def demand_context() -> DemandReasoningContext:
    current = delegation(SpecialistType.DEMAND)
    return DemandReasoningContext(
        delegation=current,
        available_evidence_refs=(current.trigger_ref,),
        remaining_logical_tool_calls=5,
    )


def inventory_context() -> InventoryReasoningContext:
    current = delegation(SpecialistType.INVENTORY)
    return InventoryReasoningContext(
        delegation=current,
        available_evidence_refs=(current.trigger_ref,),
        remaining_logical_tool_calls=6,
    )


def valid_decision() -> dict[str, Any]:
    current = delegation()
    return {
        "run_id": current.run_id,
        "task_id": current.task_id,
        "action": ProcurementDecisionAction.COMPLETE.value,
        "tool": None,
        "input_refs": [],
        "scope_selectors": [],
        "interpreted_impact": "The event is informational and has no authoritative supplier values.",
        "missing_information": [],
        "recommended_next_step": "NONE",
        "summary": "No procurement tool is justified by this synthetic event alone.",
    }


def test_typed_organiser_model_uses_existing_procurement_boundary() -> None:
    chat = RecordingChatModel(valid_decision())
    model = OrganiserProcurementReasoning(chat)  # type: ignore[arg-type]

    result = ProcurementSpecialist(model, NoCallTools(), NoopAudit()).execute(
        delegation()
    )

    assert result.status is SpecialistStatus.COMPLETED
    assert result.run_id == "RUN-TYPED-1"
    assert result.task_id == "TASK-TYPED-1"
    assert len(chat.calls) == 1
    assert chat.calls[0][1] is ProcurementModelDecision


def test_typed_adapter_supplies_existing_context_and_response_schema() -> None:
    chat = RecordingChatModel(valid_decision())
    model = OrganiserProcurementReasoning(chat)  # type: ignore[arg-type]

    result = model.decide(context())
    user_payload = json.loads(chat.calls[0][0][1]["content"])

    assert isinstance(result, ProcurementModelDecision)
    assert user_payload["context"]["delegation"]["task_id"] == "TASK-TYPED-1"
    assert user_payload["response_schema"] == ProcurementModelDecision.model_json_schema()


def test_demand_typed_adapter_uses_existing_context_and_response_schema() -> None:
    decision = DemandModelDecision(
        run_id="RUN-TYPED-1",
        task_id="TASK-TYPED-1",
        action=DemandDecisionAction.COMPLETE,
        interpreted_impact="No demand calculation is justified.",
        summary="Keep the current plan.",
    )
    chat = RecordingChatModel(decision.model_dump(mode="json"))
    model = OrganiserDemandReasoning(chat)  # type: ignore[arg-type]

    result = model.decide(demand_context())
    user_payload = json.loads(chat.calls[0][0][1]["content"])

    assert result == decision
    assert chat.calls[0][1] is DemandModelDecision
    assert user_payload["response_schema"] == DemandModelDecision.model_json_schema()


def test_inventory_typed_adapter_uses_existing_context_and_response_schema() -> None:
    decision = InventoryModelDecision(
        run_id="RUN-TYPED-1",
        task_id="TASK-TYPED-1",
        action=InventoryDecisionAction.COMPLETE,
        interpreted_impact="No inventory calculation is justified.",
        summary="Keep the current plan.",
    )
    chat = RecordingChatModel(decision.model_dump(mode="json"))
    model = OrganiserInventoryReasoning(chat)  # type: ignore[arg-type]

    result = model.decide(inventory_context())
    user_payload = json.loads(chat.calls[0][0][1]["content"])

    assert result == decision
    assert chat.calls[0][1] is InventoryModelDecision
    assert user_payload["response_schema"] == InventoryModelDecision.model_json_schema()


def test_factory_is_explicit_and_construction_has_no_network_side_effect() -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError("factory construction must not call the gateway")

    model = build_organiser_reasoning_model(
        Settings(
            database_url="sqlite://",
            llm_gateway_url=GATEWAY_URL,
            llm_gateway_api_key=SecretStr(API_KEY),
            llm_model=MODEL,
        ),
        opener=opener,
    )

    assert isinstance(model, OrganiserProcurementReasoning)
    assert calls == 0


def test_live_reasoning_bundle_is_explicit_and_uses_existing_specialist_protocols() -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError("factory construction must not call the gateway")

    models = build_organiser_reasoning_models(
        Settings(
            database_url="sqlite://",
            llm_gateway_url=GATEWAY_URL,
            llm_gateway_api_key=SecretStr(API_KEY),
            llm_model=MODEL,
        ),
        opener=opener,
    )

    assert isinstance(models, OrganiserReasoningModels)
    assert isinstance(models.procurement, OrganiserProcurementReasoning)
    assert isinstance(models.demand, OrganiserDemandReasoning)
    assert isinstance(models.inventory, OrganiserInventoryReasoning)
    assert calls == 0


def test_invalid_json_fails_closed_at_typed_boundary() -> None:
    model = OrganiserProcurementReasoning(
        OrganiserChatModel(
            gateway_settings(),
            opener=lambda request, *, timeout: FakeResponse(
                {"message": {"content": "not-json"}}
            ),
        )
    )

    with pytest.raises(OrganiserModelOutputMalformedError):
        model.decide(context())


def test_schema_invalid_json_fails_closed_at_typed_boundary() -> None:
    model = OrganiserProcurementReasoning(
        OrganiserChatModel(
            gateway_settings(),
            opener=lambda request, *, timeout: FakeResponse(
                {"message": {"content": '{"unexpected":true}'}}
            ),
        )
    )

    with pytest.raises(OrganiserModelOutputValidationError):
        model.decide(context())


def test_gateway_failure_preserves_specialist_escalation_semantics() -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        raise URLError(f"network failure involving {API_KEY}")

    model = OrganiserProcurementReasoning(
        OrganiserChatModel(gateway_settings(), opener=opener)
    )
    result = ProcurementSpecialist(model, NoCallTools(), NoopAudit()).execute(
        delegation()
    )

    assert calls == 1
    assert result.status is SpecialistStatus.ESCALATED
    assert result.escalation_reason is not None
    assert "TOOL_FAILURE" == result.escalation_reason.value
    assert API_KEY not in str(result)


def test_authentication_failure_is_sanitized_through_typed_model() -> None:
    def opener(request: Any, *, timeout: int) -> Any:
        raise HTTPError(request.full_url, 401, API_KEY, HTTPMessage(), BytesIO())

    model = OrganiserProcurementReasoning(
        OrganiserChatModel(gateway_settings(), opener=opener)
    )

    with pytest.raises(OrganiserAuthenticationError) as caught:
        model.decide(context())

    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


def test_network_failure_is_sanitized_before_typed_caller_sees_it() -> None:
    def opener(request: Any, *, timeout: int) -> Any:
        raise URLError(f"network failure involving {API_KEY}")

    model = OrganiserProcurementReasoning(
        OrganiserChatModel(gateway_settings(), opener=opener)
    )

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.decide(context())

    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)

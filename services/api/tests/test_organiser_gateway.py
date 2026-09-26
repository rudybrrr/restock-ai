import json
import logging
from collections.abc import Mapping
from http.client import HTTPMessage
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from src.demand_specialist import DemandModelDecision
from src.inventory_specialist import InventoryModelDecision
from src.organiser_gateway import (
    OrganiserAuthenticationError,
    OrganiserChatModel,
    OrganiserDemandReasoning,
    OrganiserGatewayConfigurationError,
    OrganiserGatewayResponseError,
    OrganiserGatewaySettings,
    OrganiserGatewayUnavailableError,
    OrganiserInventoryReasoning,
    OrganiserModelOutputMalformedError,
    OrganiserModelOutputValidationError,
    OrganiserProcurementReasoning,
)
from src.procurement_specialist import ProcurementModelDecision

GATEWAY_URL = "https://api.softwaresystems.app"
API_KEY = "gateway-secret-key"
MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str


class NestedResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]


class FakeResponse:
    def __init__(self, payload: Mapping[str, Any], *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class RawResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class CloseFailingResponse(FakeResponse):
    def close(self) -> None:
        raise RuntimeError("response cleanup failed")


class ReadAndCloseFailingResponse(CloseFailingResponse):
    def read(self) -> bytes:
        raise OSError("response read failed")


def settings(**overrides: Any) -> OrganiserGatewaySettings:
    values: dict[str, Any] = {
        "gateway_url": GATEWAY_URL,
        "api_key": SecretStr(API_KEY),
        "model": MODEL,
        "timeout_seconds": 30,
        "num_predict": 2048,
    }
    values.update(overrides)
    return OrganiserGatewaySettings.model_validate(values)


def test_gateway_posts_official_chat_request_and_extracts_message_content() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"message": {"content": '{"outcome":"ESCALATE"}'}})

    model = OrganiserChatModel(settings(), opener=opener)

    result = model.complete(
        [{"role": "user", "content": "Return the canonical result."}]
    )

    assert result == '{"outcome":"ESCALATE"}'
    assert captured["url"] == f"{GATEWAY_URL}/api/chat"
    assert captured["headers"]["X-api-key"] == API_KEY
    assert captured["headers"]["Content-type"] == "application/json"
    assert "Authorization" not in captured["headers"]
    assert captured["timeout"] == 30
    assert captured["body"] == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Return the canonical result."}],
        "stream": False,
        "options": {"num_predict": 2048},
    }


def test_gateway_validates_returned_json_with_existing_pydantic_model() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"message": {"content": '{"outcome":"KEEP_CURRENT_PLAN"}'}})

    model = OrganiserChatModel(
        settings(),
        opener=opener,
    )

    parsed = model.complete_json(
        [{"role": "user", "content": "Return JSON."}], ResponseModel
    )

    assert parsed.outcome == "KEEP_CURRENT_PLAN"
    assert captured["body"] == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Return JSON."}],
        "stream": False,
        "format": ResponseModel.model_json_schema(),
        "think": False,
        "options": {"num_predict": 1024, "temperature": 0},
    }


def test_typed_budget_respects_a_lower_configured_prediction_limit() -> None:
    bodies: list[dict[str, Any]] = []

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        bodies.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"message": {"content": '{"outcome":"KEEP_CURRENT_PLAN"}'}})

    model = OrganiserChatModel(settings(num_predict=512), opener=opener)

    assert model.complete_json([], ResponseModel).outcome == "KEEP_CURRENT_PLAN"
    assert model.complete([]) == '{"outcome":"KEEP_CURRENT_PLAN"}'
    assert bodies[0]["options"] == {"num_predict": 512, "temperature": 0}
    assert bodies[0]["format"] == ResponseModel.model_json_schema()
    assert bodies[0]["think"] is False
    assert bodies[1]["options"] == {"num_predict": 512}
    assert "format" not in bodies[1]
    assert "think" not in bodies[1]


def test_duplicate_first_output_is_repaired_without_echoing_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = (
        '<restock_decision_v1>{"outcome":"FIRST_VALID_SENTINEL"}'
        '</restock_decision_v1>'
        '<restock_decision_v1>{"outcome":"SECOND_VALID_SENTINEL"}'
        '</restock_decision_v1>'
    )
    second = '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}</restock_decision_v1>'
    responses = iter((first, second))
    bodies: list[dict[str, Any]] = []

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        bodies.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"message": {"content": next(responses)}})

    model = OrganiserChatModel(settings(), opener=opener)
    original_messages = [{"role": "user", "content": "Return JSON."}]

    with caplog.at_level(logging.DEBUG):
        result = model.complete_json(original_messages, ResponseModel)

    assert result.outcome == "KEEP_CURRENT_PLAN"
    assert len(bodies) == 2
    assert bodies[0]["messages"] == original_messages
    assert bodies[1]["messages"][:1] == original_messages
    assert len(bodies[1]["messages"]) == 2
    assert bodies[1]["messages"][1]["role"] == "user"
    assert "Stop immediately after the closing brace" in bodies[1]["messages"][1]["content"]
    assert bodies[0]["format"] == bodies[1]["format"] == ResponseModel.model_json_schema()
    assert bodies[0]["think"] is bodies[1]["think"] is False
    assert bodies[0]["options"] == bodies[1]["options"] == {"num_predict": 1024, "temperature": 0}
    assert "FIRST_VALID_SENTINEL" not in json.dumps(bodies[1])
    assert "SECOND_VALID_SENTINEL" not in json.dumps(bodies[1])
    assert "FIRST_VALID_SENTINEL" not in caplog.text
    assert "SECOND_VALID_SENTINEL" not in caplog.text


def test_two_duplicate_outputs_still_fail_closed_without_first_valid_wins() -> None:
    duplicated = (
        '<restock_decision_v1>{"outcome":"FIRST"}</restock_decision_v1>'
        '<restock_decision_v1>{"outcome":"SECOND"}</restock_decision_v1>'
    )
    calls = 0

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse({"message": {"content": duplicated}})

    model = OrganiserChatModel(settings(), opener=opener)

    with pytest.raises(OrganiserModelOutputMalformedError):
        model.complete_json([], ResponseModel)

    assert calls == 2


def test_schema_invalid_first_output_is_repaired_once() -> None:
    responses = iter(('{"unexpected":true}', '{"outcome":"KEEP_CURRENT_PLAN"}'))
    calls = 0

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse({"message": {"content": next(responses)}})

    model = OrganiserChatModel(settings(), opener=opener)

    assert model.complete_json([], ResponseModel).outcome == "KEEP_CURRENT_PLAN"
    assert calls == 2


@pytest.mark.parametrize(
    ("failure", "classification"),
    [
        ("network", "NETWORK_ERROR"),
        ("timeout", "TRANSPORT_TIMEOUT"),
        ("auth", "AUTH_ERROR"),
        ("rate_limit", "RATE_LIMITED"),
        ("server", "SERVER_ERROR"),
    ],
)
def test_typed_transport_and_http_failures_never_retry(
    failure: str, classification: str
) -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        if failure == "network":
            raise URLError("network unavailable")
        if failure == "timeout":
            raise TimeoutError("gateway timeout")
        if failure == "auth":
            raise HTTPError(request.full_url, 401, "unauthorized", HTTPMessage(), BytesIO())
        if failure == "rate_limit":
            return FakeResponse({}, status=429)
        return FakeResponse({}, status=500)

    model = OrganiserChatModel(settings(), opener=opener)

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete_json([], ResponseModel)

    assert caught.value.classification == classification
    assert calls == 1


@pytest.mark.parametrize("language", ["json", "JSON", "Json"])
def test_gateway_parses_one_clean_json_fence(
    language: str,
) -> None:
    content = f"```{language}\n{{\"outcome\":\"KEEP_CURRENT_PLAN\"}}\n```"
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    parsed = model.complete_json([], ResponseModel)

    assert parsed.outcome == "KEEP_CURRENT_PLAN"


@pytest.mark.parametrize(
    "content",
    [
        '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}</restock_decision_v1>',
        (
            "Here is the result:\n"
            '<restock_decision_v1>\n{"outcome":"KEEP_CURRENT_PLAN"}\n'
            "</restock_decision_v1>\nAdditional explanation."
        ),
    ],
)
def test_gateway_parses_one_authoritative_envelope(content: str) -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    parsed = model.complete_json([], ResponseModel)

    assert parsed.outcome == "KEEP_CURRENT_PLAN"


def test_gateway_parses_nested_json_inside_authoritative_envelope() -> None:
    content = (
        "<restock_decision_v1>\n"
        '{"payload":{"entries":[{"identifier":"nested-1"}]}}\n'
        "</restock_decision_v1>"
    )
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    parsed = model.complete_json([], NestedResponseModel)

    assert parsed.payload == {"entries": [{"identifier": "nested-1"}]}


def test_gateway_validates_authoritative_envelope_against_schema() -> None:
    content = '<restock_decision_v1>{"unexpected":true}</restock_decision_v1>'
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    with pytest.raises(OrganiserModelOutputValidationError):
        model.complete_json([], ResponseModel)


def test_gateway_rejects_second_envelope_in_untrusted_context_echo() -> None:
    content = (
        "Untrusted context echoed: "
        '<restock_decision_v1>{"outcome":"ESCALATE"}</restock_decision_v1>\n'
        '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}'
        "</restock_decision_v1>"
    )
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    with pytest.raises(OrganiserModelOutputMalformedError):
        model.complete_json([], ResponseModel)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "42",
        "null",
        '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}',
        '</restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}',
        (
            '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}'
            '</restock_decision_v1>'
            '<restock_decision_v1>{"outcome":"ESCALATE"}</restock_decision_v1>'
        ),
        (
            "<restock_decision_v1><restock_decision_v1>"
            '{"outcome":"KEEP_CURRENT_PLAN"}'
            "</restock_decision_v1></restock_decision_v1>"
        ),
        '<restock_decision_v1>{"outcome":</restock_decision_v1>',
        '<restock_decision_v1>[]</restock_decision_v1>',
        '<restock_decision_v1>42</restock_decision_v1>',
        '<restock_decision_v1>null</restock_decision_v1>',
        (
            '<restock_decision_v1 extra="value">{"outcome":"KEEP_CURRENT_PLAN"}'
            "</restock_decision_v1>"
        ),
        (
            '<restock_decision_v1>{"outcome":"KEEP_CURRENT_PLAN"}'
            "</restock_decision_v1><restock_decision_v1"
        ),
        (
            "Here is the result:\n```json\n"
            '{"outcome":"KEEP_CURRENT_PLAN"}\n```'
        ),
        (
            "```json\n"
            '{"outcome":"KEEP_CURRENT_PLAN"}\n'
            "This is ordinary trailing commentary.\n```"
        ),
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n"
            "{\"outcome\":\"ESCALATE\"}\n```"
        ),
        "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n[]\n```",
        "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n42\n```",
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n"
            "Additional context: {\"outcome\":\"ESCALATE\"}.\n```"
        ),
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n"
            "Additional context: [1, 2].\n```"
        ),
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n"
            'Commentary with an unmatched quote "and a hidden {} pair.\n```'
        ),
        (
            "```json\nHere is the result:\n"
            "{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```"
        ),
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```\n"
            "```json\n{\"outcome\":\"ESCALATE\"}\n```"
        ),
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```\n"
            "```text\nmore text\n```"
        ),
        "```\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```",
        "```python\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```",
        "The result is {\"outcome\":\"KEEP_CURRENT_PLAN\"}.",
        "```json\n{\"outcome\":\n```",
        "```json\n[]\n```",
        "```json\n42\n```",
        "```json\nnull\n```",
        (
            "```json\n{\"outcome\":\"KEEP_CURRENT_PLAN\"}\n```\n"
            "```json"
        ),
    ],
)
def test_gateway_rejects_unsupported_model_output_wrapping(content: str) -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    with pytest.raises(OrganiserModelOutputMalformedError):
        model.complete_json([], ResponseModel)


@pytest.mark.parametrize(
    ("content", "error_type", "sensitive_content"),
    [
        (
            (
                "MODEL_PRIVATE_SENTINEL gateway-secret-key\n"
                "```json\n{\"outcome\":\n```"
            ),
            OrganiserModelOutputMalformedError,
            "MODEL_PRIVATE_SENTINEL",
        ),
        (
            json.dumps({"unexpected": "MODEL_PRIVATE_SENTINEL gateway-secret-key"}),
            OrganiserModelOutputValidationError,
            "MODEL_PRIVATE_SENTINEL",
        ),
        (
            (
                '<restock_decision_v1>{"unexpected": "MODEL_PRIVATE_SENTINEL '
                'gateway-secret-key"}</restock_decision_v1>'
            ),
            OrganiserModelOutputValidationError,
            "MODEL_PRIVATE_SENTINEL",
        ),
        (
            (
                '<restock_decision_v1>{"outcome": "MODEL_PRIVATE_SENTINEL '
                'gateway-secret-key"</restock_decision_v1>'
            ),
            OrganiserModelOutputMalformedError,
            "MODEL_PRIVATE_SENTINEL",
        ),
    ],
)
def test_model_output_errors_and_logs_hide_credentials_and_response_content(
    content: str,
    error_type: type[Exception],
    sensitive_content: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": content}}
        ),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(error_type) as caught:
        model.complete_json([], ResponseModel)

    assert API_KEY not in str(caught.value)
    assert sensitive_content not in str(caught.value)
    assert API_KEY not in caplog.text
    assert sensitive_content not in caplog.text
    assert caught.value.__cause__ is None


class WrapperContext(BaseModel):
    value: str = "typed wrapper test"


@pytest.mark.parametrize(
    ("wrapper", "response_model"),
    [
        (OrganiserDemandReasoning, DemandModelDecision),
        (OrganiserInventoryReasoning, InventoryModelDecision),
        (OrganiserProcurementReasoning, ProcurementModelDecision),
    ],
)
def test_typed_reasoning_wrappers_send_their_exact_response_schema(
    wrapper: type[Any], response_model: type[BaseModel]
) -> None:
    captured: dict[str, Any] = {}
    decision = {
        "run_id": "RUN-TYPED-GATEWAY-1",
        "task_id": "TASK-TYPED-GATEWAY-1",
        "action": "COMPLETE",
        "interpreted_impact": "No specialist action is justified.",
        "summary": "Keep the current plan.",
    }

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"message": {"content": json.dumps(decision)}})

    result = wrapper(OrganiserChatModel(settings(), opener=opener)).decide(
        WrapperContext()
    )

    assert isinstance(result, response_model)
    assert captured["body"]["format"] == response_model.model_json_schema()
    assert captured["body"]["think"] is False
    assert isinstance(captured["body"]["format"], dict)
    assert captured["body"]["options"] == {"num_predict": 1024, "temperature": 0}
    assert json.loads(captured["body"]["messages"][1]["content"]) == {
        "context": WrapperContext().model_dump(mode="json")
    }
    system_instruction = captured["body"]["messages"][0]["content"]
    assert "one bare JSON object matching the HTTP response schema" in system_instruction
    assert "Do not wrap it in decision envelope tags" in system_instruction
    assert "Do not repeat the decision" in system_instruction
    assert "Stop after the closing brace" in system_instruction
    assert ", ".join(response_model.model_fields) in system_instruction
    assert "Copy run_id and task_id exactly from context.delegation" in system_instruction
    assert "missing_information must be an array of strings" in system_instruction
    assert "action must be exactly CALL_TOOL or COMPLETE" in system_instruction
    assert "recommended_next_step to NONE" in system_instruction
    assert "Keep interpreted_impact and summary" in system_instruction
    assert "first character must be { and the last character must be }" in system_instruction
    assert "The exact response JSON schema is:" in system_instruction
    if response_model is ProcurementModelDecision:
        assert "REQUEST_HUMAN_APPROVAL does not submit a candidate" in system_instruction


def test_gateway_rejects_malformed_model_json_and_schema_output() -> None:
    malformed = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": "not-json"}}
        ),
    )
    with pytest.raises(OrganiserModelOutputMalformedError):
        malformed.complete_json([], ResponseModel)

    invalid = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": '{"unexpected":true}'}}
        ),
    )
    with pytest.raises(OrganiserModelOutputValidationError):
        invalid.complete_json([], ResponseModel)


@pytest.mark.parametrize("status", [401, 403])
def test_gateway_authentication_errors_are_sanitized(status: int) -> None:
    def opener(request: Any, *, timeout: int) -> Any:
        raise HTTPError(
            request.full_url,
            status,
            "credential rejected",
            HTTPMessage(),
            BytesIO(),
        )

    model = OrganiserChatModel(settings(), opener=opener)

    with pytest.raises(OrganiserAuthenticationError) as caught:
        model.complete([])

    assert caught.value.classification == "AUTH_ERROR"
    assert caught.value.status_code == status
    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


@pytest.mark.parametrize(
    ("status", "classification"),
    [
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "SERVER_ERROR"),
        (418, "HTTP_ERROR"),
    ],
)
def test_gateway_http_failures_preserve_safe_classification_and_status(
    status: int, classification: str
) -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse({}, status=status),
    )

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete([])

    assert caught.value.classification == classification
    assert caught.value.status_code == status
    assert "{}" not in str(caught.value)
    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


def test_gateway_timeout_is_classified_without_retry() -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        raise TimeoutError(f"failed while using {API_KEY}")

    model = OrganiserChatModel(settings(), opener=opener)

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete([])

    assert calls == 1
    assert caught.value.classification == "TRANSPORT_TIMEOUT"
    assert caught.value.status_code is None
    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


def test_gateway_network_errors_are_classified_without_retry() -> None:
    calls = 0

    def opener(request: Any, *, timeout: int) -> Any:
        nonlocal calls
        calls += 1
        raise URLError(f"failed while using {API_KEY}")

    model = OrganiserChatModel(settings(), opener=opener)

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete([])

    assert calls == 1
    assert caught.value.classification == "NETWORK_ERROR"
    assert caught.value.status_code is None
    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


def test_gateway_unclassified_failure_uses_other_classification() -> None:
    def opener(request: Any, *, timeout: int) -> Any:
        raise ValueError("bad")

    model = OrganiserChatModel(
        settings(),
        opener=opener,
    )

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete([])

    assert caught.value.classification == "OTHER"
    assert caught.value.status_code is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": {}},
        {"message": {"content": 42}},
        {"message": {"content": "   "}},
    ],
)
def test_gateway_malformed_response_fails_closed(payload: Mapping[str, Any]) -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(payload),
    )

    with pytest.raises(OrganiserGatewayResponseError):
        model.complete([])


def test_gateway_rejects_non_https_configuration() -> None:
    with pytest.raises(OrganiserGatewayConfigurationError):
        OrganiserGatewaySettings.from_environment(
            {
                "LLM_GATEWAY_URL": "http://api.softwaresystems.app",
                "LLM_GATEWAY_API_KEY": API_KEY,
                "LLM_MODEL": MODEL,
            }
        )


def test_gateway_invalid_outer_json_is_a_response_error() -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: RawResponse(b"not-json"),
    )

    with pytest.raises(OrganiserGatewayResponseError):
        model.complete([])


def test_gateway_cleanup_failure_does_not_mask_successful_result() -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: CloseFailingResponse(
            {"message": {"content": "ok"}}
        ),
    )

    assert model.complete([]) == "ok"


def test_gateway_cleanup_failure_does_not_mask_primary_request_failure() -> None:
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: ReadAndCloseFailingResponse({}),
    )

    with pytest.raises(OrganiserGatewayUnavailableError) as caught:
        model.complete([])

    assert caught.value.classification == "NETWORK_ERROR"


def test_gateway_configuration_is_loaded_from_environment_without_secret_repr() -> None:
    configured = OrganiserGatewaySettings.from_environment(
        {
            "LLM_GATEWAY_URL": GATEWAY_URL,
            "LLM_GATEWAY_API_KEY": API_KEY,
            "LLM_MODEL": MODEL,
        }
    )

    assert configured.gateway_url == GATEWAY_URL
    assert configured.api_key.get_secret_value() == API_KEY
    assert configured.model == MODEL
    assert configured.timeout_seconds <= 120
    assert configured.num_predict <= 4096
    assert API_KEY not in repr(configured)


def test_gateway_configuration_rejects_missing_required_values_without_echoing_secret() -> (
    None
):
    with pytest.raises(OrganiserGatewayConfigurationError) as caught:
        OrganiserGatewaySettings.from_environment(
            {"LLM_GATEWAY_URL": GATEWAY_URL, "LLM_MODEL": MODEL}
        )

    assert API_KEY not in str(caught.value)


def test_gateway_rejects_unbounded_prediction_and_timeout_values() -> None:
    with pytest.raises(ValidationError):
        settings(num_predict=4097)
    with pytest.raises(ValidationError):
        settings(timeout_seconds=121)


def test_gateway_does_not_emit_credentials_to_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    model = OrganiserChatModel(
        settings(),
        opener=lambda request, *, timeout: FakeResponse(
            {"message": {"content": '{"outcome":"ESCALATE"}'}}
        ),
    )

    model.complete([])

    assert API_KEY not in caplog.text
    assert API_KEY not in repr(model)

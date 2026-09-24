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
        "options": {"num_predict": 2048},
    }


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

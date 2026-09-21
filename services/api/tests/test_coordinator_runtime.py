import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.agent_contracts import (
    AgentInvocation,
    AgentOutcome,
    EscalationReason,
    InvocationMode,
)
from src.coordinator_runtime import (
    CoordinatorConfigurationError,
    CoordinatorRuntimeSettings,
    ModelOutputMalformedError,
    ModelOutputValidationError,
    ProviderAuthenticationError,
    ProviderUnavailableError,
    invoke_coordinator,
)

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def invocation() -> AgentInvocation:
    return AgentInvocation(
        run_id="RUN-1",
        invocation_mode=InvocationMode.MANUAL,
        trigger_id="EVENT-1",
        trigger_type="RUNTIME_SMOKE_TEST",
        captured_state_revision="STATE-1",
    )


def completion_payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "run_id": "RUN-1",
        "captured_state_revision": "STATE-1",
        "outcome": "ESCALATE",
        "escalation_reason": "MISSING_REQUIRED_DATA",
        "escalation_detail": None,
        "candidate_result_ref": None,
        "affected_plan_id": None,
        "affected_plan_version": None,
        "reason_codes": ["NO_BUSINESS_TOOLS_AVAILABLE"],
        "evidence_refs": [
            {
                "category": "EVENT_CONTEXT",
                "source": "BACKEND",
                "reference_id": "EVENT-1",
                "version": None,
                "state_revision": "STATE-1",
            }
        ],
        "summary": "Business inputs and deterministic tools are unavailable.",
        "schema_version": "1",
    }
    value.update(overrides)
    return value


def settings(tmp_path: Path) -> CoordinatorRuntimeSettings:
    executable = tmp_path / "openclaw"
    executable.write_text("test executable", encoding="utf-8")
    plugin = tmp_path / "amazon-bedrock-provider"
    plugin.mkdir(exist_ok=True)
    return CoordinatorRuntimeSettings(
        bedrock_model_id=MODEL_ID,
        aws_region="us-east-1",
        openclaw_executable=executable,
        provider_plugin_path=plugin,
    )


def runner_for(
    final: str,
    *,
    returncode: int = 0,
    ok: bool = True,
    status: str = "ok",
    error: dict[str, str] | None = None,
    inspect_call: Callable[[list[str], str], None] | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if inspect_call:
            inspect_call(command, str(kwargs["input"]))
        envelope = {
            "ok": ok,
            "status": status,
            "final": final,
            "error": error,
            "model": MODEL_ID,
            "provider": "amazon-bedrock",
        }
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=json.dumps(envelope),
            stderr="",
        )

    return run


def test_valid_coordinator_invocation_validates() -> None:
    assert AgentInvocation.model_validate(invocation().model_dump()).run_id == "RUN-1"
    with pytest.raises(ValidationError):
        AgentInvocation.model_validate(
            {
                "run_id": "",
                "invocation_mode": "MANUAL",
                "trigger_id": "EVENT-1",
                "trigger_type": "RUNTIME_SMOKE_TEST",
                "captured_state_revision": "STATE-1",
            }
        )


def test_valid_claude_json_parses_to_canonical_completion(tmp_path: Path) -> None:
    result = invoke_coordinator(
        invocation(),
        settings(tmp_path),
        process_runner=runner_for(json.dumps(completion_payload())),
    )
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.escalation_reason is EscalationReason.MISSING_REQUIRED_DATA


def test_malformed_model_json_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ModelOutputMalformedError, match="single JSON object"):
        invoke_coordinator(
            invocation(),
            settings(tmp_path),
            process_runner=runner_for("```json\n{}\n```"),
        )


def test_contract_invalid_model_json_is_rejected(tmp_path: Path) -> None:
    invalid = completion_payload(escalation_reason=None)
    with pytest.raises(ModelOutputValidationError, match="AgentCompletionPublication"):
        invoke_coordinator(
            invocation(),
            settings(tmp_path),
            process_runner=runner_for(json.dumps(invalid)),
        )


def test_provider_and_authentication_failures_are_distinct(tmp_path: Path) -> None:
    with pytest.raises(ProviderUnavailableError):
        invoke_coordinator(
            invocation(),
            settings(tmp_path),
            process_runner=runner_for(
                "",
                returncode=1,
                ok=False,
                status="error",
                error={"kind": "provider", "message": "Bedrock is unavailable"},
            ),
        )
    with pytest.raises(ProviderAuthenticationError):
        invoke_coordinator(
            invocation(),
            settings(tmp_path),
            process_runner=runner_for(
                "",
                returncode=1,
                ok=False,
                status="error",
                error={
                    "kind": "authentication",
                    "message": "AWS credentials were not accepted",
                },
            ),
        )
    with pytest.raises(CoordinatorConfigurationError):
        invoke_coordinator(
            invocation(),
            settings(tmp_path),
            process_runner=runner_for(
                "",
                returncode=1,
                ok=False,
                status="error",
                error={
                    "kind": "configuration",
                    "message": "Invalid model identifier",
                },
            ),
        )


def test_missing_bedrock_configuration_never_falls_back() -> None:
    with pytest.raises(CoordinatorConfigurationError):
        CoordinatorRuntimeSettings.from_environment({})
    with pytest.raises(CoordinatorConfigurationError):
        CoordinatorRuntimeSettings.from_environment(
            {"AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": "openai/gpt-5"}
        )


def test_runtime_has_no_business_tools_or_mutation_path(tmp_path: Path) -> None:
    checked = False

    def inspect_call(command: list[str], prompt: str) -> None:
        nonlocal checked
        config_path = Path(command[command.index("--config") + 1])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["tools"] == {"profile": "minimal"}
        assert config["plugins"]["allow"] == ["amazon-bedrock"]
        assert "restock-tools" not in json.dumps(config)
        assert "--fallback" not in command
        assert "create_plan" not in prompt
        assert "approve" not in prompt
        checked = True

    invoke_coordinator(
        invocation(),
        settings(tmp_path),
        process_runner=runner_for(
            json.dumps(completion_payload()), inspect_call=inspect_call
        ),
    )
    assert checked

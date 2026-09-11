"""Headless OpenClaw Coordinator runtime for the Bedrock smoke path.

The runtime has no business tools and no persistence dependency. It validates the
canonical invocation, delegates one text-only turn to OpenClaw, and validates the
returned canonical completion.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, Never

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.agent_contracts import AgentCompletionPublication, AgentInvocation
from src.errors import ErrorDetail, ErrorResponse

LOGGER = logging.getLogger(__name__)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OPENCLAW_PACKAGE = REPOSITORY_ROOT / "agent" / "restock-tools"
DEFAULT_PROVIDER_PLUGIN = (
    DEFAULT_OPENCLAW_PACKAGE
    / "node_modules"
    / "@openclaw"
    / "amazon-bedrock-provider"
)
PROVIDER = "amazon-bedrock"


class CoordinatorRuntimeError(RuntimeError):
    code = "COORDINATOR_RUNTIME_ERROR"


class CoordinatorConfigurationError(CoordinatorRuntimeError):
    code = "COORDINATOR_CONFIGURATION_ERROR"


class OpenClawUnavailableError(CoordinatorRuntimeError):
    code = "OPENCLAW_UNAVAILABLE"


class ProviderUnavailableError(CoordinatorRuntimeError):
    code = "MODEL_PROVIDER_UNAVAILABLE"


class ProviderAuthenticationError(CoordinatorRuntimeError):
    code = "MODEL_PROVIDER_AUTHENTICATION_FAILED"


class ModelOutputMalformedError(CoordinatorRuntimeError):
    code = "MODEL_OUTPUT_MALFORMED"


class ModelOutputValidationError(CoordinatorRuntimeError):
    code = "MODEL_OUTPUT_INVALID"


class CoordinatorRuntimeSettings(BaseModel):
    """Secret-free settings; AWS credentials stay in the SDK credential chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bedrock_model_id: str | None = None
    aws_region: str | None = None
    bedrock_base_url: str | None = None
    openclaw_executable: Path | None = None
    provider_plugin_path: Path = DEFAULT_PROVIDER_PLUGIN
    timeout_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def require_bedrock_configuration(self) -> "CoordinatorRuntimeSettings":
        if not self.bedrock_model_id or not self.bedrock_model_id.strip():
            raise ValueError("BEDROCK_MODEL_ID is required")
        if "anthropic.claude-sonnet-4-5" not in self.bedrock_model_id:
            raise ValueError("BEDROCK_MODEL_ID must identify Claude Sonnet 4.5")
        if not self.aws_region or not self.aws_region.strip():
            raise ValueError("AWS_REGION is required")
        return self

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "CoordinatorRuntimeSettings":
        if environment is None:
            environment = os.environ
        executable = environment.get("OPENCLAW_EXECUTABLE")
        plugin_path = environment.get("OPENCLAW_BEDROCK_PLUGIN_PATH")
        timeout = environment.get("COORDINATOR_TIMEOUT_SECONDS")
        values: dict[str, Any] = {
            "bedrock_model_id": environment.get("BEDROCK_MODEL_ID"),
            "aws_region": environment.get("AWS_REGION")
            or environment.get("AWS_DEFAULT_REGION"),
            "bedrock_base_url": environment.get("BEDROCK_BASE_URL"),
        }
        if executable:
            values["openclaw_executable"] = Path(executable)
        if plugin_path:
            values["provider_plugin_path"] = Path(plugin_path)
        if timeout:
            try:
                values["timeout_seconds"] = int(timeout)
            except ValueError as error:
                raise CoordinatorConfigurationError(
                    "COORDINATOR_TIMEOUT_SECONDS must be an integer"
                ) from error
        try:
            return cls.model_validate(values)
        except ValidationError as error:
            raise CoordinatorConfigurationError(
                "Bedrock Coordinator configuration is incomplete or invalid"
            ) from error

    @property
    def model_ref(self) -> str:
        assert self.bedrock_model_id is not None
        return f"{PROVIDER}/{self.bedrock_model_id}"

    @property
    def base_url(self) -> str:
        assert self.aws_region is not None
        return self.bedrock_base_url or (
            f"https://bedrock-runtime.{self.aws_region}.amazonaws.com"
        )


class OpenClawEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    status: str
    final: str | None = None
    error: dict[str, Any] | None = None
    model: str | None = None
    provider: str | None = None


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def _resolve_openclaw_executable(settings: CoordinatorRuntimeSettings) -> Path:
    if settings.openclaw_executable is not None:
        path = settings.openclaw_executable
    else:
        binary = "openclaw.cmd" if os.name == "nt" else "openclaw"
        path = DEFAULT_OPENCLAW_PACKAGE / "node_modules" / ".bin" / binary
    if not path.is_file():
        raise OpenClawUnavailableError(f"OpenClaw executable not found: {path}")
    return path


def _build_openclaw_config(settings: CoordinatorRuntimeSettings) -> dict[str, Any]:
    assert settings.bedrock_model_id is not None
    assert settings.aws_region is not None
    return {
        "plugins": {
            "allow": ["amazon-bedrock"],
            "load": {"paths": [str(settings.provider_plugin_path.resolve())]},
            "entries": {
                "amazon-bedrock": {
                    "enabled": True,
                    "config": {
                        "discovery": {
                            "enabled": False,
                            "region": settings.aws_region,
                        }
                    },
                }
            },
        },
        "models": {
            "providers": {
                PROVIDER: {
                    "baseUrl": settings.base_url,
                    "api": "bedrock-converse-stream",
                    "auth": "aws-sdk",
                    "models": [
                        {
                            "id": settings.bedrock_model_id,
                            "name": "Claude Sonnet 4.5 (Amazon Bedrock)",
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {
                                "input": 0,
                                "output": 0,
                                "cacheRead": 0,
                                "cacheWrite": 0,
                            },
                            "contextWindow": 200000,
                            "maxTokens": 4096,
                        }
                    ],
                }
            }
        },
        "agents": {"defaults": {"model": {"primary": settings.model_ref}}},
        "tools": {"profile": "minimal"},
    }


def _build_prompt(invocation: AgentInvocation) -> str:
    completion_schema = AgentCompletionPublication.model_json_schema()
    return "\n".join(
        [
            "You are the ReStock orchestration Coordinator.",
            "Return exactly one JSON object and no markdown or surrounding text.",
            "Do not perform authoritative calculations or mutate business state.",
            "Do not invent missing operational values.",
            "Do not output or persist chain-of-thought.",
            "No specialist agents or business tools are available in this runtime pass.",
            "For this smoke invocation, return ESCALATE with MISSING_REQUIRED_DATA.",
            "Use the trigger as BACKEND EVENT_CONTEXT evidence at the captured state revision.",
            "Preserve run_id, captured_state_revision, and affected plan fields exactly.",
            "Use reason_codes [\"NO_BUSINESS_TOOLS_AVAILABLE\"] and a concise summary.",
            f"Canonical completion JSON schema: {json.dumps(completion_schema, separators=(',', ':'))}",
            f"Validated invocation: {invocation.model_dump_json()}",
        ]
    )


def _raise_process_failure(envelope: OpenClawEnvelope | None, stderr: str) -> Never:
    message = "OpenClaw model invocation failed"
    kind = ""
    if envelope and envelope.error:
        message = str(envelope.error.get("message") or message)
        kind = str(envelope.error.get("kind") or "")
    diagnostic = f"{kind} {message} {stderr}".lower()
    if any(
        token in diagnostic
        for token in ("credential", "authentication", "unauthorized", "accessdenied")
    ):
        raise ProviderAuthenticationError(message)
    if any(
        token in diagnostic
        for token in ("configuration", "config", "invalid model identifier")
    ):
        raise CoordinatorConfigurationError(message)
    raise ProviderUnavailableError(message)


def _parse_envelope(stdout: str) -> OpenClawEnvelope:
    try:
        value = json.loads(stdout)
        return OpenClawEnvelope.model_validate(value)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ModelOutputMalformedError(
            "OpenClaw returned an invalid runtime envelope"
        ) from error


def _parse_completion(final_text: str) -> AgentCompletionPublication:
    try:
        value = json.loads(final_text)
    except json.JSONDecodeError as error:
        raise ModelOutputMalformedError(
            "Claude response was not a single JSON object"
        ) from error
    if not isinstance(value, dict):
        raise ModelOutputMalformedError("Claude response must be a JSON object")
    try:
        return AgentCompletionPublication.model_validate(value)
    except ValidationError as error:
        raise ModelOutputValidationError(
            "Claude response failed AgentCompletionPublication validation"
        ) from error


def _invoke_coordinator(
    invocation: AgentInvocation | Mapping[str, Any],
    settings: CoordinatorRuntimeSettings,
    *,
    process_runner: ProcessRunner = subprocess.run,
) -> AgentCompletionPublication:
    """Run one text-only Coordinator turn and return its canonical completion."""
    canonical_invocation = AgentInvocation.model_validate(invocation)
    executable = _resolve_openclaw_executable(settings)
    if not settings.provider_plugin_path.is_dir():
        raise CoordinatorConfigurationError(
            "Official OpenClaw Amazon Bedrock provider is not installed"
        )

    started = perf_counter()
    LOGGER.info(
        "Coordinator invocation started run_id=%s provider=%s model=%s",
        canonical_invocation.run_id,
        PROVIDER,
        settings.bedrock_model_id,
    )
    with tempfile.TemporaryDirectory(prefix="restock-openclaw-") as state_dir:
        state_path = Path(state_dir)
        config_path = state_path / "openclaw.json"
        config_path.write_text(
            json.dumps(_build_openclaw_config(settings)), encoding="utf-8"
        )
        command = [
            str(executable),
            "agent",
            "exec",
            "--message-file",
            "-",
            "--config",
            str(config_path),
            "--cwd",
            str(REPOSITORY_ROOT),
            "--model",
            settings.model_ref,
            "--code-mode",
            "direct",
            "--thinking",
            "off",
            "--timeout",
            str(settings.timeout_seconds),
            "--json",
        ]
        try:
            completed = process_runner(
                command,
                input=_build_prompt(canonical_invocation),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.timeout_seconds + 10,
                check=False,
            )
        except FileNotFoundError as error:
            raise OpenClawUnavailableError("OpenClaw executable is unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise ProviderUnavailableError("OpenClaw model invocation timed out") from error

    envelope = _parse_envelope(completed.stdout)
    if completed.returncode != 0 or not envelope.ok or envelope.status != "ok":
        _raise_process_failure(envelope, completed.stderr)
    if envelope.provider != PROVIDER:
        raise ProviderUnavailableError("OpenClaw used an unexpected model provider")
    if envelope.model != settings.bedrock_model_id:
        raise ProviderUnavailableError("OpenClaw used an unexpected model")
    if envelope.final is None:
        raise ModelOutputMalformedError("OpenClaw response did not contain final output")

    completion = _parse_completion(envelope.final)
    if completion.run_id != canonical_invocation.run_id:
        raise ModelOutputValidationError("Claude response changed the invocation run_id")
    if (
        completion.captured_state_revision
        != canonical_invocation.captured_state_revision
    ):
        raise ModelOutputValidationError(
            "Claude response changed the captured state revision"
        )
    if (completion.affected_plan_id, completion.affected_plan_version) != (
        canonical_invocation.affected_plan_id,
        canonical_invocation.affected_plan_version,
    ):
        raise ModelOutputValidationError("Claude response changed affected plan identity")

    LOGGER.info(
        "Coordinator invocation succeeded run_id=%s provider=%s model=%s validation=passed latency_ms=%d",
        canonical_invocation.run_id,
        PROVIDER,
        settings.bedrock_model_id,
        round((perf_counter() - started) * 1000),
    )
    return completion


def invoke_coordinator(
    invocation: AgentInvocation | Mapping[str, Any],
    settings: CoordinatorRuntimeSettings,
    *,
    process_runner: ProcessRunner = subprocess.run,
) -> AgentCompletionPublication:
    """Log the public runtime outcome without exposing prompt or credential data."""
    try:
        return _invoke_coordinator(
            invocation, settings, process_runner=process_runner
        )
    except CoordinatorRuntimeError as error:
        run_id = (
            invocation.run_id
            if isinstance(invocation, AgentInvocation)
            else invocation.get("run_id", "unknown")
        )
        LOGGER.warning(
            "Coordinator invocation failed run_id=%s provider=%s model=%s code=%s validation=failed",
            run_id,
            PROVIDER,
            settings.bedrock_model_id,
            error.code,
        )
        raise


def main() -> int:
    """Read one invocation from stdin and emit a canonical result or error."""
    try:
        invocation_value = json.load(sys.stdin)
        settings = CoordinatorRuntimeSettings.from_environment()
        completion = invoke_coordinator(invocation_value, settings)
    except (json.JSONDecodeError, ValidationError):
        response = ErrorResponse(
            error=ErrorDetail(
                code="INVALID_AGENT_INVOCATION",
                message="Input does not match the AgentInvocation contract",
            )
        )
        print(response.model_dump_json(exclude_none=True))
        LOGGER.warning("Coordinator invocation rejected validation=failed")
        return 2
    except CoordinatorRuntimeError as error:
        response = ErrorResponse(
            error=ErrorDetail(code=error.code, message=str(error), retryable=False)
        )
        print(response.model_dump_json(exclude_none=True))
        return 1
    print(completion.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

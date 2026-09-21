"""Strict machine-readable contracts for the local evaluation harness.

The manifest deliberately separates observed inputs from evaluator-only truth.
Adapters receive only :class:`ObservedBoundary`; hidden truth and expectations
are never part of that object.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agent_contracts import (
    EscalationDetail,
    EscalationReason,
    EventType,
    SpecialistType,
)


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class ScenarioStatus(StrEnum):
    RUNNABLE = "runnable"
    OPEN = "open"


class EvaluationOutcome(StrEnum):
    KEEP_CURRENT_PLAN = "KEEP_CURRENT_PLAN"
    REVISE_PLAN = "REVISE_PLAN"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"
    ESCALATE = "ESCALATE"
    FAILED = "FAILED"


class MetricStatus(StrEnum):
    SUPPORTED = "supported"
    PENDING = "pending"
    UNSUPPORTED = "unsupported"


class MetricValue(BaseModel):
    """A metric value with an honest availability state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: MetricStatus
    value: float | int | bool | None = None
    reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_value_state(self) -> MetricValue:
        if self.status is MetricStatus.SUPPORTED and self.value is None:
            raise ValueError("supported metrics require a value")
        if self.status is not MetricStatus.SUPPORTED and self.value is not None:
            raise ValueError("pending or unsupported metrics cannot contain a value")
        return self


class ObservedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    event_type: EventType | str = Field(min_length=1)
    occurred_at: datetime
    payload: dict[str, Any]


class EvidenceExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1)
    source: str = Field(min_length=1)
    reference: str | None = Field(default=None, min_length=1)


class ExpectedScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deterministic_evidence: tuple[EvidenceExpectation, ...] = ()
    relevant_domains: tuple[SpecialistType, ...] = ()
    routing: tuple[SpecialistType, ...] = ()
    final_outcome: EvaluationOutcome
    escalation_reason: EscalationReason | None = None
    escalation_detail: EscalationDetail | None = None
    business_metrics: dict[str, MetricValue] = {}

    @model_validator(mode="after")
    def validate_escalation(self) -> ExpectedScenario:
        if self.final_outcome is EvaluationOutcome.ESCALATE and self.escalation_reason is None:
            raise ValueError("escalation scenarios require an escalation reason")
        if self.final_outcome is not EvaluationOutcome.ESCALATE and (
            self.escalation_reason is not None or self.escalation_detail is not None
        ):
            raise ValueError("escalation reason/detail only apply to escalations")
        return self


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["restock-evaluation-scenario/1"]
    scenario_id: str = Field(min_length=1)
    scenario_version: str = Field(min_length=1)
    split: EvaluationSplit
    family: str = Field(min_length=1)
    status: ScenarioStatus = ScenarioStatus.RUNNABLE
    initial_authoritative_state: dict[str, Any]
    observed_events: tuple[ObservedEvent, ...] = ()
    policy_config_versions: dict[str, str] = {}
    expected: ExpectedScenario | None = None
    fixture_refs: tuple[str, ...] = ()
    hidden_evaluator_truth: dict[str, Any] | None = None
    open_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_status(self) -> ScenarioManifest:
        if self.status is ScenarioStatus.OPEN and self.open_reason is None:
            raise ValueError("open scenarios require an open_reason")
        if self.status is ScenarioStatus.RUNNABLE and self.open_reason is not None:
            raise ValueError("runnable scenarios cannot have an open_reason")
        if self.status is ScenarioStatus.RUNNABLE and self.expected is None:
            raise ValueError("runnable scenarios require expected results")
        return self

    def runtime_boundary(self) -> ObservedBoundary:
        """Project only observed, authoritative inputs into runtime context."""

        return ObservedBoundary(
            scenario_id=self.scenario_id,
            scenario_version=self.scenario_version,
            initial_authoritative_state=deepcopy(self.initial_authoritative_state),
            observed_events=tuple(deepcopy(event) for event in self.observed_events),
            policy_config_versions=deepcopy(self.policy_config_versions),
        )


class EvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["restock-evaluation-suite/1"]
    suite_id: str = Field(min_length=1)
    configuration_version: str = Field(min_length=1)
    scenarios: tuple[ScenarioManifest, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> EvaluationManifest:
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_id values must be unique")
        if not {scenario.split for scenario in self.scenarios} >= {
            EvaluationSplit.DEVELOPMENT,
            EvaluationSplit.HELD_OUT,
        }:
            raise ValueError("suite must contain development and held-out scenarios")
        return self


class ObservedBoundary(BaseModel):
    """The only scenario representation available to runtime systems."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    scenario_version: str
    initial_authoritative_state: dict[str, Any]
    observed_events: tuple[ObservedEvent, ...]
    policy_config_versions: dict[str, str]

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = _canonical_json(payload).encode("utf-8")
        return sha256(encoded).hexdigest()

    def as_runtime_inputs(self) -> dict[str, Any]:
        return deepcopy(self.model_dump(mode="json"))


class FailureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    retryable: bool = False


class SystemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    configuration_version: str = Field(min_length=1)
    observed_boundary_fingerprint: str = Field(min_length=1)
    outcome: EvaluationOutcome
    routing: tuple[SpecialistType, ...] = ()
    deterministic_evidence: tuple[EvidenceExpectation, ...] = ()
    specialist_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    retries: int = Field(ge=0)
    structured_output_valid: bool | None = None
    failure: FailureRecord | None = None
    escalation_reason: EscalationReason | None = None
    escalation_detail: EscalationDetail | None = None
    business_metrics: dict[str, MetricValue] = {}
    elapsed_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def preserve_failures(self) -> SystemResult:
        if self.outcome is EvaluationOutcome.FAILED and self.failure is None:
            raise ValueError("failed results must preserve a failure record")
        if self.outcome is EvaluationOutcome.ESCALATE and self.escalation_reason is None:
            raise ValueError("escalated results must preserve a reason")
        return self


class SystemSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str
    scenario_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    metrics: dict[str, MetricValue]


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    configuration_version: str
    scenarios: tuple[SystemResult, ...]
    summaries: tuple[SystemSummary, ...]


def _canonical_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

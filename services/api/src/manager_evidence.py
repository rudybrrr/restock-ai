"""Manager-safe projections of persisted planning and Agent evidence.

This module is deliberately a whitelist.  Audit payloads contain canonical
structured facts, but the projection never forwards the payload wholesale.
Private prompts, scratchpads, frozen state, and other implementation details
therefore cannot cross the manager API boundary accidentally.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.planning_schemas import PlanningRun, PurchasePlanVersion


class ManagerEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    source: str
    reference_id: str
    version: int | None = None
    state_revision: str | None = None
    producer_tool: str | None = None


class ManagerPlanReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    plan_id: str
    version: int
    status: str
    calculation_mode: str
    run_id: str
    created_at: AwareDatetime
    line_count: int = Field(ge=0)
    total_expected_cost: str


class ManagerTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str
    timestamp: AwareDatetime
    actor: str
    event_type: str | None = None
    state_revision: str | None = None
    invocation_mode: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    specialist: str | None = None
    specialist_call_id: str | None = None
    call_sequence: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    attempt_number: int | None = None
    tool_succeeded: bool | None = None
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[ManagerEvidenceRef] = Field(default_factory=list)
    summary: str


class ManagerApprovalAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    plan_id: str | None = None
    plan_version: int | None = None
    actor: str
    timestamp: AwareDatetime
    status: Literal["APPROVED", "REJECTED", "STALE", "UNKNOWN"]
    reason_codes: list[str] = Field(default_factory=list)
    summary: str


class ManagerApprovalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required: bool
    status: str
    plan_id: str | None = None
    plan_version: int | None = None
    latest_attempt: ManagerApprovalAttempt | None = None
    stale_attempts: list[ManagerApprovalAttempt] = Field(default_factory=list)


class ManagerRoutingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_mode: str | None = None
    trigger_type: str | None = None
    specialists: list[str] = Field(default_factory=list)
    specialist_calls: int = Field(ge=0)
    tool_calls: list[str] = Field(default_factory=list)
    tool_call_count: int = Field(ge=0)
    retries: int = Field(ge=0)


class ManagerValidationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    timestamp: AwareDatetime
    state_revision: str | None = None
    succeeded: bool | None = None
    evidence_refs: list[ManagerEvidenceRef] = Field(default_factory=list)
    summary: str


class ManagerDecisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    summary: str | None = None


class ManagerEvidenceGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ManagerEvaluationSummary(BaseModel):
    """Reserved for a persisted local evaluation result projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["available", "pending", "unsupported"]
    suite_id: str | None = None
    scenario_id: str | None = None
    summary: str


class ManagerRunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    run_status: str
    trigger: str
    trigger_event_id: str | None = None
    operational_cutoff: AwareDatetime
    input_revision: int
    claimed_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    active_plan: ManagerPlanReference | None = None
    plan_history: list[ManagerPlanReference] = Field(default_factory=list)
    approval: ManagerApprovalEvidence
    timeline: list[ManagerTimelineEntry] = Field(default_factory=list)
    routing: ManagerRoutingEvidence
    validation: list[ManagerValidationEvidence] = Field(default_factory=list)
    decision: ManagerDecisionEvidence
    evaluation: ManagerEvaluationSummary | None = None
    gaps: list[ManagerEvidenceGap] = Field(default_factory=list)


def _plan_reference(plan: PurchasePlanVersion) -> ManagerPlanReference:
    return ManagerPlanReference(
        id=plan.id,
        plan_id=plan.plan_id,
        version=plan.version,
        status=plan.status.value,
        calculation_mode=plan.calculation_mode,
        run_id=plan.run_id,
        created_at=plan.created_at,
        line_count=len(plan.lines),
        total_expected_cost=str(plan.total_expected_cost),
    )


def _safe_refs(value: Any) -> list[ManagerEvidenceRef]:
    if not isinstance(value, list):
        return []
    result: list[ManagerEvidenceRef] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        required = {"category", "source", "reference_id"}
        if not required <= item.keys():
            continue
        result.append(
            ManagerEvidenceRef(
                category=str(item["category"]),
                source=str(item["source"]),
                reference_id=str(item["reference_id"]),
                version=item.get("version"),
                state_revision=(
                    str(item["state_revision"])
                    if item.get("state_revision") is not None
                    else None
                ),
                producer_tool=(
                    str(item["producer_tool"])
                    if item.get("producer_tool") is not None
                    else None
                ),
            )
        )
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _summary(action: str, payload: Mapping[str, Any]) -> str:
    value = payload.get("summary")
    return str(value) if isinstance(value, str) and value else action.replace("_", " ").title()


def _timeline_entry(entry: Mapping[str, Any]) -> ManagerTimelineEntry:
    payload = entry.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    return ManagerTimelineEntry(
        id=str(entry["id"]),
        kind=str(entry.get("action") or "AUDIT"),
        timestamp=_timestamp(entry["timestamp"]),
        actor=str(entry.get("actor") or "unknown"),
        event_type=(str(payload["event_type"]) if payload.get("event_type") else None),
        state_revision=(
            str(payload["state_revision"]) if payload.get("state_revision") is not None else None
        ),
        invocation_mode=(
            str(payload["invocation_mode"]) if payload.get("invocation_mode") else None
        ),
        plan_id=str(payload["plan_id"]) if payload.get("plan_id") else None,
        plan_version=payload.get("plan_version"),
        specialist=(str(payload["specialist"]) if payload.get("specialist") else None),
        specialist_call_id=(
            str(payload["specialist_call_id"])
            if payload.get("specialist_call_id")
            else None
        ),
        call_sequence=payload.get("call_sequence"),
        tool_call_id=(str(payload["tool_call_id"]) if payload.get("tool_call_id") else None),
        tool_name=(str(payload["tool_name"]) if payload.get("tool_name") else None),
        attempt_number=payload.get("attempt_number"),
        tool_succeeded=(
            bool(payload["tool_succeeded"])
            if payload.get("tool_succeeded") is not None
            else None
        ),
        reason_codes=[str(code) for code in payload.get("reason_codes", []) if isinstance(code, str)],
        evidence_refs=_safe_refs(payload.get("evidence_refs")),
        summary=_summary(str(entry.get("action") or "AUDIT"), payload),
    )


def _approval_attempt(entry: ManagerTimelineEntry) -> ManagerApprovalAttempt:
    reason_codes = set(entry.reason_codes)
    if "PLAN_VERSION_STALE" in reason_codes:
        status: Literal["APPROVED", "REJECTED", "STALE", "UNKNOWN"] = "STALE"
    elif "APPROVED" in entry.summary.upper():
        status = "APPROVED"
    elif "REJECTED" in entry.summary.upper():
        status = "REJECTED"
    else:
        status = "UNKNOWN"
    return ManagerApprovalAttempt(
        id=entry.id,
        plan_id=entry.plan_id,
        plan_version=entry.plan_version,
        actor=entry.actor,
        timestamp=entry.timestamp,
        status=status,
        reason_codes=entry.reason_codes,
        summary=entry.summary,
    )


def build_manager_run_evidence(
    run: PlanningRun,
    plans: Sequence[PurchasePlanVersion],
    trigger_event: Mapping[Any, Any] | None,
    audits: Sequence[Mapping[Any, Any]],
) -> ManagerRunEvidence:
    """Build a manager-safe read projection from authoritative records."""

    plan_history = sorted(
        (_plan_reference(plan) for plan in plans),
        key=lambda plan: (plan.created_at, plan.version),
        reverse=True,
    )
    active_plan = next(
        (plan for plan in plan_history if plan.id == run.plan_version_id), None
    )
    timeline: list[ManagerTimelineEntry] = []
    if trigger_event is not None:
        timeline.append(
            ManagerTimelineEntry(
                id=str(trigger_event["id"]),
                kind="TRIGGER_EVENT",
                timestamp=_timestamp(trigger_event["timestamp"]),
                actor=str(trigger_event.get("source") or "unknown"),
                event_type=str(trigger_event.get("type") or run.trigger),
                summary=f"{trigger_event.get('type') or run.trigger} triggered this assessment.",
            )
        )
    timeline.extend(_timeline_entry(entry) for entry in audits)
    timeline.sort(key=lambda item: (item.timestamp, item.id))

    specialist_entries = [
        entry for entry in timeline if entry.kind == "SPECIALIST_CALLED" and entry.specialist
    ]
    tool_entries = [
        entry for entry in timeline if entry.kind in {"TOOL_CALLED", "TOOL_RESULT_RECORDED"}
    ]
    validation: list[ManagerValidationEvidence] = []
    for entry in timeline:
        validation_refs = [
            ref for ref in entry.evidence_refs if ref.category == "VALIDATION_RESULT"
        ]
        if entry.kind == "VALIDATION_COMPLETED":
            validation.append(
                ManagerValidationEvidence(
                    id=entry.id,
                    timestamp=entry.timestamp,
                    state_revision=entry.state_revision,
                    succeeded=entry.tool_succeeded,
                    evidence_refs=entry.evidence_refs,
                    summary=entry.summary,
                )
            )
        elif entry.kind == "TOOL_RESULT_RECORDED" and validation_refs:
            validation.append(
                ManagerValidationEvidence(
                    id=entry.id,
                    timestamp=entry.timestamp,
                    state_revision=entry.state_revision,
                    succeeded=entry.tool_succeeded,
                    evidence_refs=validation_refs,
                    summary=entry.summary,
                )
            )
    approval_attempts = [
        _approval_attempt(entry)
        for entry in timeline
        if entry.kind == "APPROVAL_RECORDED"
    ]
    latest_attempt = approval_attempts[-1] if approval_attempts else None
    stale_attempts = [attempt for attempt in approval_attempts if attempt.status == "STALE"]

    decision_entry = next(
        (entry for entry in reversed(timeline) if entry.kind == "RUN_COMPLETED"), None
    )
    decision = ManagerDecisionEvidence(
        outcome=run.outcome.value if run.outcome is not None else None,
        reason_codes=(
            decision_entry.reason_codes
            if decision_entry is not None
            else ([run.escalation_reason] if run.escalation_reason else [])
        ),
        summary=(
            decision_entry.summary
            if decision_entry is not None
            else None
        ),
    )

    gaps: list[ManagerEvidenceGap] = [
        ManagerEvidenceGap(
            code="EVALUATION_NOT_PERSISTED",
            message="Local evaluation results are not persisted with this run.",
        )
    ]
    if run.status == "SUCCEEDED" and not decision_entry:
        gaps.append(
            ManagerEvidenceGap(
                code="DECISION_TRACE_NOT_RECORDED",
                message="The run completed without a persisted Coordinator completion summary.",
            )
        )
    if run.outcome == "REQUEST_HUMAN_APPROVAL" and active_plan is None:
        gaps.append(
            ManagerEvidenceGap(
                code="PENDING_PLAN_NOT_FOUND",
                message="The run requests approval but its exact plan version is unavailable.",
            )
        )

    return ManagerRunEvidence(
        run_id=run.id,
        run_status=run.status,
        trigger=run.trigger,
        trigger_event_id=run.trigger_event_id,
        operational_cutoff=run.as_of,
        input_revision=run.input_revision,
        claimed_at=run.claimed_at,
        completed_at=run.completed_at,
        active_plan=active_plan,
        plan_history=plan_history,
        approval=ManagerApprovalEvidence(
            required=active_plan is not None and active_plan.status == "PENDING_APPROVAL",
            status=active_plan.status if active_plan is not None else "NOT_AVAILABLE",
            plan_id=active_plan.plan_id if active_plan is not None else None,
            plan_version=active_plan.version if active_plan is not None else None,
            latest_attempt=latest_attempt,
            stale_attempts=stale_attempts,
        ),
        timeline=timeline,
        routing=ManagerRoutingEvidence(
            invocation_mode=next(
                (entry.invocation_mode for entry in timeline if entry.invocation_mode),
                None,
            ),
            trigger_type=run.trigger,
            specialists=[entry.specialist for entry in specialist_entries if entry.specialist],
            specialist_calls=len(specialist_entries),
            tool_calls=list(
                dict.fromkeys(entry.tool_name for entry in tool_entries if entry.tool_name)
            ),
            tool_call_count=len({entry.tool_call_id for entry in tool_entries if entry.tool_call_id}),
            retries=sum(
                1
                for entry in tool_entries
                if entry.kind == "TOOL_CALLED"
                and entry.attempt_number is not None
                and entry.attempt_number > 1
            ),
        ),
        validation=validation,
        decision=decision,
        gaps=gaps,
    )

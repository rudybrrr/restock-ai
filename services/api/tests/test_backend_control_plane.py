from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from src import planning
from src.agent_contracts import (
    AgentCompletionPublication,
    AgentInvocation,
    AgentOutcome,
    AuditAction,
    AuditEvent,
    EscalationReason,
    EventType,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    InvocationMode,
    PlanPublicationResult,
    SpecialistType,
    StateRevisionStaleError,
)
from src.backend_control_plane import run_backend_coordinator
from src.planning_schemas import Completion
from src.procurement_specialist import ProcurementReasoningModel, ProcurementToolPort

NOW = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)


def fake_session() -> Session:
    return cast(Session, object())


def invocation() -> AgentInvocation:
    return AgentInvocation(
        run_id="run-1",
        invocation_mode=InvocationMode.EVENT,
        trigger_id="event-1",
        trigger_type=EventType.SUPPLIER_AVAILABILITY_CHANGED,
        captured_state_revision="7",
        affected_plan_id="plan-1",
        affected_plan_version=2,
    )


def ref(category: EvidenceCategory, reference_id: str) -> EvidenceRef:
    return EvidenceRef(
        category=category,
        source=EvidenceSource.BACKEND,
        reference_id=reference_id,
        state_revision="7",
    )


def completion(outcome: AgentOutcome = AgentOutcome.ESCALATE) -> AgentCompletionPublication:
    return AgentCompletionPublication(
        run_id="run-1",
        captured_state_revision="7",
        outcome=outcome,
        escalation_reason=(
            EscalationReason.MISSING_REQUIRED_DATA
            if outcome is AgentOutcome.ESCALATE
            else None
        ),
        affected_plan_id="plan-1",
        affected_plan_version=2,
        evidence_refs=[ref(EvidenceCategory.EVENT_CONTEXT, "event-1")],
        summary="Recorded decision.",
    )


def trace() -> list[AuditEvent]:
    return [
        AuditEvent(
            audit_event_id="audit-1",
            timestamp=NOW,
            actor="COORDINATOR",
            action=AuditAction.RUN_COMPLETED,
            state_revision="7",
            trigger_id="event-1",
            plan_id="plan-1",
            plan_version=2,
            run_id="run-1",
            invocation_mode=InvocationMode.EVENT,
            event_type=EventType.SUPPLIER_AVAILABILITY_CHANGED,
            evidence_refs=[ref(EvidenceCategory.EVENT_CONTEXT, "event-1")],
            final_outcome=AgentOutcome.ESCALATE,
            reason_codes=[EscalationReason.MISSING_REQUIRED_DATA],
            summary="Recorded decision.",
        )
    ]


def test_adapter_uses_backend_context_services(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    session = fake_session()
    seen = []
    monkeypatch.setattr(
        planning,
        "get_event_context",
        lambda actual_session, run_id, event_id: seen.append(
            (actual_session, run_id, event_id)
        ),
    )
    monkeypatch.setattr(
        planning,
        "get_active_plan",
        lambda actual_session, plan_id: type(
            "StoredPlan", (), {"run_id": "plan-run-2", "version": 2}
        )(),
    )
    monkeypatch.setattr(
        planning,
        "get_run",
        lambda actual_session, run_id: SimpleNamespace(input_revision=7),
    )

    adapter = BackendCoordinatorControlPlane(session)

    assert adapter.get_event_context(invocation()) == ref(
        EvidenceCategory.EVENT_CONTEXT, "event-1"
    )
    assert adapter.get_active_plan(invocation()) == [
        EvidenceRef(
            category=EvidenceCategory.CANDIDATE_RESULT,
            source=EvidenceSource.BACKEND,
            reference_id="plan-run-2:candidate",
            version=2,
            state_revision="7",
        )
    ]
    assert seen == [(session, "run-1", "event-1")]


def test_active_plan_evidence_uses_the_plan_certified_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    monkeypatch.setattr(
        planning,
        "get_active_plan",
        lambda actual_session, plan_id: SimpleNamespace(
            run_id="plan-run-2", version=2
        ),
    )
    monkeypatch.setattr(
        planning,
        "get_run",
        lambda actual_session, run_id: SimpleNamespace(input_revision=4),
    )

    refs = BackendCoordinatorControlPlane(fake_session()).get_active_plan(invocation())

    assert len(refs) == 1
    assert refs[0].reference_id == "plan-run-2:candidate"
    assert refs[0].state_revision == "4"


def test_local_backend_runner_composes_coordinator_and_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(
        id="run-1",
        status="RUNNING",
        trigger="MANUAL_REASSESSMENT_REQUESTED",
        trigger_event_id="event-1",
        input_revision=7,
        snapshot={},
    )
    expected = PlanPublicationResult(
        run_id="run-1",
        state_revision="7",
        requested_outcome=AgentOutcome.KEEP_CURRENT_PLAN,
        audit_event_refs=[ref(EvidenceCategory.AUDIT_EVENT, "audit-1")],
        published_at=NOW,
    )
    monkeypatch.setattr(planning, "get_run", lambda actual_session, run_id: run)
    monkeypatch.setattr(
        planning, "get_active_plan", lambda actual_session, plan_id: None
    )
    monkeypatch.setattr(
        planning,
        "get_event_context",
        lambda actual_session, run_id, event_id: {"id": event_id},
    )
    monkeypatch.setattr(
        planning,
        "publish_agent_completion",
        lambda actual_session, actual_completion, actual_trace: expected,
    )

    class NoRoutes:
        def classify(
            self,
            invocation: AgentInvocation,
            context_refs: Sequence[EvidenceRef],
        ) -> Sequence[SpecialistType]:
            return []

    execution = run_backend_coordinator(
        fake_session(),
        "run-1",
        cast(ProcurementReasoningModel, object()),
        cast(ProcurementToolPort, object()),
        manual_classifier=NoRoutes(),
    )

    assert execution.completion.outcome is AgentOutcome.KEEP_CURRENT_PLAN
    assert execution.publication_result is expected


def test_adapter_builds_invocation_from_claimed_backend_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    session = fake_session()
    run = SimpleNamespace(
        id="run-1",
        status="RUNNING",
        trigger="MANUAL_REASSESSMENT_REQUESTED",
        trigger_event_id="event-1",
        input_revision=7,
        snapshot={"revises_plan_id": "plan-1"},
    )
    plan = SimpleNamespace(plan_id="plan-1", version=2)
    monkeypatch.setattr(planning, "get_run", lambda actual_session, run_id: run)
    monkeypatch.setattr(
        planning, "get_active_plan", lambda actual_session, plan_id: plan
    )

    actual = BackendCoordinatorControlPlane(session).get_invocation("run-1")

    assert actual == AgentInvocation(
        run_id="run-1",
        invocation_mode=InvocationMode.MANUAL,
        trigger_id="event-1",
        trigger_type="MANUAL_REASSESSMENT_REQUESTED",
        captured_state_revision="7",
        affected_plan_id="plan-1",
        affected_plan_version=2,
    )


def test_adapter_validates_candidate_through_backend_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    session = fake_session()
    candidate = ref(EvidenceCategory.CANDIDATE_RESULT, "run-1:candidate")
    seen = []
    monkeypatch.setattr(
        planning,
        "validate_candidate_reference",
        lambda actual_session, run_id, reference_id, captured_revision: seen.append(
            (actual_session, run_id, reference_id, captured_revision)
        ),
    )

    result = BackendCoordinatorControlPlane(session).validate_final_plan(
        invocation(), candidate
    )

    assert result == ref(EvidenceCategory.VALIDATION_RESULT, "run-1:validation")
    assert seen == [(session, "run-1", "run-1:candidate", "7")]


def test_adapter_publishes_completion_and_trace_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    session = fake_session()
    expected = PlanPublicationResult(
        run_id="run-1",
        state_revision="7",
        requested_outcome=AgentOutcome.ESCALATE,
        audit_event_refs=[ref(EvidenceCategory.AUDIT_EVENT, "audit-1")],
        published_at=NOW,
    )
    seen = []

    def publish(actual_session, actual_completion, actual_trace):
        seen.append((actual_session, actual_completion, actual_trace))
        return expected

    monkeypatch.setattr(planning, "publish_agent_completion", publish)

    actual_completion = completion()
    actual_trace = trace()
    adapter = BackendCoordinatorControlPlane(session)
    tool_event = actual_trace[0].model_copy(
        update={
            "audit_event_id": "audit-tool-1",
            "action": AuditAction.TOOL_CALLED,
            "final_outcome": None,
        }
    )
    adapter.record(tool_event)
    result = adapter.record_agent_decision(actual_completion, actual_trace)

    assert result is expected
    assert seen == [(session, actual_completion, [tool_event, *actual_trace])]


def test_adapter_preserves_canonical_stale_revision_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    def stale(*args):
        raise StateRevisionStaleError("stale")

    monkeypatch.setattr(planning, "publish_agent_completion", stale)

    with pytest.raises(StateRevisionStaleError):
        BackendCoordinatorControlPlane(fake_session()).record_agent_decision(
            completion(), trace()
        )


def test_adapter_checks_human_review_target_through_backend_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend_control_plane import BackendCoordinatorControlPlane

    session = fake_session()
    seen = []
    monkeypatch.setattr(
        planning,
        "validate_human_review_request",
        lambda actual_session, actual_completion: seen.append(
            (actual_session, actual_completion)
        ),
    )
    review = completion(AgentOutcome.REQUEST_HUMAN_APPROVAL)

    BackendCoordinatorControlPlane(session).request_human_review(review)

    assert seen == [(session, review)]


def test_backend_completion_accepts_all_canonical_escalation_reasons() -> None:
    for reason in EscalationReason:
        assert Completion(
            outcome=AgentOutcome.ESCALATE, escalation_reason=reason
        ).escalation_reason is reason

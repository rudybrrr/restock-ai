"""One-shot application worker for queued ReStock assessments."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src import planning
from src.agent_contracts import (
    AgentInvocation,
    AgentOutcome,
    EscalationReason,
    EvidenceRef,
    SpecialistType,
    StateRevisionStaleError,
)
from src.backend_control_plane import run_backend_coordinator
from src.config import Settings
from src.decision_engine_adapter import BackendProcurementTools
from src.errors import ApiError
from src.organiser_gateway import build_organiser_reasoning_models

WorkerPublicationStatus = Literal[
    "NO_WORK", "PUBLISHED", "NOT_PUBLISHED", "STALE_REJECTED"
]
type WorkerFailureClassification = EscalationReason | Literal[
    "NO_QUEUED_RUN", "STATE_REVISION_STALE"
]


class QueuedAssessmentWorkerResult(BaseModel):
    """Safe operational metadata returned by one worker invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str | None
    outcome: AgentOutcome | None
    publication_status: WorkerPublicationStatus
    publication_reference: str | None = None
    failure_classification: WorkerFailureClassification | None = None


class _FullPlanningRouteClassifier:
    """Use the existing manual route seam for a normal manager assessment."""

    def classify(
        self,
        invocation: AgentInvocation,
        context_refs: Sequence[EvidenceRef],
    ) -> list[SpecialistType]:
        del invocation, context_refs
        return [
            SpecialistType.DEMAND,
            SpecialistType.INVENTORY,
            SpecialistType.PROCUREMENT,
        ]


def _no_work_result() -> QueuedAssessmentWorkerResult:
    return QueuedAssessmentWorkerResult(
        run_id=None,
        outcome=None,
        publication_status="NO_WORK",
        failure_classification="NO_QUEUED_RUN",
    )


def run_one_queued_assessment(
    session: Session, settings: Settings | None = None
) -> QueuedAssessmentWorkerResult:
    """Claim and execute at most one queued assessment through Backend."""

    try:
        claimed = planning.claim_run(session)
    except ApiError as error:
        if error.detail.code == "NO_QUEUED_RUN":
            return _no_work_result()
        raise

    reasoning_models = build_organiser_reasoning_models(settings)
    try:
        execution = run_backend_coordinator(
            session,
            claimed.id,
            reasoning_models.procurement,
            BackendProcurementTools(session),
            demand_model=reasoning_models.demand,
            inventory_model=reasoning_models.inventory,
            manual_classifier=_FullPlanningRouteClassifier(),
        )
    except StateRevisionStaleError:
        return QueuedAssessmentWorkerResult(
            run_id=claimed.id,
            outcome=None,
            publication_status="STALE_REJECTED",
            failure_classification="STATE_REVISION_STALE",
        )

    publication = execution.publication_result
    persisted = planning.get_run(session, claimed.id)
    return QueuedAssessmentWorkerResult(
        run_id=claimed.id,
        outcome=execution.completion.outcome,
        publication_status="PUBLISHED" if publication is not None else "NOT_PUBLISHED",
        publication_reference=persisted.plan_version_id,
        failure_classification=execution.completion.escalation_reason,
    )


def main() -> None:
    """Execute one queued assessment using the configured application services."""

    settings = Settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            result = run_one_queued_assessment(session, settings)
            print(result.model_dump_json(exclude_none=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

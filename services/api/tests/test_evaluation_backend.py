from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.agent_contracts import SpecialistType
from src.evaluation.adapters import (
    BackendAgentAdapter,
    FirstSliceProcurementScript,
    SeededBackendScenarioPreparer,
)
from src.evaluation.contracts import EvaluationOutcome, ObservedBoundary


class ProcurementOnlyClassifier:
    def classify(self, invocation, context_refs):
        return [SpecialistType.PROCUREMENT]


def test_backend_agent_adapter_uses_real_lifecycle_and_tools(database_url: str) -> None:
    engine = create_engine(database_url)
    boundary = ObservedBoundary(
        scenario_id="backend-adapter",
        scenario_version="1",
        initial_authoritative_state={"as_of": "2026-02-15T22:00:00+08:00"},
        observed_events=(),
        policy_config_versions={"procurement": "seed-policy-v1"},
    )

    try:
        adapter = BackendAgentAdapter(
            lambda: Session(engine),
            SeededBackendScenarioPreparer(),
            FirstSliceProcurementScript(),
            manual_classifier=ProcurementOnlyClassifier(),
        )
        result = adapter.run(boundary)
    finally:
        engine.dispose()

    assert result.outcome is EvaluationOutcome.REVISE_PLAN
    assert result.failure is None
    assert result.specialist_calls == 1
    assert result.tool_calls == 2
    assert result.observed_boundary_fingerprint == boundary.fingerprint

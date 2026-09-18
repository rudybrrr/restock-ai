from dataclasses import dataclass

from src.agent_contracts import SpecialistType
from src.evaluation.adapters import (
    KernelResult,
    RuleBaselineAdapter,
    ScriptedAgentAdapter,
    StaticBaselineAdapter,
)
from src.evaluation.contracts import (
    EvaluationManifest,
    EvaluationOutcome,
    FailureRecord,
    MetricStatus,
    MetricValue,
    ScenarioManifest,
    SystemResult,
)
from src.evaluation.runner import EvaluationRunner


def scenario(scenario_id: str, *, split: str = "development", event: str | None = None) -> ScenarioManifest:
    return ScenarioManifest.model_validate(
        {
            "schema_version": "restock-evaluation-scenario/1",
            "scenario_id": scenario_id,
            "scenario_version": "1",
            "split": split,
            "family": "test",
            "initial_authoritative_state": {"as_of": "2026-02-15T22:00:00+08:00"},
            "observed_events": (
                [{
                    "event_id": f"{scenario_id}-event",
                    "event_type": event,
                    "occurred_at": "2026-02-15T12:00:00Z",
                    "payload": {},
                }]
                if event
                else []
            ),
            "policy_config_versions": {"test": "v1"},
            "expected": {
                "routing": ["PROCUREMENT"] if event else [],
                "final_outcome": "REVISE_PLAN" if event else "KEEP_CURRENT_PLAN",
            },
        }
    )


def suite(*scenarios_: ScenarioManifest) -> EvaluationManifest:
    return EvaluationManifest(
        schema_version="restock-evaluation-suite/1",
        suite_id="test-suite",
        configuration_version="test-config-v1",
        scenarios=scenarios_,
    )


class RecordingKernel:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.boundaries = []
        self.failing = failing or set()

    def plan(self, boundary):
        self.boundaries.append(boundary)
        if boundary.scenario_id in self.failing:
            raise RuntimeError("kernel failure")
        return KernelResult(
            EvaluationOutcome.REVISE_PLAN,
            deterministic_evidence=(),
        )


@dataclass(frozen=True)
class EventRules:
    def should_replan(self, boundary) -> bool:
        return bool(boundary.observed_events)

    def routing(self, boundary):
        return [SpecialistType.PROCUREMENT] if boundary.observed_events else []


class ScriptedExecutor:
    def run(self, boundary):
        return SystemResult(
            system="adaptive_restock",
            scenario_id=boundary.scenario_id,
            configuration_version="adaptive-local-v1",
            observed_boundary_fingerprint=boundary.fingerprint,
            outcome=EvaluationOutcome.REVISE_PLAN if boundary.observed_events else EvaluationOutcome.KEEP_CURRENT_PLAN,
            routing=(SpecialistType.PROCUREMENT,) if boundary.observed_events else (),
            specialist_calls=1 if boundary.observed_events else 0,
            tool_calls=2 if boundary.observed_events else 0,
            retries=0,
            structured_output_valid=True,
            business_metrics={
                "food_waste": MetricValue(status=MetricStatus.UNSUPPORTED, reason="test")
            },
            elapsed_ms=1,
        )


class MutatingExecutor:
    def run(self, boundary):
        fingerprint = boundary.fingerprint
        boundary.initial_authoritative_state["mutated"] = True
        return ScriptedExecutor().run(boundary).model_copy(
            update={"observed_boundary_fingerprint": fingerprint}
        )


def test_all_systems_receive_identical_observed_boundary_and_replay_is_deterministic() -> None:
    cases = (scenario("normal"), scenario("supplier", event="SUPPLIER_PRICE_CHANGED"), scenario("held", split="held_out", event="SUPPLIER_PRICE_CHANGED"))
    kernel = RecordingKernel()
    runner = EvaluationRunner(
        suite(*cases),
        {
            "static": StaticBaselineAdapter(kernel),
            "rule": RuleBaselineAdapter(kernel, EventRules()),
            "adaptive_restock": __import__("src.evaluation.adapters", fromlist=["ScriptedAgentAdapter"]).ScriptedAgentAdapter(ScriptedExecutor()),
        },
    )

    first = runner.run(split="development")
    second = runner.run(split="development")

    first_fingerprints = {(row.system, row.scenario_id): row.observed_boundary_fingerprint for row in first.scenarios}
    second_fingerprints = {(row.system, row.scenario_id): row.observed_boundary_fingerprint for row in second.scenarios}
    assert first_fingerprints == second_fingerprints
    assert len({row.observed_boundary_fingerprint for row in first.scenarios if row.scenario_id == "supplier"}) == 1
    assert {row.scenario_id for row in first.scenarios} == {"normal", "supplier"}
    assert {row.scenario_id for row in runner.run(split="held_out").scenarios} == {"held"}


def test_failed_scenarios_are_retained_and_live_metrics_remain_pending() -> None:
    case = scenario("failure", event="SUPPLIER_PRICE_CHANGED")
    runner = EvaluationRunner(
        suite(case, scenario("held", split="held_out")),
        {"static": StaticBaselineAdapter(RecordingKernel({"failure"}))},
    )

    result = runner.run(split="development")
    row = result.scenarios[0]
    summary = result.summaries[0]

    assert row.outcome is EvaluationOutcome.FAILED
    assert row.failure == FailureRecord(code="RuntimeError", detail="kernel failure")
    assert summary.failed_count == 1
    assert summary.metrics["token_usage"].status is MetricStatus.PENDING
    assert summary.metrics["model_calls"].status is MetricStatus.PENDING


def test_each_system_gets_a_fresh_projection_of_the_same_boundary() -> None:
    case = scenario("mutation", event="SUPPLIER_PRICE_CHANGED")
    runner = EvaluationRunner(
        suite(case, scenario("held", split="held_out")),
        {
            "mutator": ScriptedAgentAdapter(MutatingExecutor()),
            "observer": ScriptedAgentAdapter(ScriptedExecutor()),
        },
    )

    result = runner.run(split="development")

    assert len({row.observed_boundary_fingerprint for row in result.scenarios}) == 1

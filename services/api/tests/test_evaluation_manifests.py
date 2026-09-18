import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evaluation.contracts import ScenarioManifest
from src.evaluation.manifests import load_manifest, runtime_projection

MANIFEST = Path(__file__).parent / "fixtures" / "evaluation" / "scenarios_v1.json"


def test_canonical_suite_is_strict_and_separates_splits() -> None:
    suite = load_manifest(MANIFEST)

    assert suite.suite_id == "restock-local-authoritative-v1"
    assert len(suite.scenarios) == 18
    assert {scenario.split.value for scenario in suite.scenarios} == {"development", "held_out"}
    assert sum(scenario.status.value == "runnable" for scenario in suite.scenarios) == 17
    assert sum(scenario.status.value == "open" for scenario in suite.scenarios) == 1
    assert {
        scenario.scenario_id
        for scenario in suite.scenarios
        if scenario.family == "sales_materiality"
    } == {"open-sales-materiality-001"}


def test_runtime_projection_excludes_expectations_and_hidden_truth() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["scenarios"][0]["hidden_evaluator_truth"] = {
        "future_stockouts": {"chicken": 3},
    }
    scenario = ScenarioManifest.model_validate(raw["scenarios"][0])

    projected = runtime_projection(scenario)

    assert set(projected) == {
        "scenario_id",
        "scenario_version",
        "initial_authoritative_state",
        "observed_events",
        "policy_config_versions",
    }
    assert "future_stockouts" not in json.dumps(projected, sort_keys=True)


def test_manifest_rejects_unknown_fields_and_open_sales_contract() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"][0]
    raw["unexpected"] = True
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(raw)

    sales = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"][0]
    sales["scenario_id"] = "sales-open"
    sales["family"] = "sales_materiality"
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(sales)

    sales["status"] = "open"
    sales["open_reason"] = "ML-owned sales materiality contract is not landed"
    sales["expected"] = None
    assert ScenarioManifest.model_validate(sales).expected is None

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
    } == {"development-sales-materiality-001"}


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


def test_manifest_rejects_unknown_fields_and_accepts_landed_sales_contract() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"][0]
    raw["unexpected"] = True
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(raw)

    sales = next(
        scenario
        for scenario in json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"]
        if scenario["family"] == "sales_materiality"
    )
    assert ScenarioManifest.model_validate(sales).status.value == "runnable"

    inventory = next(
        scenario
        for scenario in json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"]
        if scenario["family"] == "inventory_correction"
    )
    assert ScenarioManifest.model_validate(inventory).status.value == "open"

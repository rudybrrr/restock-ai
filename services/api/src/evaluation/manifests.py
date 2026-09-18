"""Manifest loading and strict evaluator/runtime boundary checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.evaluation.contracts import EvaluationManifest, ScenarioManifest


def load_manifest(path: str | Path) -> EvaluationManifest:
    """Load one canonical suite; malformed or duplicate scenarios fail closed."""

    source = Path(path)
    return EvaluationManifest.model_validate_json(source.read_text(encoding="utf-8"))


def runtime_projection(scenario: ScenarioManifest) -> dict[str, Any]:
    """Return the exact payload permitted to enter a runtime adapter."""

    return scenario.runtime_boundary().as_runtime_inputs()


def assert_no_evaluator_truth(runtime_inputs: dict[str, Any], scenario: ScenarioManifest) -> None:
    """Guard the non-leakage invariant at the adapter boundary."""

    forbidden = {
        "hidden_evaluator_truth",
        "expected",
        "open_reason",
        "evaluator_truth",
        "future_truth",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise AssertionError("evaluator-only truth entered runtime inputs")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(runtime_inputs)
    if scenario.hidden_evaluator_truth is not None:
        encoded_runtime = json.dumps(runtime_inputs, sort_keys=True, default=str)
        encoded_truth = json.dumps(scenario.hidden_evaluator_truth, sort_keys=True, default=str)
        if encoded_truth and encoded_truth in encoded_runtime:
            raise AssertionError("evaluator-only truth value entered runtime inputs")

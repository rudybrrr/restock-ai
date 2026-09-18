"""Local, provider-free evaluation contracts and runners."""

from src.evaluation.adapters import (
    BackendAgentAdapter,
    RuleBaselineAdapter,
    ScriptedAgentAdapter,
    StaticBaselineAdapter,
)
from src.evaluation.contracts import (
    EvaluationManifest,
    EvaluationResult,
    MetricValue,
    ScenarioManifest,
)
from src.evaluation.manifests import load_manifest
from src.evaluation.runner import EvaluationRunner

__all__ = [
    "BackendAgentAdapter",
    "EvaluationManifest",
    "EvaluationResult",
    "EvaluationRunner",
    "MetricValue",
    "RuleBaselineAdapter",
    "ScenarioManifest",
    "ScriptedAgentAdapter",
    "StaticBaselineAdapter",
    "load_manifest",
]

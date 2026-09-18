"""Repeatable local golden-demo preparation and execution.

The run path composes the existing Backend planning kernel, Coordinator,
specialists, and evaluation contracts. It does not use frontend fixtures or a
live model. Database reset is intentionally restricted to a database whose
name starts with restock_demo_.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src import database as db
from src import planning
from src.agent_contracts import SpecialistType
from src.errors import ApiError
from src.evaluation.adapters import (
    BackendAgentAdapter,
    BackendPlanningKernel,
    EventRoutingClassifier,
    FirstSliceProcurementScript,
    RuleBaselineAdapter,
    SeededBackendScenarioPreparer,
    StaticBaselineAdapter,
)
from src.evaluation.contracts import (
    EvaluationManifest,
    EvaluationResult,
    ObservedBoundary,
)
from src.evaluation.manifests import load_manifest
from src.evaluation.runner import EvaluationRunner
from src.operations import record_event
from src.planning_schemas import PlanDecision
from src.seed import seed


@dataclass(frozen=True)
class GoldenDemoScenario:
    label: str
    scenario: Any
    evidence_focus: tuple[str, ...]


_GOLDEN_SELECTION: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "supplier_replanning",
        "development-supplier-availability-001",
        ("materiality", "procurement routing", "replacement plan"),
    ),
    (
        "promotion_route",
        "development-promotion-001",
        ("promotion event", "demand routing", "plan revision"),
    ),
    (
        "delivery_disruption",
        "development-delivery-delay-001",
        ("delivery event", "inventory routing", "replanning"),
    ),
    (
        "sales_materiality",
        "development-sales-materiality-001",
        ("sales batch", "materiality contract", "fail-closed routing"),
    ),
    (
        "approval_stale_version",
        "development-stale-approval-001",
        ("exact version", "stale approval", "audit trace"),
    ),
)


def select_golden_scenarios(manifest: EvaluationManifest) -> tuple[GoldenDemoScenario, ...]:
    by_id = {scenario.scenario_id: scenario for scenario in manifest.scenarios}
    selected: list[GoldenDemoScenario] = []
    for label, scenario_id, focus in _GOLDEN_SELECTION:
        scenario = by_id.get(scenario_id)
        if scenario is None:
            raise ValueError(f"Golden demo scenario is missing: {scenario_id}")
        if scenario.status.value != "runnable":
            raise ValueError(f"Golden demo scenario is not runnable: {scenario_id}")
        selected.append(
            GoldenDemoScenario(label=label, scenario=scenario, evidence_focus=focus)
        )
    return tuple(selected)


def prepare_golden_demo(
    manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Write a safe, human-readable preparation manifest without evaluator truth."""

    manifest = load_manifest(manifest_path)
    selected = select_golden_scenarios(manifest)
    payload = _preparation_payload(manifest, selected)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _preparation_payload(
    manifest: EvaluationManifest,
    selected: tuple[GoldenDemoScenario, ...],
) -> dict[str, Any]:
    return {
        "schema_version": "restock-golden-demo/1",
        "suite_id": manifest.suite_id,
        "configuration_version": manifest.configuration_version,
        "scenario_count": len(selected),
        "scenarios": [
            {
                "label": item.label,
                "scenario_id": item.scenario.scenario_id,
                "scenario_version": item.scenario.scenario_version,
                "family": item.scenario.family,
                "split": item.scenario.split.value,
                "observed_event_types": [
                    event.event_type for event in item.scenario.observed_events
                ],
                "policy_config_versions": item.scenario.policy_config_versions,
                "fixture_refs": item.scenario.fixture_refs,
                "evidence_focus": item.evidence_focus,
                "runtime_boundary_fingerprint": item.scenario.runtime_boundary().fingerprint,
            }
            for item in selected
        ],
    }


def write_golden_output(
    output_path: str | Path,
    evaluation: EvaluationResult,
    preparation: dict[str, Any],
    approval_flow: dict[str, Any],
) -> dict[str, Any]:
    """Write one combined demo artifact without evaluator-only expectations."""

    payload = {
        "schema_version": "restock-golden-demo-result/1",
        "preparation": preparation,
        "evaluation": evaluation.model_dump(mode="json"),
        "approval_flow": approval_flow,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def reset_and_seed_demo_database(database_url: str) -> None:
    """Reset and reseed only an explicitly dedicated local demo database."""

    database_name = make_url(database_url).database or ""
    if not database_name.startswith("restock_demo_"):
        raise ValueError(
            "Demo reset requires a dedicated PostgreSQL database named restock_demo_..."
        )
    engine = create_engine(database_url)
    try:
        table_names = [
            table.name
            for table in db.metadata.sorted_tables
            if table.name != "alembic_version"
        ]
        quoted = ", ".join('"' + name.replace('"', '""') + '"' for name in table_names)
        with engine.begin() as connection:
            connection.execute(
                text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            )
    finally:
        engine.dispose()
    seed(database_url)


class _RuleRouting:
    def __init__(self, boundary: ObservedBoundary) -> None:
        self._classifier = EventRoutingClassifier(boundary)

    def should_replan(self, boundary: ObservedBoundary) -> bool:
        return bool(boundary.observed_events) or not boundary.observed_events

    def routing(self, boundary: ObservedBoundary) -> list[SpecialistType]:
        return list(self._classifier.classify(None, []))


class _IsolatedDemoAdapter:
    def __init__(self, database_url: str, system: str) -> None:
        self._database_url = database_url
        self._system = system

    def run(self, boundary: ObservedBoundary):
        reset_and_seed_demo_database(self._database_url)
        engine = create_engine(self._database_url)
        try:
            preparer = SeededBackendScenarioPreparer()
            session_factory = lambda: Session(engine)
            if self._system == "static":
                adapter = StaticBaselineAdapter(
                    BackendPlanningKernel(session_factory, preparer)
                )
            elif self._system == "rule":
                adapter = RuleBaselineAdapter(
                    BackendPlanningKernel(session_factory, preparer),
                    _RuleRouting(boundary),
                )
            else:
                adapter = BackendAgentAdapter(
                    session_factory,
                    preparer,
                    FirstSliceProcurementScript(),
                    manual_classifier=EventRoutingClassifier(boundary),
                )
            return adapter.run(boundary)
        finally:
            engine.dispose()


def _run_stale_approval_flow(
    database_url: str,
    scenario: GoldenDemoScenario,
) -> dict[str, Any]:
    """Exercise the real publication and exact-version stale approval guard."""

    reset_and_seed_demo_database(database_url)
    engine = create_engine(database_url)
    try:
        boundary = scenario.scenario.runtime_boundary()
        preparer = SeededBackendScenarioPreparer()
        adapter = BackendAgentAdapter(
            lambda: Session(engine),
            preparer,
            FirstSliceProcurementScript(),
            manual_classifier=EventRoutingClassifier(boundary),
        )
        agent_result = adapter.run(boundary)
        if agent_result.outcome.value != "REVISE_PLAN":
            return {
                "status": "NOT_AVAILABLE",
                "scenario_id": scenario.scenario.scenario_id,
                "agent_outcome": agent_result.outcome.value,
                "message": "The real local Agent path did not publish a pending plan.",
            }
        with Session(engine) as session:
            row = (
                session.execute(
                    select(db.plan_versions)
                    .where(db.plan_versions.c.status == "PENDING_APPROVAL")
                    .order_by(db.plan_versions.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return {
                    "status": "NOT_AVAILABLE",
                    "scenario_id": scenario.scenario.scenario_id,
                    "message": "No pending plan was persisted by the real local Agent path.",
                }
            plan = planning.read_plan(session, row["id"])
            record_event(
                session,
                "SUPPLIER_PRICE_CHANGED",
                "golden-demo",
                {
                    "offer_id": "fresh-chicken",
                    "field": "unit_price",
                    "previous": "4.50",
                    "value": "4.75",
                    "effective_at": "2026-02-16T08:30:00+08:00",
                },
            )
            try:
                planning.decide_plan(
                    session,
                    plan.id,
                    PlanDecision(
                        plan_id=plan.plan_id,
                        plan_version=plan.version,
                        decision="APPROVED",
                    ),
                    "manager",
                )
            except ApiError as error:
                audit = (
                    session.execute(
                        select(db.audit_entries)
                        .where(db.audit_entries.c.action == "APPROVAL_RECORDED")
                        .order_by(db.audit_entries.c.timestamp.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                return {
                    "status": "STALE" if error.detail.code == "PLAN_VERSION_STALE" else "FAILED",
                    "scenario_id": scenario.scenario.scenario_id,
                    "run_id": plan.run_id,
                    "plan_id": plan.plan_id,
                    "plan_version": plan.version,
                    "error_code": error.detail.code,
                    "message": error.detail.message,
                    "audit_event_id": audit["id"] if audit else None,
                    "audit_action": audit["action"] if audit else None,
                }
            return {
                "status": "UNEXPECTEDLY_APPROVED",
                "scenario_id": scenario.scenario.scenario_id,
                "run_id": plan.run_id,
                "plan_id": plan.plan_id,
                "plan_version": plan.version,
            }
    finally:
        engine.dispose()


def run_golden_demo(
    manifest_path: str | Path,
    output_path: str | Path,
    database_url: str,
) -> EvaluationResult:
    """Run the five supported golden scenarios through isolated local adapters."""

    manifest = load_manifest(manifest_path)
    selected = select_golden_scenarios(manifest)
    golden_manifest = manifest.model_copy(
        update={"scenarios": tuple(item.scenario for item in selected)}
    )
    runner = EvaluationRunner(
        golden_manifest,
        {
            "static": _IsolatedDemoAdapter(database_url, "static"),
            "rule": _IsolatedDemoAdapter(database_url, "rule"),
            "adaptive_restock": _IsolatedDemoAdapter(database_url, "adaptive"),
        },
    )
    evaluation = runner.run()
    preparation = _preparation_payload(manifest, selected)
    approval_flow = _run_stale_approval_flow(
        database_url,
        next(item for item in selected if item.label == "approval_stale_version"),
    )
    write_golden_output(output_path, evaluation, preparation, approval_flow)
    return evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or run the local ReStock golden demo."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--output", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--manifest", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--database-url", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "prepare":
        prepare_golden_demo(args.manifest, args.output)
    else:
        run_golden_demo(args.manifest, args.output, args.database_url)


if __name__ == "__main__":
    main()

from pathlib import Path

import pytest

MANIFEST = Path(__file__).parent / "fixtures" / "evaluation" / "scenarios_v1.json"


def test_golden_demo_selects_the_requested_operational_flows():
    from src.evaluation.local_demo import select_golden_scenarios
    from src.evaluation.manifests import load_manifest

    selected = select_golden_scenarios(load_manifest(MANIFEST))

    assert [item.label for item in selected] == [
        "supplier_replanning",
        "promotion_route",
        "delivery_disruption",
        "inventory_correction_safe",
        "inventory_correction_material",
        "sales_materiality",
        "approval_stale_version",
    ]
    assert [item.scenario.scenario_id for item in selected] == [
        "development-supplier-availability-001",
        "development-promotion-001",
        "development-delivery-delay-001",
        "development-inventory-correction-safe-001",
        "development-inventory-correction-material-001",
        "development-sales-materiality-001",
        "development-stale-approval-001",
    ]


def test_golden_demo_preparation_is_machine_readable_and_runtime_safe(tmp_path: Path):
    from src.evaluation.local_demo import prepare_golden_demo

    output = tmp_path / "golden-demo.json"
    result = prepare_golden_demo(MANIFEST, output)

    assert result["scenario_count"] == 7
    assert output.exists()
    assert all("hidden_evaluator_truth" not in row for row in result["scenarios"])
    assert all("expected" not in row for row in result["scenarios"])


def test_demo_reset_rejects_non_dedicated_database_targets():
    from src.evaluation.local_demo import reset_and_seed_demo_database

    with pytest.raises(ValueError, match="restock_demo_"):
        reset_and_seed_demo_database("postgresql+psycopg://demo@localhost/restock")


def test_golden_output_keeps_evaluation_and_approval_flow_sections(tmp_path: Path):
    from src.evaluation.contracts import EvaluationResult
    from src.evaluation.local_demo import write_golden_output

    result = EvaluationResult(
        suite_id="suite",
        configuration_version="config",
        scenarios=(),
        summaries=(),
    )
    payload = write_golden_output(
        tmp_path / "result.json",
        result,
        {"scenario_count": 5},
        {"status": "STALE", "error_code": "PLAN_VERSION_STALE"},
    )

    assert payload["evaluation"]["suite_id"] == "suite"
    assert payload["approval_flow"]["status"] == "STALE"

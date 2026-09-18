from datetime import UTC, datetime

from src.materiality import SALES_MATERIALITY_V1
from src.procurement_contracts import _build, first_slice_seed_rows
from src.sales_materiality_contracts import context_from_contract, seed_policy
from src.sales_threshold_schemas import FrozenSalesThresholdPolicy


def test_persisted_policy_matches_the_approved_numerical_definition():
    row = seed_policy(datetime(2026, 9, 18, tzinfo=UTC))
    payload = row["payload"]
    assert (
        payload["version"],
        payload["rule"],
        payload["absolute_floor"],
        payload["relative_threshold"],
        payload["minimum_expected_portions"],
        payload["minimum_complete_buckets"],
    ) == (
        SALES_MATERIALITY_V1.version,
        SALES_MATERIALITY_V1.rule,
        str(SALES_MATERIALITY_V1.absolute_floor),
        str(SALES_MATERIALITY_V1.relative_threshold),
        str(SALES_MATERIALITY_V1.minimum_expected_portions),
        SALES_MATERIALITY_V1.minimum_complete_buckets,
    )


def test_run_context_binds_policy_and_snapshot_evidence_to_one_revision():
    recorded_at = datetime(2026, 9, 18, tzinfo=UTC)
    rows = first_slice_seed_rows(recorded_at)
    contract = _build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    )
    policy = seed_policy(recorded_at)
    contract = contract.model_copy(
        update={
            "run_id": "run-1",
            "known_at": recorded_at,
            "captured_state_revision": "17",
            "sales_threshold_policy": FrozenSalesThresholdPolicy.model_validate(
                {
                    **policy,
                    "evidence": {
                        "reference": policy["id"],
                        "available_at": recorded_at,
                        "captured_revision": "17",
                    },
                }
            ),
        }
    )
    context = context_from_contract(contract)
    assert context.supported is True
    assert context.policy.payload.version == "SALES_MATERIALITY_V1"
    assert context.policy.evidence.captured_revision == "17"
    assert context.snapshot_evidence.captured_revision == "17"
    assert context.snapshot_reference == "run:run-1:snapshot:17"
    assert context.forecast_input_reference == contract.forecast_input.id

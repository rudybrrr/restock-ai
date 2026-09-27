import json
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

from test_procurement import reference as reference  # noqa: PLC0414

from src.history_dataset import Catalogue
from src.inventory_projection import SourceEvidence
from src.materiality import SALES_MATERIALITY_V1
from src.procurement_contracts import _build, first_slice_seed_rows
from src.promotion_forecasting import (
    SOURCES,
    ForecastVersion,
    ObservedPortions,
    PromotionUse,
)
from src.sales_materiality_contracts import (
    _canonical_hash,
    context_from_contract,
    seed_policy,
)
from src.sales_materiality_schemas import (
    SalesMaterialityEngineRequest,
    SalesThresholdPolicyInput,
    serialize_engine_request,
)
from src.sales_threshold_schemas import FrozenSalesThresholdPolicy
from src.service_buckets import ProjectedDemandBucket, ServicePeriod


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


def test_engine_request_serializes_and_round_trips_real_frozen_forecast(reference):
    recorded_at = datetime(2026, 9, 18, tzinfo=UTC)
    rows = first_slice_seed_rows(recorded_at)
    contract = _build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    ).model_copy(
        update={
            "run_id": "serialization-run",
            "known_at": recorded_at,
            "captured_state_revision": "17",
            "sales_threshold_policy": FrozenSalesThresholdPolicy.model_validate(
                {
                    **seed_policy(recorded_at),
                    "evidence": {
                        "reference": "sales-threshold-policy:SALES_MATERIALITY_V1",
                        "available_at": recorded_at,
                        "captured_revision": "17",
                    },
                }
            ),
        }
    )
    context = context_from_contract(contract)
    catalogue = Catalogue(
        menu_items=tuple(reference.inventory["menu_items"]),
        ingredients=tuple(reference.inventory["ingredients"]),
        recipes=tuple(reference.inventory["recipes"]),
    )
    evidence = SourceEvidence("forecast-source", contract.known_at, "17")
    profile = tuple(
        ServicePeriod(period.start, period.end, period.weight)
        for period in contract.policy.payload.service_profile
    )
    bucket_start, bucket_end = profile[0].start, profile[0].end
    bucket = ProjectedDemandBucket(
        bucket_start,
        bucket_end,
        {"tofu-bowl": Decimal("12.3400")},
    )
    assert isinstance(bucket.expected_portions, MappingProxyType)
    forecast = ForecastVersion(
        reference="forecast:immutable-v1",
        as_of=contract.as_of,
        known_at=contract.known_at,
        target_date=contract.policy.payload.target_date,
        profile=profile,
        sources=tuple(
            (name, SourceEvidence(f"source:{name}", contract.known_at, "17"))
            for name in sorted(SOURCES)
        ),
        buckets=(bucket,),
        promotion_state="APPLIED",
        base_reference="forecast:normal-v1",
        actuals=(
            ObservedPortions(
                bucket_start,
                bucket_end,
                (("tofu-bowl", 4),),
                "sales-batch-1",
                1,
                evidence,
            ),
        ),
        promotions=(
            PromotionUse(
                "promotion-event-1",
                "promotion-1",
                1,
                contract.known_at,
                bucket_start,
                "approved-multiplier",
                Decimal("1.125"),
                bucket_start,
                bucket_end,
                ("tofu-bowl",),
            ),
        ),
        context_evidence=evidence,
        actual_coverage=evidence,
        revision_evidence=(("promotion-1", 1, "promotion-event-1"),),
    )
    request = SalesMaterialityEngineRequest(
        contract_reference=context.procurement_contract_reference,
        contract=contract,
        issued_forecast_reference=forecast.reference,
        issued_forecast=forecast,
        issued_input=contract.forecast_input,
        issued_catalogue=catalogue,
        snapshot_evidence=context.snapshot_evidence,
        threshold_policy=SalesThresholdPolicyInput(
            **context.policy.payload.model_dump(), evidence=context.policy.evidence
        ),
        plan_reference=None,
        safety_reference="safety:17",
        risk=None,
    )

    payload = serialize_engine_request(request)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert encoded

    def assert_json_values(value):
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for item in value.values():
                assert_json_values(item)
        elif isinstance(value, list):
            for item in value:
                assert_json_values(item)
        else:
            assert value is None or isinstance(value, (str, int, float, bool))

    assert_json_values(payload)
    forecast_payload = cast(dict[str, Any], payload["issued_forecast"])
    assert forecast_payload["reference"] == forecast.reference
    assert forecast_payload["as_of"] == forecast.as_of.isoformat()
    assert forecast_payload["known_at"] == forecast.known_at.isoformat()
    assert forecast_payload["target_date"] == forecast.target_date.isoformat()
    assert forecast_payload["promotion_state"] == "APPLIED"
    assert forecast_payload["base_reference"] == forecast.base_reference
    assert forecast_payload["buckets"][0]["start"] == bucket_start.isoformat()
    assert forecast_payload["buckets"][0]["end"] == bucket_end.isoformat()
    assert forecast_payload["buckets"][0]["expected_portions"] == {
        "tofu-bowl": "12.3400"
    }
    assert forecast_payload["actuals"][0]["portions"] == [["tofu-bowl", 4]]
    assert forecast_payload["promotions"][0]["multiplier"] == "1.125"
    assert forecast_payload["profile"][0]["weight"] == str(profile[0].weight)
    assert forecast_payload["sources"][0][1]["reference"].startswith("source:")

    restored = SalesMaterialityEngineRequest.model_validate(payload)
    restored_forecast = restored.issued_forecast
    assert restored_forecast == forecast
    assert restored_forecast.buckets[0].expected_portions == {
        "tofu-bowl": Decimal("12.3400")
    }
    assert isinstance(restored_forecast.buckets[0].expected_portions, MappingProxyType)

    repeated_payload = serialize_engine_request(request)
    assert repeated_payload == payload
    assert _canonical_hash(repeated_payload) == _canonical_hash(payload)

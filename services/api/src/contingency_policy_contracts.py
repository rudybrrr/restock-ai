"""Persisted contingency-policy authority; staged values never select live runs."""

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import database as db
from src.contingency_policy_schemas import ContingencyPolicyVersion
from src.errors import ApiError

DEMO_POLICY_ID = "BOUNDED_CONTINGENCY_CASH_V1_DEMO"


def _validated_policy(row) -> ContingencyPolicyVersion:
    if row is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Contingency policy not found")
    try:
        return ContingencyPolicyVersion.model_validate(dict(row))
    except ValidationError as error:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Contingency policy invalid"
        ) from error


def read_policy(
    session: Session, policy_id: str, version: int
) -> ContingencyPolicyVersion:
    row = (
        session.execute(
            select(db.contingency_policy_versions).where(
                db.contingency_policy_versions.c.policy_id == policy_id,
                db.contingency_policy_versions.c.version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    return _validated_policy(row)


def read_policy_version_by_id(
    session: Session, version_id: str
) -> ContingencyPolicyVersion:
    row = (
        session.execute(
            select(db.contingency_policy_versions).where(
                db.contingency_policy_versions.c.id == version_id
            )
        )
        .mappings()
        .one_or_none()
    )
    return _validated_policy(row)


def first_case_seed_policy(recorded_at: datetime) -> dict:
    """Explicit synthetic numerical fixture values, staged pending full mapping."""
    ingredients = (
        "chicken",
        "rice",
        "noodles",
        "eggs",
        "tofu",
        "vegetables",
        "oil",
        "soy-sauce",
    )
    issue = "2026-02-16T10:00:00+08:00"
    protected = "2026-02-16T12:00:00+08:00"
    assessment = "2026-02-17T12:00:00+08:00"
    policy = ContingencyPolicyVersion.model_validate(
        {
            "id": f"policy:{DEMO_POLICY_ID}:1",
            "policy_id": DEMO_POLICY_ID,
            "version": 1,
            "effective_at": issue,
            "recorded_at": recorded_at,
            "source_revision": "ML_CONTINGENCY_CONTRACT_V1_DEMO_POLICY",
            "payload": {
                "source_kind": "EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE",
                "activation_state": "STAGED",
                "objective_policy": "BOUNDED_CONTINGENCY_CASH_V1",
                "search_policy": "CONTINGENCY_CARTESIAN_V1",
                "fee_policy": "EXPLICIT_NEW_SHIPMENT_ONCE_V1",
                "cash_policy": "CASH_SLICE_V1",
                "expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
                "tie_break_policy": "SUPPLIER_ID_THEN_INGREDIENT_ID_V1",
                "reliability_mode": "CONTEXT_ONLY",
                "constraint_policy": "SERVICE_END_SAFETY_RECEIPT_STORAGE_V1",
                "fefo_policy": "FEFO_EXPIRY_RECEIVED_LOT_ID_V1",
                "currency": "SGD",
                "issue_time": issue,
                "new_order_budget_sgd": "30",
                "safety_stock": dict.fromkeys(ingredients, "0"),
                "storage_limits": dict.fromkeys(ingredients, "30"),
                "protected_end": dict.fromkeys(ingredients, protected),
                "assessment_end": {
                    key: assessment if key == "vegetables" else protected
                    for key in ingredients
                },
                "max_horizon_days": 2,
                "work_limit": 10000,
                "approved_domain_id": None,
                "forecast_artifact_id": None,
            },
        }
    )
    return policy.model_dump(mode="json")


def first_case_seed_policy_v2(recorded_at: datetime) -> dict:
    """Stage exact catalogue/domain references without selecting live runs yet."""
    row = first_case_seed_policy(recorded_at)
    row["id"] = f"policy:{DEMO_POLICY_ID}:2"
    row["version"] = 2
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V2_DEMO_POLICY"
    row["payload"]["approved_domain_id"] = "BOUNDED_CONTINGENCY_20260216_DOMAIN_V1"
    row["payload"]["forecast_artifact_id"] = (
        "case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:2"
    )
    return ContingencyPolicyVersion.model_validate(row).model_dump(mode="json")


def first_case_seed_policy_v3(recorded_at: datetime) -> dict:
    """Point the staged demo policy at the explicitly approved quote version."""
    row = first_case_seed_policy_v2(recorded_at)
    row["id"] = f"policy:{DEMO_POLICY_ID}:3"
    row["version"] = 3
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V3_APPROVED_DEMO_POLICY"
    row["payload"]["forecast_artifact_id"] = (
        "case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:3"
    )
    return ContingencyPolicyVersion.model_validate(row).model_dump(mode="json")


def first_case_seed_policy_v4(recorded_at: datetime) -> dict:
    """Activate only the exact approved synthetic first-case domain."""
    row = first_case_seed_policy_v3(recorded_at)
    row["id"] = f"policy:{DEMO_POLICY_ID}:4"
    row["version"] = 4
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V4_ACTIVE_FIRST_CASE"
    row["payload"]["activation_state"] = "ACTIVE"
    row["payload"]["forecast_artifact_id"] = (
        "case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:4"
    )
    return ContingencyPolicyVersion.model_validate(row).model_dump(mode="json")


def post_purchase_seed_policy(recorded_at: datetime, *, version: int) -> dict:
    if version not in (5, 6):
        raise ValueError("Unsupported post-purchase version")
    row = first_case_seed_policy_v4(recorded_at)
    row["id"] = f"policy:{DEMO_POLICY_ID}:{version}"
    row["version"] = version
    row["source_revision"] = f"POST_PURCHASE_FIXED_SUPPLY_V1:{version}"
    if version == 6:
        row["effective_at"] = row["payload"]["issue_time"] = "2026-02-16T11:00:00+08:00"
    row["payload"]["approved_domain_id"] = f"POST_PURCHASE_20260216_DOMAIN_V{version}"
    row["payload"]["forecast_artifact_id"] = (
        f"case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:{version}"
    )
    return ContingencyPolicyVersion.model_validate(row).model_dump(mode="json")

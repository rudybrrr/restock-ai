"""Read the complete versioned synthetic case without inferring live state."""

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import database as db
from src.contingency_case_schemas import (
    ContingencyCaseInputVersion,
    approved_quote_sha256,
    catalogue_sha256,
)
from src.contingency_policy_contracts import DEMO_POLICY_ID, read_policy_version_by_id
from src.errors import ApiError
from src.procurement_contract_schemas import (
    FrozenOfferRevision,
    FrozenOrderingOpportunity,
)
from src.schemas import Ingredient, MenuItem, RecipeItem, Supplier

FIRST_CASE_ID = "BOUNDED_CONTINGENCY_20260216_CASE_V1"


def read_case_input(
    session: Session, artifact_id: str, version: int
) -> ContingencyCaseInputVersion:
    row = (
        session.execute(
            select(db.contingency_case_inputs).where(
                db.contingency_case_inputs.c.artifact_id == artifact_id,
                db.contingency_case_inputs.c.version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Contingency case not found")
    try:
        case = ContingencyCaseInputVersion.model_validate(dict(row))
    except ValidationError as error:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Contingency case invalid"
        ) from error
    policy = read_policy_version_by_id(session, case.policy_version_id)
    if (
        case.policy_version_id != policy.id
        or case.recorded_at < policy.recorded_at
        or case.payload.source_kind != policy.payload.source_kind
        or case.payload.as_of != policy.payload.issue_time
        or set(case.payload.ingredient_ids) != set(policy.payload.safety_stock)
        or case.payload.forecasts[-1].buckets[-1].end
        < max(policy.payload.assessment_end.values())
        or (
            policy.payload.approved_domain_id is not None
            and policy.payload.approved_domain_id != case.payload.domain_id
        )
        or (
            policy.payload.forecast_artifact_id is not None
            and policy.payload.forecast_artifact_id != case.id
        )
    ):
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Case and policy versions conflict"
        )
    return case


def first_case_seed_input(recorded_at: datetime) -> dict:
    """Exact first numerical fixture; it is not an activated operational forecast."""
    issue = "2026-02-16T10:00:00+08:00"
    day = "2026-02-16"
    next_day = "2026-02-17"
    ingredient_ids = [
        "chicken",
        "rice",
        "noodles",
        "eggs",
        "tofu",
        "vegetables",
        "oil",
        "soy-sauce",
    ]
    menu_item_ids = [
        "chicken-rice",
        "fried-rice",
        "chicken-noodles",
        "tofu-bowl",
        "vegetable-noodles",
    ]
    offer_id = "market-vegetables"
    opportunity_id = "rescue"
    source_revision = "ML_CONTINGENCY_CONTRACT_V1_DEMO_CASE"

    def forecast(target_date: str, tofu_first: str, tofu_second: str) -> dict:
        return {
            "target_date": target_date,
            "promotion_state": "EXCLUDED",
            "profile": [
                {
                    "start": f"{target_date}T11:00:00+08:00",
                    "end": f"{target_date}T11:30:00+08:00",
                    "weight": "0.7",
                },
                {
                    "start": f"{target_date}T11:30:00+08:00",
                    "end": f"{target_date}T12:00:00+08:00",
                    "weight": "0.3",
                },
            ],
            "buckets": [
                {
                    "start": f"{target_date}T11:00:00+08:00",
                    "end": f"{target_date}T11:30:00+08:00",
                    "expected_portions": {
                        key: tofu_first if key == "tofu-bowl" else "0"
                        for key in menu_item_ids
                    },
                },
                {
                    "start": f"{target_date}T11:30:00+08:00",
                    "end": f"{target_date}T12:00:00+08:00",
                    "expected_portions": {
                        key: tofu_second if key == "tofu-bowl" else "0"
                        for key in menu_item_ids
                    },
                },
            ],
        }

    artifact = ContingencyCaseInputVersion.model_validate(
        {
            "id": f"case-input:{FIRST_CASE_ID}:1",
            "policy_version_id": f"policy:{DEMO_POLICY_ID}:1",
            "artifact_id": FIRST_CASE_ID,
            "version": 1,
            "effective_at": issue,
            "recorded_at": recorded_at,
            "source_revision": source_revision,
            "payload": {
                "source_kind": "EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE",
                "as_of": issue,
                "domain_id": "BOUNDED_CONTINGENCY_20260216_DOMAIN_V1",
                "forecast_method": "EXPLICIT_RESIDUAL_DEMO_V1",
                "ingredient_ids": ingredient_ids,
                "menu_item_ids": menu_item_ids,
                "forecasts": [forecast(day, "70", "30"), forecast(next_day, "0", "0")],
                "opening_expected": {
                    **dict.fromkeys(ingredient_ids, "0"),
                    "rice": "20",
                    "tofu": "20",
                    "vegetables": "6",
                },
                "fixed_supply_expected": {
                    "supplier_id": "fresh",
                    "ingredient_id": "vegetables",
                    "kind": "NORMAL",
                    "ordered_at": "2026-02-15T10:00:00+08:00",
                    "expected_at": "2026-02-17T09:00:00+08:00",
                    "expected_quantity": "10",
                    "received_quantity": "6",
                    "cancelled_quantity": "0",
                    "outstanding_quantity": "4",
                    "received_expiry_date": "2026-02-20",
                },
                "approved_offer_manifest": [[offer_id, "market", "vegetables"]],
                "offers": [
                    {
                        "id": f"case-offer:{FIRST_CASE_ID}:{offer_id}:1",
                        "offer_id": offer_id,
                        "supplier_id": "market",
                        "ingredient_id": "vegetables",
                        "source_revision": f"{source_revision}:offer:{offer_id}:1",
                        "offer": {
                            "id": offer_id,
                            "supplier_id": "market",
                            "ingredient_id": "vegetables",
                            "currency": "SGD",
                            "unit_price": "2",
                            "available_quantity": "6",
                            "moq": "1",
                            "pack_size": "1",
                            "lead_time_minutes": 60,
                            "order_cutoff": {"kind": "NONE"},
                            "feasible_delivery_at": ["2026-02-16T11:00:00+08:00"],
                            "current_status": "AVAILABLE",
                            "recent_on_time_rate": "0.5",
                            "shelf_life_days_on_arrival": 2,
                            "delivery_fee_sgd": "3",
                            "emergency_fee_sgd": "4",
                            "observed_at": recorded_at,
                        },
                    }
                ],
                "opportunity_manifest": [opportunity_id],
                "opportunities": [
                    {
                        "id": f"case-opportunity:{FIRST_CASE_ID}:{opportunity_id}:1",
                        "opportunity_id": opportunity_id,
                        "offer_id": offer_id,
                        "ordered_at": issue,
                        "arrival_at": "2026-02-16T11:00:00+08:00",
                        "kind": "EMERGENCY",
                        "shipment_group_id": "new-rescue-shipment",
                        "expiry_date": "2026-02-17",
                        "source_revision": f"{source_revision}:opportunity:{opportunity_id}:1",
                    }
                ],
            },
        }
    )
    return artifact.model_dump(mode="json")


def first_case_seed_input_v2(
    recorded_at: datetime,
    *,
    menu_items: list[dict],
    ingredients: list[dict],
    recipes: list[dict],
    suppliers: list[dict],
) -> dict:
    """Freeze the exact seeded catalogue behind the same synthetic demand case."""
    row = first_case_seed_input(recorded_at)
    row["id"] = f"case-input:{FIRST_CASE_ID}:2"
    row["version"] = 2
    row["policy_version_id"] = f"policy:{DEMO_POLICY_ID}:2"
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V2_DEMO_CASE"
    menu = [MenuItem.model_validate(item) for item in menu_items]
    ingredient_rows = [Ingredient.model_validate(item) for item in ingredients]
    recipe_rows = [RecipeItem.model_validate(item) for item in recipes]
    supplier_rows = [Supplier.model_validate(item) for item in suppliers]
    row["payload"].update(
        catalogue_menu_items=[item.model_dump(mode="json") for item in menu],
        catalogue_ingredients=[
            item.model_dump(mode="json") for item in ingredient_rows
        ],
        catalogue_recipes=[item.model_dump(mode="json") for item in recipe_rows],
        catalogue_suppliers=[item.model_dump(mode="json") for item in supplier_rows],
        recipe_manifest=[
            [item.menu_item_id, item.ingredient_id] for item in recipe_rows
        ],
        catalogue_sha256=catalogue_sha256(
            menu, ingredient_rows, recipe_rows, supplier_rows
        ),
    )
    return ContingencyCaseInputVersion.model_validate(row).model_dump(mode="json")


def first_case_seed_input_v3(
    recorded_at: datetime,
    *,
    menu_items: list[dict],
    ingredients: list[dict],
    recipes: list[dict],
    suppliers: list[dict],
) -> dict:
    """Version the team's approval of the exact synthetic emergency quote."""
    row = first_case_seed_input_v2(
        recorded_at,
        menu_items=menu_items,
        ingredients=ingredients,
        recipes=recipes,
        suppliers=suppliers,
    )
    row["id"] = f"case-input:{FIRST_CASE_ID}:3"
    row["version"] = 3
    row["policy_version_id"] = f"policy:{DEMO_POLICY_ID}:3"
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V3_APPROVED_DEMO_QUOTE"
    payload = row["payload"]
    payload["offer_authority"] = "APPROVED_SYNTHETIC_DEMO_QUOTE"
    payload["offer_approval_reference"] = "DEMO_QUOTE_DECISION_2026_09_24"
    payload["approved_quote_sha256"] = approved_quote_sha256(
        [FrozenOfferRevision.model_validate(offer) for offer in payload["offers"]],
        [
            FrozenOrderingOpportunity.model_validate(opportunity)
            for opportunity in payload["opportunities"]
        ],
    )
    return ContingencyCaseInputVersion.model_validate(row).model_dump(mode="json")


def first_case_seed_input_v4(
    recorded_at: datetime,
    *,
    menu_items: list[dict],
    ingredients: list[dict],
    recipes: list[dict],
    suppliers: list[dict],
) -> dict:
    """Bind the unchanged approved quote to the active first-case policy."""
    row = first_case_seed_input_v3(
        recorded_at,
        menu_items=menu_items,
        ingredients=ingredients,
        recipes=recipes,
        suppliers=suppliers,
    )
    row["id"] = f"case-input:{FIRST_CASE_ID}:4"
    row["version"] = 4
    row["policy_version_id"] = f"policy:{DEMO_POLICY_ID}:4"
    row["source_revision"] = "ML_CONTINGENCY_CONTRACT_V4_ACTIVE_FIRST_CASE"
    return ContingencyCaseInputVersion.model_validate(row).model_dump(mode="json")


def post_purchase_seed_input(
    recorded_at: datetime, *, version: int, **catalogue
) -> dict:
    """Two explicitly bounded checkpoints; v4 authority is never broadened."""
    if version not in (5, 6):
        raise ValueError("Unsupported post-purchase version")
    row = first_case_seed_input_v4(recorded_at, **catalogue)
    row["id"] = f"case-input:{FIRST_CASE_ID}:{version}"
    row["version"] = version
    row["policy_version_id"] = f"policy:{DEMO_POLICY_ID}:{version}"
    row["source_revision"] = f"POST_PURCHASE_FIXED_SUPPLY_V1:{version}"
    payload = row["payload"]
    payload["domain_id"] = f"POST_PURCHASE_20260216_DOMAIN_V{version}"
    payload["offer_approval_reference"] = "ANIQ_POST_PURCHASE_BOUNDED_DEMO_2026_09_25"
    if version == 6:
        row["effective_at"] = payload["as_of"] = "2026-02-16T11:00:00+08:00"
        # Explicit exhausted domain: the only quote arrived at 11:00 with a
        # 60-minute lead. No NEW order remains available at this checkpoint.
        payload["opportunity_manifest"] = []
        payload["opportunities"] = []
    payload["approved_quote_sha256"] = approved_quote_sha256(
        [FrozenOfferRevision.model_validate(x) for x in payload["offers"]],
        [FrozenOrderingOpportunity.model_validate(x) for x in payload["opportunities"]],
    )
    return ContingencyCaseInputVersion.model_validate(row).model_dump(mode="json")

"""Read-only canonical procurement-policy and approved-domain authority."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.procurement_contract_schemas import ProcurementContract

FIRST_SLICE_POLICY_ID = "CASH_SLICE_V1"


def _row_or_missing(row: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    if row is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", f"Missing required {name}")
    return dict(row)


def _policy_at(session: Session, as_of: datetime, known_at: datetime) -> dict | None:
    row = (
        session.execute(
            select(db.procurement_policy_versions)
            .where(
                db.procurement_policy_versions.c.policy_id == FIRST_SLICE_POLICY_ID,
                db.procurement_policy_versions.c.effective_at <= as_of,
                db.procurement_policy_versions.c.recorded_at <= known_at,
            )
            .order_by(
                db.procurement_policy_versions.c.effective_at.desc(),
                db.procurement_policy_versions.c.version.desc(),
                db.procurement_policy_versions.c.recorded_at.desc(),
            )
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _domain(session: Session, policy: dict) -> dict:
    row = (
        session.execute(
            select(db.procurement_policy_domains).where(
                db.procurement_policy_domains.c.policy_version_id == policy["id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    return _row_or_missing(
        dict(row) if row is not None else None,
        "approved procurement domain",
    )


def _build(
    policy: dict, domain: dict, offers: list[dict], opportunities: list[dict]
) -> ProcurementContract:
    payload = policy["payload"]
    if domain["domain_id"] != payload["approved_domain_id"]:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Policy domain identity does not match"
        )
    if len(offers) != payload["expected_offer_count"]:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Approved offer domain is incomplete"
        )
    if len(opportunities) != payload["expected_opportunity_count"]:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Approved opportunity domain is incomplete"
        )
    supplier_ids = set(payload["approved_supplier_ids"])
    ingredient_ids = set(payload["storage_limits"])
    offer_keys = {(row["supplier_id"], row["ingredient_id"]) for row in offers}
    if offer_keys != {
        (supplier, ingredient)
        for supplier in supplier_ids
        for ingredient in ingredient_ids
    }:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Approved offer manifest is incomplete"
        )
    if any(
        row["offer_id"] not in {offer["offer_id"] for offer in offers}
        or row["kind"] != "NORMAL"
        for row in opportunities
    ):
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Approved opportunity domain is invalid"
        )
    by_offer = {row["offer_id"] for row in offers}
    if {row["offer_id"] for row in opportunities} != by_offer:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Every approved offer needs one opportunity"
        )
    return ProcurementContract.model_validate(
        {
            "as_of": policy["effective_at"],
            "known_at": policy["recorded_at"],
            "captured_state_revision": domain["source_revision"],
            "policy": {**policy, "payload": payload},
            "domain": {
                key: domain[key]
                for key in (
                    "id",
                    "domain_id",
                    "version",
                    "source_revision",
                    "recorded_at",
                    "payload",
                )
            }
            | {
                "offers": [
                    {
                        **{
                            key: offer[key]
                            for key in (
                                "id",
                                "offer_id",
                                "supplier_id",
                                "ingredient_id",
                                "source_revision",
                            )
                        },
                        "offer": offer["payload"],
                    }
                    for offer in offers
                ],
                "opportunities": [
                    {
                        key: opportunity[key]
                        for key in (
                            "id",
                            "opportunity_id",
                            "offer_id",
                            "ordered_at",
                            "arrival_at",
                            "kind",
                            "expiry_date",
                            "source_revision",
                        )
                    }
                    for opportunity in opportunities
                ],
            },
        }
    )


def read_policy_contract(
    session: Session, policy_id: str, version: int
) -> ProcurementContract:
    row = (
        session.execute(
            select(db.procurement_policy_versions).where(
                db.procurement_policy_versions.c.policy_id == policy_id,
                db.procurement_policy_versions.c.version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    policy = _row_or_missing(
        dict(row) if row is not None else None,
        "procurement policy version",
    )
    domain = _domain(session, policy)
    offers = [
        dict(row)
        for row in session.execute(
            select(db.procurement_domain_offer_revisions)
            .where(
                db.procurement_domain_offer_revisions.c.domain_version_id
                == domain["id"]
            )
            .order_by(db.procurement_domain_offer_revisions.c.offer_id)
        ).mappings()
    ]
    opportunities = [
        dict(row)
        for row in session.execute(
            select(db.procurement_domain_opportunities)
            .where(
                db.procurement_domain_opportunities.c.domain_version_id == domain["id"]
            )
            .order_by(db.procurement_domain_opportunities.c.opportunity_id)
        ).mappings()
    ]
    return _build(policy, domain, offers, opportunities)


def freeze_first_slice_contract(
    session: Session, as_of: datetime, known_at: datetime, captured_state_revision: int
) -> dict | None:
    """Return an immutable selected contract only for its declared issue instant."""
    policy = _policy_at(session, as_of, known_at)
    if policy is None:
        return None
    payload = policy["payload"]
    if as_of != datetime.fromisoformat(payload["issue_time"]):
        return None
    contract = read_policy_contract(session, policy["policy_id"], policy["version"])
    return contract.model_copy(
        update={
            "as_of": as_of,
            "known_at": known_at,
            "captured_state_revision": str(captured_state_revision),
        }
    ).model_dump(mode="json")


def first_slice_seed_rows(recorded_at: datetime) -> dict[str, list[dict]]:
    """The approved synthetic integration fixture; separate from live offer facts."""
    issue_time = datetime.fromisoformat("2026-02-15T22:00:00+08:00")
    arrival_at = datetime.fromisoformat("2026-02-16T08:00:00+08:00")
    policy_id = FIRST_SLICE_POLICY_ID
    policy_version_id = "policy:CASH_SLICE_V1:1"
    domain_version_id = "domain:CASH_SLICE_20260216_DOMAIN_V1:1"
    domain_id = "CASH_SLICE_20260216_DOMAIN_V1"
    source_revision = "CASH_SLICE_20260216_SOURCE_V1"
    ingredients = [
        "chicken",
        "rice",
        "noodles",
        "eggs",
        "tofu",
        "vegetables",
        "oil",
        "soy-sauce",
    ]
    prices = {
        ingredient: Decimal("4.50") + index
        for index, ingredient in enumerate(ingredients)
    }
    policy = {
        "id": policy_version_id,
        "policy_id": policy_id,
        "version": 1,
        "effective_at": issue_time,
        "recorded_at": recorded_at,
        "payload": {
            "objective_policy": "CASH_SLICE_V1",
            "currency": "SGD",
            "new_order_budget_sgd": "100.000",
            "target_date": "2026-02-16",
            "issue_time": issue_time.isoformat(),
            "horizon_end": "2026-02-16T21:00:00+08:00",
            "timezone": "Asia/Singapore",
            "bucket_minutes": 30,
            "service_profile": [
                {
                    "start": "2026-02-16T11:00:00+08:00",
                    "end": "2026-02-16T14:00:00+08:00",
                    "weight": "0.4",
                },
                {
                    "start": "2026-02-16T17:00:00+08:00",
                    "end": "2026-02-16T21:00:00+08:00",
                    "weight": "0.6",
                },
            ],
            "safety_stock": {ingredient: "0.000" for ingredient in ingredients},
            "storage_limits": {
                "chicken": "30.000",
                "rice": "40.000",
                "noodles": "30.000",
                "eggs": "150.000",
                "tofu": "20.000",
                "vegetables": "30.000",
                "oil": "15.000",
                "soy-sauce": "15.000",
            },
            "fee_policy": "SUPPLIER_ARRIVAL_ONCE_V1",
            "fee_grouping": "SUPPLIER_ID_AND_ARRIVAL_AT",
            "emergency_mode": "NORMAL_ONLY",
            "reliability_mode": "CONTEXT_ONLY",
            "fefo_policy": "FEFO_EXPIRY_RECEIVED_LOT_ID_V1",
            "new_supply_expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
            "tie_break_policy": "SUPPLIER_ID_THEN_INGREDIENT_ID_V1",
            "search_policy": "COMPLETE_PRUNED_DOMAIN_V1",
            "approved_domain_id": domain_id,
            "approved_supplier_ids": ["fresh", "pantry", "market"],
            "expected_offer_count": 24,
            "expected_opportunity_count": 24,
            "explicit_empty_post_count_activity": True,
            "explicit_empty_outstanding_commitments": True,
        },
    }
    domain = {
        "id": domain_version_id,
        "policy_version_id": policy_version_id,
        "domain_id": domain_id,
        "version": 1,
        "source_revision": source_revision,
        "recorded_at": recorded_at,
        "payload": {
            "source_kind": "FIRST_SLICE_SYNTHETIC_FIXTURE",
            "source_description": "Approved Pass 3E one-day 24-offer normal-order domain.",
            "opening_lot_ids": [
                *(f"{ingredient}-01" for ingredient in ingredients),
                "chicken-02",
            ],
        },
    }
    offers = []
    opportunities = []
    for supplier in ("fresh", "pantry", "market"):
        for ingredient in ingredients:
            offer_id = f"{supplier}-{ingredient}"
            offer_revision = f"{source_revision}:offer:{offer_id}:1"
            offers.append(
                {
                    "id": f"domain-offer:{domain_id}:{offer_id}:1",
                    "domain_version_id": domain_version_id,
                    "offer_id": offer_id,
                    "supplier_id": supplier,
                    "ingredient_id": ingredient,
                    "source_revision": offer_revision,
                    "payload": {
                        "id": offer_id,
                        "supplier_id": supplier,
                        "ingredient_id": ingredient,
                        "currency": "SGD",
                        "unit_price": str(prices[ingredient]),
                        "available_quantity": "200.000",
                        "moq": "1.000",
                        "pack_size": "1.000",
                        "lead_time_minutes": 480,
                        "order_cutoff": {
                            "kind": "LOCAL_TIME",
                            "local_time": "23:00:00",
                            "timezone": "Asia/Singapore",
                        },
                        "feasible_delivery_at": [arrival_at.isoformat()],
                        "current_status": "AVAILABLE",
                        "recent_on_time_rate": "0.9500",
                        "shelf_life_days_on_arrival": 5,
                        "delivery_fee_sgd": "5.00",
                        "emergency_fee_sgd": "12.00",
                        "observed_at": issue_time.isoformat(),
                    },
                }
            )
            opportunities.append(
                {
                    "id": f"domain-opportunity:{domain_id}:{offer_id}:normal:1",
                    "domain_version_id": domain_version_id,
                    "opportunity_id": f"{offer_id}:normal:20260215T2200+0800",
                    "offer_id": offer_id,
                    "ordered_at": issue_time,
                    "arrival_at": arrival_at,
                    "kind": "NORMAL",
                    "expiry_date": date(2026, 2, 20),
                    "source_revision": f"{source_revision}:opportunity:{offer_id}:normal:1",
                }
            )
    return {
        "policies": [policy],
        "domains": [domain],
        "offers": offers,
        "opportunities": opportunities,
    }

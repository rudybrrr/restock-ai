"""Read-only canonical procurement-policy and approved-domain authority."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

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
    policy: dict,
    domain: dict,
    forecast_input: dict,
    offers: list[dict],
    opportunities: list[dict],
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
    forecast_payload = forecast_input["payload"]
    if forecast_input["policy_version_id"] != policy["id"]:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Forecast input policy identity does not match",
        )
    menu_item_ids = forecast_payload["menu_item_ids"]
    history = forecast_payload["history"]
    target_date = date.fromisoformat(str(forecast_payload["target_date"]))
    if (
        forecast_payload["target_date"] != payload["target_date"]
        or forecast_input["effective_at"] != policy["effective_at"]
        or len(history) != 4
        or len(menu_item_ids) != len(set(menu_item_ids))
        or len({str(row["service_date"]) for row in history}) != len(history)
        or any(set(row["portions"]) != set(menu_item_ids) for row in history)
        or any(
            date.fromisoformat(str(row["service_date"])) >= target_date
            for row in history
        )
        or any(
            datetime.fromisoformat(str(row["available_at"]))
            > datetime.fromisoformat(str(payload["issue_time"]))
            for row in history
        )
    ):
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Forecast input artifact is incomplete"
        )
    return ProcurementContract.model_validate(
        {
            "as_of": policy["effective_at"],
            "known_at": max(
                policy["recorded_at"],
                domain["recorded_at"],
                forecast_input["recorded_at"],
            ),
            "captured_state_revision": domain["source_revision"],
            "policy": {**policy, "payload": payload},
            "forecast_input": forecast_input,
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
    forecast_input_row = (
        session.execute(
            select(db.procurement_forecast_inputs).where(
                db.procurement_forecast_inputs.c.policy_version_id == policy["id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    forecast_input = _row_or_missing(
        dict(forecast_input_row) if forecast_input_row is not None else None,
        "forecast input artifact",
    )
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
    return _build(policy, domain, forecast_input, offers, opportunities)


def freeze_first_slice_contract(
    session: Session, as_of: datetime, known_at: datetime, captured_state_revision: int
) -> dict | None:
    """Select the immutable first-slice policy for an in-horizon operational run."""
    policy = _policy_at(session, as_of, known_at)
    if policy is None:
        return None
    payload = policy["payload"]
    if not (
        datetime.fromisoformat(payload["issue_time"])
        <= as_of
        <= datetime.fromisoformat(payload["horizon_end"])
    ):
        return None
    contract = read_policy_contract(session, policy["policy_id"], policy["version"])
    if (
        contract.forecast_input.effective_at > as_of
        or contract.forecast_input.recorded_at > known_at
    ):
        return None
    return contract.model_copy(
        update={
            "as_of": as_of,
            "known_at": known_at,
            "captured_state_revision": str(captured_state_revision),
        }
    ).model_dump(mode="json")


def bind_frozen_supplier_state(
    contract: dict, offers: list[dict], offer_version_ids: list[str]
) -> dict:
    """Freeze authoritative current supplier revisions inside the approved domain.

    The policy still authorizes the exact offer identities and ordering
    opportunities.  This only substitutes the already-versioned operational offer
    facts captured in the claimed run, so a supplier disruption is visible to the
    deterministic engine without creating a new policy or domain contract.
    """
    if len(offers) != len(offer_version_ids):
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Supplier revision evidence is incomplete")
    by_id = {str(offer["id"]): offer for offer in offers}
    revision_by_id = {
        str(offer["id"]): version_id
        for offer, version_id in zip(offers, offer_version_ids, strict=True)
    }
    domain = dict(contract["domain"])
    domain_offers = []
    for domain_offer in domain["offers"]:
        offer_id = str(domain_offer["offer_id"])
        offer = by_id.get(offer_id)
        revision = revision_by_id.get(offer_id)
        if offer is None or revision is None:
            raise ApiError(
                409,
                "MISSING_REQUIRED_DATA",
                "Approved supplier domain is missing a frozen offer revision",
            )
        # Availability/status are the only authoritative operational fields wired
        # for Pass 3F.  Preserve the approved domain's frozen commercial terms and
        # opportunities rather than silently importing a broader live offer shape.
        bound_offer = {
            **domain_offer["offer"],
            "available_quantity": offer["available_quantity"],
            "current_status": offer["current_status"],
        }
        domain_offers.append(
            {
                **domain_offer,
                "source_revision": revision,
                "offer": bound_offer,
            }
        )
    domain["offers"] = domain_offers
    return ProcurementContract.model_validate(
        {**contract, "domain": domain}
    ).model_dump(mode="json")


def freeze_operational_activity(contract: dict, frozen_state: dict) -> dict:
    """Attach activity and adapter-ready fixed commitments to one run contract."""
    selected = ProcurementContract.model_validate(contract)
    offer_by_key = {
        (row.supplier_id, row.ingredient_id): row for row in selected.domain.offers
    }
    findings = []
    supplies = []
    manifest = []
    for raw in frozen_state["commitments"]:
        delivery_id = raw["id"]
        manifest.append(delivery_id)
        outstanding = Decimal(str(raw["outstanding_quantity"]))
        expiry_date = None
        expiry_evidence = None
        projected_lot_id = None
        if outstanding:
            projected_lot_id = f"projected-delivery:{delivery_id}"
            offer = offer_by_key.get((raw["supplier_id"], raw["ingredient_id"]))
            if offer is None:
                findings.append(
                    {"code": "MISSING_APPROVED_OFFER", "source": delivery_id}
                )
            elif offer.offer.shelf_life_days_on_arrival is None:
                findings.append(
                    {"code": "MISSING_EXPECTED_EXPIRY", "source": delivery_id}
                )
            else:
                arrival_day = raw["expected_at"]
                if isinstance(arrival_day, str):
                    arrival_day = datetime.fromisoformat(arrival_day)
                expiry_date = arrival_day.astimezone(
                    ZoneInfo(selected.policy.payload.timezone)
                ).date() + timedelta(days=offer.offer.shelf_life_days_on_arrival - 1)
                expiry_evidence = {
                    "reference": (f"{offer.offer_id}:shelf_life_days_on_arrival"),
                    "available_at": selected.domain.recorded_at,
                    "captured_revision": offer.source_revision,
                }
        supplies.append(
            {
                "delivery": raw,
                "expiry_date": expiry_date,
                "expiry_evidence": expiry_evidence,
                "projected_lot_id": projected_lot_id,
            }
        )
    projection = {
        "as_of": selected.as_of,
        "known_at": selected.known_at,
        "captured_state_revision": selected.captured_state_revision,
        "expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
        "complete": not findings,
        "findings": findings,
        "supply_manifest": manifest,
        "supplies": supplies,
    }
    return ProcurementContract.model_validate(
        {
            **selected.model_dump(mode="python"),
            "frozen_state": frozen_state,
            "commitment_projection": projection,
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
    forecast_input_id = "forecast-input:CASH_SLICE_20260216_HISTORY_V1:1"
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
    portions = {
        "chicken-rice": 100,
        "fried-rice": 60,
        "chicken-noodles": 80,
        "tofu-bowl": 40,
        "vegetable-noodles": 40,
    }
    forecast_input = {
        "id": forecast_input_id,
        "policy_version_id": policy_version_id,
        "artifact_id": "CASH_SLICE_20260216_HISTORY_V1",
        "version": 1,
        "effective_at": issue_time,
        "recorded_at": recorded_at,
        "source_revision": "CASH_SLICE_20260216_DEMAND_HISTORY_SOURCE_V1",
        "payload": {
            "source_kind": "FIRST_SLICE_SYNTHETIC_HISTORY",
            "forecast_method": "SEASONAL_BASELINE_V1",
            "target_date": "2026-02-16",
            "menu_item_ids": list(portions),
            "history": [
                {
                    "service_date": day,
                    "available_at": f"{day}T22:00:00+08:00",
                    "revision": 1,
                    "promotion": False,
                    "censored": False,
                    "portions": portions,
                }
                for day in ("2026-01-19", "2026-01-26", "2026-02-02", "2026-02-09")
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
        "forecast_inputs": [forecast_input],
        "offers": offers,
        "opportunities": opportunities,
    }

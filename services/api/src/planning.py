"""Short transactions around frozen agent runs and deterministic candidate validation."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.operations import record_event
from src.planning_schemas import (
    Candidate,
    Completion,
    OptimiseRequest,
    PlanLine,
    PlanningRun,
    PurchasePlanVersion,
)
from src.sales import estimated_inventory


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def _revision(session: Session) -> int:
    return session.execute(select(func.count()).select_from(db.events)).scalar_one()


def _snapshot(session: Session, as_of: datetime, run_id: str) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "forecast_id": f"{run_id}:forecast",
        "inventory_snapshot_id": f"{run_id}:inventory",
        "inventory": [_json(row) for row in estimated_inventory(session, as_of)],
        "recipes": [
            _json(dict(row)) for row in session.execute(select(db.recipes)).mappings()
        ],
        "offers": [
            _json(dict(row))
            for row in session.execute(select(db.supplier_offers)).mappings()
        ],
    }


def request_run(session: Session, as_of: datetime) -> PlanningRun:
    existing = (
        session.execute(
            select(db.planning_runs).where(
                db.planning_runs.c.status.in_(("QUEUED", "RUNNING"))
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        return PlanningRun.model_validate(existing)
    run_id = str(uuid4())
    row = {
        "id": run_id,
        "status": "QUEUED",
        "trigger": "MANUAL_REASSESSMENT_REQUESTED",
        "as_of": as_of,
        "input_revision": _revision(session),
        "snapshot": {},
        "created_at": datetime.now(UTC),
    }
    session.execute(insert(db.planning_runs).values(**row))
    record_event(
        session,
        "MANUAL_REASSESSMENT_REQUESTED",
        "manager",
        {"run_id": run_id, "effective_at": as_of.isoformat()},
    )
    session.commit()
    return PlanningRun.model_validate(row)


def get_run(session: Session, run_id: str) -> PlanningRun:
    row = (
        session.execute(select(db.planning_runs).where(db.planning_runs.c.id == run_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(404, "RUN_NOT_FOUND", "Assessment run does not exist")
    return PlanningRun.model_validate(row)


def claim_run(session: Session) -> PlanningRun:
    row = (
        session.execute(
            select(db.planning_runs)
            .where(db.planning_runs.c.status == "QUEUED")
            .with_for_update(skip_locked=True)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(409, "NO_QUEUED_RUN", "There is no queued assessment")
    now = datetime.now(UTC)
    snapshot = _snapshot(session, row["as_of"], row["id"])
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == row["id"])
        .values(
            status="RUNNING",
            claimed_at=now,
            deadline_at=now + timedelta(minutes=10),
            input_revision=_revision(session),
            snapshot=snapshot,
        )
    )
    session.commit()
    return get_run(session, row["id"])


def optimise(session: Session, run_id: str, body: OptimiseRequest) -> Candidate:
    run = get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(
            409, "RUN_NOT_CLAIMED", "Claim the assessment before using its tools"
        )
    snapshot = run.snapshot
    quantities: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for recipe in snapshot["recipes"]:
        quantities[recipe["ingredient_id"]] += Decimal(
            str(body.dish_quantities.get(recipe["menu_item_id"], 0))
        ) * Decimal(str(recipe["quantity"]))
    inventory: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for lot in snapshot["inventory"]:
        if lot["status"] == "ACTIVE":
            inventory[lot["ingredient_id"]] += Decimal(str(lot["quantity"]))
    lines = []
    delivery_cost = Decimal(0)
    for ingredient, required in quantities.items():
        shortage = required - inventory[ingredient]
        if shortage <= 0:
            continue
        offers = [
            offer
            for offer in snapshot["offers"]
            if offer["ingredient_id"] == ingredient
            and offer["current_status"] == "AVAILABLE"
        ]
        offers = [
            offer
            for offer in offers
            if all(
                offer[field] is not None
                for field in (
                    "unit_price",
                    "available_quantity",
                    "moq",
                    "pack_size",
                    "lead_time_minutes",
                    "feasible_delivery_at",
                    "delivery_fee_sgd",
                )
            )
            and offer["feasible_delivery_at"]
        ]
        as_of = datetime.fromisoformat(snapshot["as_of"])
        offers = [
            offer
            for offer in offers
            if any(
                datetime.fromisoformat(slot)
                >= as_of + timedelta(minutes=offer["lead_time_minutes"])
                for slot in offer["feasible_delivery_at"]
            )
        ]
        if not offers:
            raise ApiError(
                409,
                "NO_FEASIBLE_SUPPLIER",
                f"No complete feasible offer for {ingredient}",
            )
        offer = min(offers, key=lambda item: Decimal(str(item["unit_price"])))
        pack = Decimal(str(offer["pack_size"]))
        quantity = max(shortage, Decimal(str(offer["moq"])))
        quantity = (quantity / pack).to_integral_value(rounding=ROUND_UP) * pack
        if quantity > Decimal(str(offer["available_quantity"])):
            raise ApiError(
                409,
                "NO_FEASIBLE_SUPPLIER",
                f"Available {ingredient} cannot cover the shortage",
            )
        lines.append(
            {
                "ingredient_id": ingredient,
                "supplier_id": offer["supplier_id"],
                "quantity": quantity,
                "unit_price": Decimal(str(offer["unit_price"])),
                "arrival_at": min(
                    datetime.fromisoformat(slot)
                    for slot in offer["feasible_delivery_at"]
                    if datetime.fromisoformat(slot)
                    >= as_of + timedelta(minutes=offer["lead_time_minutes"])
                ),
            }
        )
        delivery_cost += Decimal(str(offer["delivery_fee_sgd"]))
    purchase = sum(
        (line["quantity"] * line["unit_price"] for line in lines), Decimal(0)
    )
    return Candidate(
        forecast_id=snapshot["forecast_id"],
        inventory_snapshot_id=snapshot["inventory_snapshot_id"],
        lines=[PlanLine.model_validate(line) for line in lines],
        total_purchase_cost=purchase,
        delivery_cost=delivery_cost,
        total_expected_cost=purchase + delivery_cost,
    )


def _validate_candidate(snapshot: dict, candidate: Candidate) -> None:
    """Reject raw candidate writes that diverge from frozen supplier constraints."""
    allocations: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    as_of = datetime.fromisoformat(snapshot["as_of"])
    purchase_cost = Decimal(0)
    delivery_cost = Decimal(0)
    for line in candidate.lines:
        offer = next(
            (
                item
                for item in snapshot["offers"]
                if item["supplier_id"] == line.supplier_id
                and item["ingredient_id"] == line.ingredient_id
            ),
            None,
        )
        if offer is None or offer["current_status"] != "AVAILABLE":
            raise ApiError(
                409, "PLAN_INVALID", "Plan line has no available approved offer"
            )
        required = (
            "unit_price",
            "available_quantity",
            "moq",
            "pack_size",
            "lead_time_minutes",
            "feasible_delivery_at",
            "delivery_fee_sgd",
        )
        if any(offer[field] is None for field in required):
            raise ApiError(
                409, "PLAN_INVALID", "Plan line depends on unknown supplier data"
            )
        if line.unit_price != Decimal(str(offer["unit_price"])):
            raise ApiError(
                409, "PLAN_INVALID", "Plan line price differs from frozen offer"
            )
        pack = Decimal(str(offer["pack_size"]))
        if line.quantity < Decimal(str(offer["moq"])) or line.quantity % pack != 0:
            raise ApiError(409, "PLAN_INVALID", "Plan line violates MOQ or pack size")
        offer_id = offer["id"]
        allocations[offer_id] += line.quantity
        if allocations[offer_id] > Decimal(str(offer["available_quantity"])):
            raise ApiError(
                409, "PLAN_INVALID", "Plan allocation exceeds supplier availability"
            )
        slots = {datetime.fromisoformat(slot) for slot in offer["feasible_delivery_at"]}
        if line.arrival_at not in slots or line.arrival_at < as_of + timedelta(
            minutes=offer["lead_time_minutes"]
        ):
            raise ApiError(
                409, "PLAN_INVALID", "Plan arrival violates frozen delivery feasibility"
            )
        purchase_cost += line.quantity * line.unit_price
        delivery_cost += Decimal(str(offer["delivery_fee_sgd"]))
    if (
        candidate.total_purchase_cost != purchase_cost
        or candidate.delivery_cost != delivery_cost
        or candidate.total_expected_cost != purchase_cost + delivery_cost
    ):
        raise ApiError(
            409, "PLAN_INVALID", "Plan costs do not match its frozen supplier inputs"
        )


def complete_run(session: Session, run_id: str, body: Completion) -> PlanningRun:
    run = get_run(session, run_id)
    if run.status == "SUCCEEDED":
        return run
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Only a claimed assessment can complete")
    if run.deadline_at is not None and run.deadline_at < datetime.now(UTC):
        session.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run_id)
            .values(status="FAILED", completed_at=datetime.now(UTC))
        )
        session.commit()
        raise ApiError(
            409, "RUN_EXPIRED", "Assessment deadline elapsed before completion"
        )
    if _revision(session) != run.input_revision:
        raise ApiError(
            409,
            "STALE_RUN_INPUT",
            "Newer operational input requires a new assessment before publication",
        )
    if (body.outcome == "ESCALATE") != (body.escalation_reason is not None):
        raise ApiError(422, "INVALID_OUTCOME", "Only ESCALATE has an escalation reason")
    if (body.outcome == "REVISE_PLAN") != (body.candidate is not None):
        raise ApiError(
            422, "INVALID_OUTCOME", "REVISE_PLAN requires exactly one candidate"
        )
    version_id = None
    if body.candidate:
        candidate = body.candidate
        snapshot = run.snapshot
        if (
            candidate.forecast_id != snapshot["forecast_id"]
            or candidate.inventory_snapshot_id != snapshot["inventory_snapshot_id"]
            or not candidate.lines
        ):
            raise ApiError(
                409,
                "PLAN_INVALID",
                "Candidate must reference this run's frozen artifacts and have lines",
            )
        _validate_candidate(snapshot, candidate)
        plan_id, version_id = str(uuid4()), str(uuid4())
        now = datetime.now(UTC)
        session.execute(insert(db.purchase_plans).values(id=plan_id, created_at=now))
        session.execute(
            insert(db.plan_versions).values(
                id=version_id,
                plan_id=plan_id,
                version=1,
                run_id=run_id,
                status="PENDING_APPROVAL",
                snapshot=snapshot,
                costs=candidate.model_dump(
                    mode="json",
                    exclude={"lines", "forecast_id", "inventory_snapshot_id"},
                ),
                created_at=now,
            )
        )
        session.execute(
            insert(db.purchase_plan_lines).values(
                [
                    {
                        "id": str(uuid4()),
                        "plan_version_id": version_id,
                        **line.model_dump(),
                    }
                    for line in candidate.lines
                ]
            )
        )
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(
            status="SUCCEEDED",
            outcome=body.outcome,
            plan_version_id=version_id,
            completed_at=datetime.now(UTC),
        )
    )
    session.commit()
    return get_run(session, run_id)


def read_plan(session: Session, version_id: str) -> PurchasePlanVersion:
    row = (
        session.execute(
            select(db.plan_versions).where(db.plan_versions.c.id == version_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "Purchase-plan version does not exist")
    lines = (
        session.execute(
            select(db.purchase_plan_lines).where(
                db.purchase_plan_lines.c.plan_version_id == version_id
            )
        )
        .mappings()
        .all()
    )
    costs = row["costs"]
    return PurchasePlanVersion(
        id=row["id"],
        plan_id=row["plan_id"],
        version=row["version"],
        status=row["status"],
        run_id=row["run_id"],
        created_at=row["created_at"],
        lines=[PlanLine.model_validate(line) for line in lines],
        forecast_id=row["snapshot"]["forecast_id"],
        inventory_snapshot_id=row["snapshot"]["inventory_snapshot_id"],
        **costs,
    )

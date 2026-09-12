"""Short transactions around frozen agent runs and deterministic candidate validation."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from src import database as db
from src.deliveries import read_delivery
from src.errors import ApiError
from src.operations import lock_inventory, record_event
from src.planning_schemas import (
    Candidate,
    Completion,
    OptimiseRequest,
    PlanDecision,
    PlanLine,
    PlanningRun,
    PurchasePlanVersion,
)
from src.reconciliation import authoritative_daily_sales
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
        "authoritative_daily_sales": authoritative_daily_sales(session, as_of),
        "forecast_id": f"{run_id}:forecast",
        "inventory_snapshot_id": f"{run_id}:inventory",
        "inventory": [_json(row) for row in estimated_inventory(session, as_of)],
        "commitments": [
            read_delivery(session, key).model_dump(mode="json")
            for key in session.execute(select(db.deliveries.c.id)).scalars()
        ],
        "ingredients": [
            _json(dict(row))
            for row in session.execute(select(db.ingredients)).mappings()
        ],
        "cycle_decisions": [
            _json(dict(row))
            for row in session.execute(select(db.order_cycles)).mappings()
        ],
        "holidays": [
            _json(dict(row)) for row in session.execute(select(db.holidays)).mappings()
        ],
        "promotions": [
            {"id": row["id"], **row["payload"]}
            for row in session.execute(select(db.promotions)).mappings()
        ],
        "daily_history": [
            _json(dict(row))
            for row in session.execute(
                select(db.daily_revisions).where(db.daily_revisions.c.cutoff <= as_of)
            ).mappings()
        ],
        "sales_batches": [
            _json(dict(row))
            for row in session.execute(
                select(db.sales_batches).where(
                    db.sales_batches.c.active == 1,
                    db.sales_batches.c.period_end <= as_of,
                )
            ).mappings()
        ],
        "recipes": [
            _json(dict(row)) for row in session.execute(select(db.recipes)).mappings()
        ],
        "offers": [
            _json(dict(row))
            for row in session.execute(select(db.supplier_offers)).mappings()
        ],
    }


def request_run(
    session: Session, as_of: datetime, revises_plan_id: str | None = None
) -> PlanningRun:
    lock_inventory(session)
    _expire_runs(session)
    if (
        revises_plan_id is not None
        and not session.execute(
            select(db.purchase_plans.c.id).where(
                db.purchase_plans.c.id == revises_plan_id
            )
        ).first()
    ):
        raise ApiError(404, "PLAN_NOT_FOUND", "The plan to revise does not exist")
    existing = (
        session.execute(
            select(db.planning_runs).where(db.planning_runs.c.status == "QUEUED")
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["snapshot"].get("revises_plan_id") != revises_plan_id:
            raise ApiError(
                409,
                "ASSESSMENT_TARGET_CONFLICT",
                "A queued request already targets a different planning horizon",
            )
        if existing["status"] == "QUEUED" and as_of > existing["as_of"]:
            session.execute(
                update(db.planning_runs)
                .where(db.planning_runs.c.id == existing["id"])
                .values(as_of=as_of)
            )
        session.commit()
        return get_run(session, existing["id"])
    running = (
        session.execute(
            select(db.planning_runs).where(db.planning_runs.c.status == "RUNNING")
        )
        .mappings()
        .one_or_none()
    )
    if (
        running
        and as_of <= running["as_of"]
        and _revision(session) == running["input_revision"]
        and running["snapshot"].get("revises_plan_id") == revises_plan_id
    ):
        session.commit()
        return PlanningRun.model_validate(running)
    run_id = str(uuid4())
    row = {
        "id": run_id,
        "status": "QUEUED",
        "trigger": "MANUAL_REASSESSMENT_REQUESTED",
        "as_of": as_of,
        "input_revision": _revision(session),
        "snapshot": {"revises_plan_id": revises_plan_id},
        "created_at": datetime.now(UTC),
    }
    session.execute(insert(db.planning_runs).values(**row))
    trigger_event_id = record_event(
        session,
        "MANUAL_REASSESSMENT_REQUESTED",
        "manager",
        {"run_id": run_id, "effective_at": as_of.isoformat()},
    )
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(trigger_event_id=trigger_event_id)
    )
    session.execute(
        insert(db.assessment_requests).values(
            event_id=trigger_event_id, run_id=run_id, effective_at=as_of
        )
    )
    row["trigger_event_id"] = trigger_event_id
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


def retry_run(session: Session, run_id: str, as_of: datetime) -> PlanningRun:
    lock_inventory(session)
    _expire_runs(session)
    previous = get_run(session, run_id)
    if previous.status not in ("FAILED", "SUCCEEDED"):
        raise ApiError(
            409, "RUN_NOT_FINISHED", "Only a completed or failed attempt can be retried"
        )
    target = previous.snapshot.get("revises_plan_id")
    if previous.plan_version_id:
        target = read_plan(session, previous.plan_version_id).plan_id
    return request_run(session, as_of, target)


def _expire_runs(session: Session) -> None:
    session.execute(
        update(db.planning_runs)
        .where(
            db.planning_runs.c.status == "RUNNING",
            db.planning_runs.c.deadline_at < datetime.now(UTC),
        )
        .values(
            status="FAILED",
            failure_reason="RUN_EXPIRED",
            completed_at=datetime.now(UTC),
        )
    )


def claim_run(session: Session) -> PlanningRun:
    lock_inventory(session)
    _expire_runs(session)
    if session.execute(
        select(db.planning_runs.c.id).where(db.planning_runs.c.status == "RUNNING")
    ).first():
        session.commit()
        raise ApiError(
            409, "RUN_IN_PROGRESS", "Only one agent attempt may run at a time"
        )
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
        session.commit()
        raise ApiError(409, "NO_QUEUED_RUN", "There is no queued assessment")
    now = datetime.now(UTC)
    snapshot = {**row["snapshot"], **_snapshot(session, row["as_of"], row["id"])}
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
    lock_inventory(session)
    run = get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(
            409, "RUN_NOT_CLAIMED", "Claim the assessment before using its tools"
        )
    snapshot = run.snapshot
    if any(
        not lot["coverage_complete"]
        for lot in snapshot["inventory"]
        if lot["status"] == "ACTIVE"
    ):
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Complete sales coverage or a current stocktake is required to certify inventory",
        )
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

        def allocation(item: dict, shortage: Decimal = shortage) -> Decimal:
            pack = Decimal(str(item["pack_size"]))
            return (max(shortage, Decimal(str(item["moq"]))) / pack).to_integral_value(
                rounding=ROUND_UP
            ) * pack

        offers = [
            item
            for item in offers
            if allocation(item) <= Decimal(str(item["available_quantity"]))
        ]
        if not offers:
            raise ApiError(
                409,
                "NO_FEASIBLE_SUPPLIER",
                f"Available {ingredient} cannot cover the shortage",
            )
        offer = min(
            offers,
            key=lambda item: (
                allocation(item) * Decimal(str(item["unit_price"]))
                + Decimal(str(item["delivery_fee_sgd"]))
            ),
        )
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
    candidate = Candidate(
        forecast_id=snapshot["forecast_id"],
        inventory_snapshot_id=snapshot["inventory_snapshot_id"],
        lines=[PlanLine.model_validate(line) for line in lines],
        total_purchase_cost=purchase,
        delivery_cost=delivery_cost,
        total_expected_cost=purchase + delivery_cost,
    )
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(
            snapshot={
                **snapshot,
                "forecast": body.model_dump(mode="json"),
                "calculated_candidate": candidate.model_dump(mode="json"),
            }
        )
    )
    session.commit()
    return candidate


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
    lock_inventory(session)
    run = get_run(session, run_id)
    if run.status == "SUCCEEDED":
        if run.snapshot.get("completion") != body.model_dump(mode="json"):
            raise ApiError(
                409,
                "COMPLETION_CONFLICT",
                "Run already completed with a different result",
            )
        return run
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Only a claimed assessment can complete")
    if run.deadline_at is not None and run.deadline_at < datetime.now(UTC):
        session.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run_id)
            .values(
                status="FAILED",
                failure_reason="RUN_EXPIRED",
                completed_at=datetime.now(UTC),
            )
        )
        session.commit()
        raise ApiError(
            409, "RUN_EXPIRED", "Assessment deadline elapsed before completion"
        )
    if _revision(session) != run.input_revision:
        session.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run_id)
            .values(
                status="FAILED",
                failure_reason="STALE_RUN_INPUT",
                completed_at=datetime.now(UTC),
            )
        )
        session.commit()
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
    if body.outcome in ("KEEP_CURRENT_PLAN", "REQUEST_HUMAN_APPROVAL"):
        calculated = run.snapshot.get("calculated_candidate")
        if calculated is None:
            raise ApiError(
                409,
                "UNCERTIFIED_OUTCOME",
                "Run the deterministic tools before certifying a plan or no-purchase result",
            )
        target = run.snapshot.get("revises_plan_id")
        current = (
            session.execute(
                select(db.plan_versions)
                .where(
                    db.plan_versions.c.plan_id == target,
                    db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED")),
                )
                .order_by(db.plan_versions.c.version.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if current is None:
            if body.outcome != "KEEP_CURRENT_PLAN" or calculated["lines"]:
                raise ApiError(
                    409,
                    "NO_CURRENT_PLAN",
                    "There is no current plan matching this decision",
                )
        else:
            stored = read_plan(session, current["id"])
            comparable = set(Candidate.model_fields) - {
                "forecast_id",
                "inventory_snapshot_id",
            }
            if Candidate.model_validate(calculated).model_dump(
                include=comparable
            ) != stored.model_dump(include=comparable):
                raise ApiError(
                    409,
                    "PLAN_CHANGED",
                    "Calculated purchases changed; publish a new pending version",
                )
            if (
                body.outcome == "REQUEST_HUMAN_APPROVAL"
                and current["status"] != "PENDING_APPROVAL"
            ):
                raise ApiError(
                    409, "PLAN_NOT_PENDING", "Only a pending plan can request approval"
                )
            version_id = current["id"]
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
        if snapshot.get("calculated_candidate") != candidate.model_dump(mode="json"):
            raise ApiError(
                409,
                "PLAN_INVALID",
                "Candidate must match this run's deterministic tool result",
            )
        previous = (
            session.execute(
                select(db.plan_versions)
                .where(db.plan_versions.c.plan_id == snapshot.get("revises_plan_id"))
                .order_by(db.plan_versions.c.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        plan_id = previous["plan_id"] if previous else str(uuid4())
        version_number = previous["version"] + 1 if previous else 1
        version_id = str(uuid4())
        now = datetime.now(UTC)
        if previous is None:
            session.execute(
                insert(db.purchase_plans).values(id=plan_id, created_at=now)
            )
        else:
            session.execute(
                update(db.plan_versions)
                .where(
                    db.plan_versions.c.plan_id == plan_id,
                    db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED")),
                )
                .values(status="SUPERSEDED")
            )
        session.execute(
            insert(db.plan_versions).values(
                id=version_id,
                plan_id=plan_id,
                version=version_number,
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
            escalation_reason=body.escalation_reason,
            snapshot={**run.snapshot, "completion": body.model_dump(mode="json")},
            plan_version_id=version_id,
            completed_at=datetime.now(UTC),
        )
    )
    session.commit()
    return get_run(session, run_id)


def decide_plan(
    session: Session, version_id: str, body: PlanDecision, actor: str
) -> PurchasePlanVersion:
    lock_inventory(session)
    plan = read_plan(session, version_id)
    if body.plan_id != plan.plan_id or body.plan_version != plan.version:
        raise ApiError(
            409,
            "PLAN_VERSION_MISMATCH",
            "Decision must name the exact displayed plan and version",
        )
    decision = body.decision
    if plan.status == decision:
        event = (
            session.execute(
                select(db.events).where(
                    db.events.c.type
                    == ("PLAN_APPROVED" if decision == "APPROVED" else "PLAN_REJECTED"),
                    db.events.c.payload["version_id"].as_string() == version_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if event is None or event["payload"].get("instructions") != body.instructions:
            raise ApiError(
                409,
                "DECISION_CONFLICT",
                "This version already has a different recorded decision",
            )
        return plan
    if plan.status != "PENDING_APPROVAL":
        raise ApiError(
            409,
            "PLAN_NOT_PENDING",
            "Only a pending exact version can receive a decision",
        )
    certified_revision = session.execute(
        select(db.planning_runs.c.input_revision)
        .where(
            db.planning_runs.c.plan_version_id == version_id,
            db.planning_runs.c.status == "SUCCEEDED",
            db.planning_runs.c.outcome.in_(
                ("REVISE_PLAN", "KEEP_CURRENT_PLAN", "REQUEST_HUMAN_APPROVAL")
            ),
        )
        .order_by(db.planning_runs.c.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if decision == "APPROVED" and _revision(session) != certified_revision:
        raise ApiError(
            409, "PLAN_STALE", "Operational inputs changed; reassess before approval"
        )
    session.execute(
        update(db.plan_versions)
        .where(db.plan_versions.c.id == version_id)
        .values(status=decision)
    )
    record_event(
        session,
        "PLAN_APPROVED" if decision == "APPROVED" else "PLAN_REJECTED",
        actor,
        {
            "plan_id": plan.plan_id,
            "version_id": version_id,
            "version": plan.version,
            "instructions": body.instructions,
        },
    )
    session.commit()
    return read_plan(session, version_id)


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

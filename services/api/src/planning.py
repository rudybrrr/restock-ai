"""Short transactions around frozen agent runs and deterministic candidate validation."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src import database as db
from src.agent_contracts import (
    AgentCompletionPublication,
    AgentOutcome,
    AuditAction,
    AuditEvent,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    PlanPublicationResult,
    PlanStatus,
    StateRevisionStaleError,
)
from src.agent_contracts import (
    PurchasePlanLine as CanonicalPurchasePlanLine,
)
from src.agent_contracts import (
    PurchasePlanVersion as CanonicalPurchasePlanVersion,
)
from src.errors import ApiError
from src.fact_history import commitments_at, offers_at, promotions_at, sales_at
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
from src.procurement_contracts import freeze_first_slice_contract
from src.reconciliation import authoritative_daily_sales
from src.requirements import sum_recipe_usage
from src.sales import estimated_inventory
from src.schemas import RecipeItem


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
    return session.execute(
        select(func.count())
        .select_from(db.events)
        .where(
            db.events.c.type.not_in(
                ("PLAN_APPROVED", "PLAN_REJECTED", "PLAN_SUPERSEDED")
            )
        )
    ).scalar_one()


def current_state_revision(session: Session) -> str:
    """Return the authoritative opaque revision used by Agent publications."""
    return str(_revision(session))


def get_active_plan(
    session: Session, plan_id: str | None = None
) -> PurchasePlanVersion | None:
    """Return the latest actionable version, optionally scoped to one plan."""
    statement = select(db.plan_versions.c.id).where(
        db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED"))
    )
    if plan_id is not None:
        statement = statement.where(db.plan_versions.c.plan_id == plan_id)
    version_id = session.execute(
        statement.order_by(db.plan_versions.c.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    return read_plan(session, version_id) if version_id is not None else None


def get_event_context(session: Session, run_id: str, event_id: str) -> dict:
    """Read a trigger event only when it belongs to the requested planning run."""
    event = (
        session.execute(
            select(db.events)
            .join(
                db.assessment_requests,
                db.assessment_requests.c.event_id == db.events.c.id,
            )
            .where(
                db.assessment_requests.c.run_id == run_id,
                db.events.c.id == event_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if event is None:
        raise ApiError(404, "EVENT_CONTEXT_NOT_FOUND", "Run trigger event does not exist")
    return dict(event)


def _require_claimed_agent_revision(
    run: PlanningRun, captured_state_revision: str
) -> None:
    if captured_state_revision != str(run.input_revision):
        raise StateRevisionStaleError(
            "captured state revision does not match the claimed Backend run"
        )


def validate_candidate_reference(
    session: Session,
    run_id: str,
    reference_id: str,
    captured_state_revision: str,
) -> Candidate:
    """Validate a stored deterministic candidate without publishing it."""
    lock_inventory(session)
    run = get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Only a claimed assessment can validate")
    _require_claimed_agent_revision(run, captured_state_revision)
    artifacts = run.snapshot.get("decision_engine_artifacts")
    if artifacts is not None and reference_id == artifacts.get("candidate", {}).get("id"):
        validation = artifacts.get("validation", {})
        if (
            validation.get("candidate_id") != reference_id
            or validation.get("complete") is not True
            or validation.get("feasible") is not True
        ):
            raise ApiError(409, "UNCERTIFIED_OUTCOME", "Engine candidate lacks validation")
        return Candidate.model_validate(artifacts["candidate"]["candidate"])
    if reference_id != f"{run_id}:candidate":
        raise ApiError(409, "PLAN_INVALID", "Candidate reference does not belong to run")
    stored = run.snapshot.get("calculated_candidate")
    if stored is None:
        raise ApiError(409, "UNCERTIFIED_OUTCOME", "No deterministic candidate is stored")
    candidate = Candidate.model_validate(stored)
    _validate_candidate(run.snapshot, candidate)
    return candidate


def validate_human_review_request(
    session: Session, completion: AgentCompletionPublication
) -> None:
    """Ensure a Coordinator can request review only for the exact active version."""
    if completion.outcome is not AgentOutcome.REQUEST_HUMAN_APPROVAL:
        raise ApiError(422, "INVALID_OUTCOME", "Completion does not request review")
    if completion.affected_plan_id is None or completion.affected_plan_version is None:
        raise ApiError(409, "NO_CURRENT_PLAN", "Human review requires an exact plan version")
    lock_inventory(session)
    run = get_run(session, completion.run_id)
    _require_claimed_agent_revision(run, completion.captured_state_revision)
    active = get_active_plan(session, completion.affected_plan_id)
    if (
        active is None
        or active.version != completion.affected_plan_version
        or active.status is not PlanStatus.PENDING_APPROVAL
    ):
        raise ApiError(409, "PLAN_NOT_PENDING", "Only the exact pending version can be reviewed")


def _snapshot(
    session: Session,
    as_of: datetime,
    run_id: str,
    known_at: datetime | None = None,
    captured_state_revision: int | None = None,
) -> dict:
    known_at = known_at or datetime.now(UTC)
    captured_state_revision = (
        _revision(session)
        if captured_state_revision is None
        else captured_state_revision
    )
    offers, offer_versions = offers_at(session, as_of, known_at)
    missing_offer_history = sorted(
        set(session.execute(select(db.supplier_offers.c.id)).scalars())
        - {offer["id"] for offer in offers}
    )
    snapshot = {
        "as_of": as_of.isoformat(),
        "known_at": known_at.isoformat(),
        "offer_version_ids": offer_versions,
        "missing_offer_history": missing_offer_history,
        "authoritative_daily_sales": authoritative_daily_sales(
            session, as_of, known_at
        ),
        "forecast_id": f"{run_id}:forecast",
        "inventory_snapshot_id": f"{run_id}:inventory",
        "inventory": [
            _json(row) for row in estimated_inventory(session, as_of, known_at)
        ],
        "commitments": commitments_at(session, as_of, known_at),
        "ingredients": [
            _json(dict(row))
            for row in session.execute(
                select(db.ingredients).order_by(db.ingredients.c.id)
            ).mappings()
        ],
        "menu_items": [
            _json(dict(row))
            for row in session.execute(
                select(db.menu_items).order_by(db.menu_items.c.id)
            ).mappings()
        ],
        "suppliers": [
            _json(dict(row))
            for row in session.execute(
                select(db.suppliers).order_by(db.suppliers.c.id)
            ).mappings()
        ],
        "cycle_decisions": [
            _json(dict(row))
            for row in session.execute(
                select(db.order_cycles)
                .where(
                    db.order_cycles.c.effective_at <= as_of,
                    db.order_cycles.c.decided_at <= known_at,
                )
                .order_by(
                    db.order_cycles.c.ingredient_id, db.order_cycles.c.scheduled_date
                )
            ).mappings()
        ],
        "holidays": [
            _json(dict(row))
            for row in session.execute(
                select(db.holidays).order_by(db.holidays.c.date)
            ).mappings()
        ],
        "promotions": promotions_at(session, as_of, known_at),
        "daily_history": [
            _json(dict(row))
            for row in session.execute(
                select(db.daily_revisions)
                .where(
                    db.daily_revisions.c.cutoff <= as_of,
                    db.daily_revisions.c.recorded_at <= known_at,
                )
                .order_by(db.daily_revisions.c.day, db.daily_revisions.c.revision)
            ).mappings()
        ],
        "sales_batches": [_json(row) for row in sales_at(session, as_of, known_at)],
        "recipes": [
            _json(dict(row))
            for row in session.execute(
                select(db.recipes).order_by(
                    db.recipes.c.menu_item_id, db.recipes.c.ingredient_id
                )
            ).mappings()
        ],
        "offers": offers,
    }
    contract = freeze_first_slice_contract(
        session, as_of, known_at, captured_state_revision
    )
    if contract is not None:
        contract["run_id"] = run_id
        required_empty = (
            snapshot["commitments"],
            snapshot["daily_history"],
            snapshot["sales_batches"],
        )
        if any(required_empty):
            snapshot["procurement_contract_unavailable_reason"] = (
                "FIRST_SLICE_ACTIVITY_NOT_EMPTY"
            )
        else:
            contract["frozen_state"] = {
                key: snapshot[key]
                for key in (
                    "inventory",
                    "ingredients",
                    "menu_items",
                    "recipes",
                    "suppliers",
                    "commitments",
                    "daily_history",
                    "sales_batches",
                )
            }
            snapshot["procurement_contract"] = contract
    return snapshot


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
    captured_state_revision = _revision(session)
    snapshot = {
        **row["snapshot"],
        **_snapshot(
            session,
            row["as_of"],
            row["id"],
            now,
            captured_state_revision,
        ),
    }
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == row["id"])
        .values(
            status="RUNNING",
            claimed_at=now,
            deadline_at=now + timedelta(minutes=10),
            input_revision=captured_state_revision,
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
    if snapshot.get("missing_offer_history") or not snapshot["inventory"]:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Historical supplier or inventory observations are unavailable at this cutoff",
        )
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
    quantities = sum_recipe_usage(
        {dish: Decimal(quantity) for dish, quantity in body.dish_quantities.items()},
        [RecipeItem.model_validate(row) for row in snapshot["recipes"]],
    )
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


def complete_run(
    session: Session,
    run_id: str,
    body: Completion,
    *,
    captured_state_revision: str | None = None,
    audit_events: Sequence[AuditEvent] = (),
) -> PlanningRun:
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
    expected_revision = captured_state_revision or str(run.input_revision)
    if (
        expected_revision != str(run.input_revision)
        or current_state_revision(session) != expected_revision
    ):
        session.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run_id)
            .values(
                status="FAILED",
                failure_reason="STATE_REVISION_STALE",
                completed_at=datetime.now(UTC),
            )
        )
        session.commit()
        raise ApiError(
            409,
            "STATE_REVISION_STALE",
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
        artifacts = snapshot.get("decision_engine_artifacts")
        engine_candidate = (
            candidate.calculation_mode == "ENGINE"
            and artifacts is not None
            and artifacts.get("candidate", {}).get("candidate")
            == candidate.model_dump(mode="json")
            and artifacts.get("validation", {}).get("candidate_id")
            == artifacts.get("candidate", {}).get("id")
            and artifacts.get("validation", {}).get("complete") is True
            and artifacts.get("validation", {}).get("feasible") is True
        )
        if not engine_candidate:
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
        active_versions = (
            session.execute(
                select(db.plan_versions).where(
                    db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED"))
                )
            )
            .mappings()
            .all()
        )
        for old in active_versions:
            session.execute(
                update(db.plan_versions)
                .where(db.plan_versions.c.id == old["id"])
                .values(status="SUPERSEDED")
            )
            record_event(
                session,
                "PLAN_SUPERSEDED",
                "backend",
                {
                    "plan_id": old["plan_id"],
                    "version_id": old["id"],
                    "version": old["version"],
                    "replacement_version_id": version_id,
                    "previous_status": old["status"],
                    "reason": "New recommendation replaces the restaurant's actionable plan",
                },
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
    _persist_agent_audit(session, run, audit_events, version_id)
    session.commit()
    return get_run(session, run_id)


def _persist_agent_audit(
    session: Session,
    run: PlanningRun,
    audit_events: Sequence[AuditEvent],
    plan_version_id: str | None,
) -> None:
    """Append canonical Agent trace events to the existing Backend audit store."""
    if not audit_events:
        return
    if run.trigger_event_id is None:
        raise ApiError(409, "AUDIT_CONTEXT_MISSING", "Run has no persisted trigger event")
    publication = None
    if plan_version_id is not None:
        publication = dict(
            session.execute(
                select(
                    db.plan_versions.c.id,
                    db.plan_versions.c.plan_id,
                    db.plan_versions.c.version,
                    db.plan_versions.c.status,
                ).where(db.plan_versions.c.id == plan_version_id)
            )
            .mappings()
            .one()
        )
    for event in audit_events:
        if event.run_id != run.id:
            raise ApiError(409, "AUDIT_CONTEXT_MISMATCH", "Audit event belongs to another run")
        payload = event.model_dump(mode="json")
        if event.action is AuditAction.RUN_COMPLETED:
            payload["backend_publication"] = {
                "plan_version": publication,
                "requested_outcome": event.final_outcome,
            }
        session.execute(
            pg_insert(db.audit_entries)
            .values(
                id=event.audit_event_id,
                event_id=run.trigger_event_id,
                actor=event.actor,
                action=event.action,
                timestamp=event.timestamp,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )


def _canonical_plan_version(
    stored: PurchasePlanVersion,
    run: PlanningRun,
    completion: AgentCompletionPublication,
) -> CanonicalPurchasePlanVersion:
    units = {
        ingredient["id"]: ingredient["unit"]
        for ingredient in run.snapshot["ingredients"]
    }
    candidate_ref = completion.candidate_result_ref
    if candidate_ref is None:
        raise ApiError(409, "PLAN_INVALID", "Published plan has no candidate reference")
    revision = completion.captured_state_revision
    return CanonicalPurchasePlanVersion(
        plan_id=stored.plan_id,
        version=stored.version,
        status=stored.status,
        forecast_ref=EvidenceRef(
            category=EvidenceCategory.FORECAST_RESULT,
            source=EvidenceSource.BACKEND,
            reference_id=stored.forecast_id,
            state_revision=revision,
        ),
        inventory_snapshot_ref=EvidenceRef(
            category=EvidenceCategory.INVENTORY_SNAPSHOT,
            source=EvidenceSource.BACKEND,
            reference_id=stored.inventory_snapshot_id,
            state_revision=revision,
        ),
        candidate_result_ref=candidate_ref,
        created_at=stored.created_at,
        trigger_id=run.trigger_event_id or completion.run_id,
        state_revision=revision,
        lines=[
            CanonicalPurchasePlanLine(
                ingredient_id=line.ingredient_id,
                supplier_id=line.supplier_id,
                offer_id=line.offer_id,
                opportunity_id=line.opportunity_id,
                shipment_group_id=line.shipment_group_id,
                quantity=line.quantity,
                unit=units[line.ingredient_id],
                unit_price=line.unit_price,
                delivery_at=line.arrival_at,
            )
            for line in stored.lines
        ],
        total_purchase_cost=stored.total_purchase_cost,
        expected_waste_cost=stored.expected_waste_cost,
        expected_stockout_cost=stored.expected_stockout_cost,
        delivery_cost=stored.delivery_cost,
        emergency_penalty=stored.emergency_penalty,
        total_expected_cost=stored.total_expected_cost,
        approval_reason="MANAGER_APPROVAL_REQUIRED",
    )


def publish_agent_completion(
    session: Session,
    completion: AgentCompletionPublication,
    trace: Sequence[AuditEvent],
) -> PlanPublicationResult:
    """Publish one canonical Agent completion through the Backend transaction."""
    candidate = None
    if completion.outcome is AgentOutcome.REVISE_PLAN:
        if completion.candidate_result_ref is None:
            raise ApiError(422, "INVALID_OUTCOME", "REVISE_PLAN requires a candidate")
        candidate = validate_candidate_reference(
            session,
            completion.run_id,
            completion.candidate_result_ref.reference_id,
            completion.captured_state_revision,
        )
    body = Completion(
        outcome=completion.outcome,
        escalation_reason=completion.escalation_reason,
        candidate=candidate,
    )
    try:
        published = complete_run(
            session,
            completion.run_id,
            body,
            captured_state_revision=completion.captured_state_revision,
            audit_events=trace,
        )
    except ApiError as error:
        if error.detail.code == "STATE_REVISION_STALE":
            raise StateRevisionStaleError(error.detail.message) from error
        raise
    created = None
    if published.plan_version_id is not None and completion.outcome is AgentOutcome.REVISE_PLAN:
        created = _canonical_plan_version(
            read_plan(session, published.plan_version_id), published, completion
        )
    return PlanPublicationResult(
        run_id=published.id,
        state_revision=completion.captured_state_revision,
        requested_outcome=completion.outcome,
        created_plan_version=created,
        audit_event_refs=[
            EvidenceRef(
                category=EvidenceCategory.AUDIT_EVENT,
                source=EvidenceSource.BACKEND,
                reference_id=event.audit_event_id,
                state_revision=completion.captured_state_revision,
            )
            for event in trace
        ],
        published_at=published.completed_at or datetime.now(UTC),
    )


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
            409,
            "PLAN_VERSION_STALE",
            "Operational inputs changed; reassess before approval",
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

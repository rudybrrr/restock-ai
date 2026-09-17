"""Narrow deterministic materiality evidence for supplier disruption reassessment."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import database as db
from src.agent_contracts import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    MaterialityAssessment,
)
from src.errors import ApiError
from src.planning_schemas import PlanningRun, PurchasePlanVersion

SUPPORTED_SUPPLIER_EVENTS = frozenset(
    {"SUPPLIER_AVAILABILITY_CHANGED", "SUPPLIER_STATUS_CHANGED"}
)


def supplier_materiality(
    session: Session,
    run: PlanningRun,
    active_plan: PurchasePlanVersion | None,
    events: Sequence[dict],
) -> MaterialityAssessment | None:
    """Assess only selected supplier offers against the frozen post-event state.

    The assessment deliberately does not calculate substitutes or prices.  It only
    establishes whether an authoritative availability/status change makes the
    existing selected allocation unusable, which is the routing boundary for the
    real Procurement and Decision Engine path.
    """
    supplier_events = [event for event in events if event["type"] in SUPPORTED_SUPPLIER_EVENTS]
    if not supplier_events:
        return None
    revision = str(run.input_revision)
    reference = EvidenceRef(
        category=EvidenceCategory.MATERIALITY,
        source=EvidenceSource.BACKEND,
        reference_id=f"{run.id}:supplier-materiality",
        state_revision=revision,
    )
    if active_plan is None:
        return MaterialityAssessment(
            source_event_ids=[event["id"] for event in supplier_events],
            captured_state_revision=revision,
            material=False,
            current_plan_unactionable=False,
            reason_codes=["NO_ACTIONABLE_PLAN"],
            evidence_ref=reference,
        )

    version_id = session.execute(
        select(db.plan_versions.c.id).where(
            db.plan_versions.c.plan_id == active_plan.plan_id,
            db.plan_versions.c.version == active_plan.version,
        )
    ).scalar_one_or_none()
    if version_id is None:
        raise ApiError(409, "NO_CURRENT_PLAN", "Materiality target no longer exists")
    selected_by_offer: dict[str, list[dict]] = {}
    for row in session.execute(
        select(db.purchase_plan_lines).where(
            db.purchase_plan_lines.c.plan_version_id == version_id
        )
    ).mappings():
        line = dict(row)
        if line["offer_id"] is not None:
            selected_by_offer.setdefault(line["offer_id"], []).append(line)
    offers = {offer["id"]: offer for offer in run.snapshot.get("offers", [])}
    affected_offer_ids = {
        str(event["payload"].get("offer_id"))
        for event in supplier_events
        if event["payload"].get("offer_id") in selected_by_offer
    }
    affected_lines = [
        line for offer_id in sorted(affected_offer_ids) for line in selected_by_offer[offer_id]
    ]
    unusable = False
    for offer_id in affected_offer_ids:
        offer = offers.get(offer_id)
        if offer is None:
            raise ApiError(
                409,
                "MISSING_REQUIRED_DATA",
                "Frozen supplier state is missing an affected selected offer",
            )
        planned = sum((line["quantity"] for line in selected_by_offer[offer_id]), Decimal(0))
        available = offer.get("available_quantity")
        unusable = unusable or (
            offer.get("current_status") != "AVAILABLE"
            or available is None
            or Decimal(str(available)) < planned
        )
    if not affected_offer_ids:
        codes = ["SUPPLIER_CHANGE_OUTSIDE_CURRENT_PLAN"]
    elif unusable:
        codes = ["SELECTED_SUPPLIER_OFFER_UNUSABLE"]
    else:
        codes = ["SELECTED_SUPPLIER_OFFER_REMAINS_FEASIBLE"]
    return MaterialityAssessment(
        source_event_ids=[event["id"] for event in supplier_events],
        captured_state_revision=revision,
        affected_plan_id=active_plan.plan_id,
        affected_plan_version=active_plan.version,
        affected_ingredient_ids=sorted({line["ingredient_id"] for line in affected_lines}),
        affected_offer_ids=sorted(affected_offer_ids),
        affected_supplier_ids=sorted({line["supplier_id"] for line in affected_lines}),
        affected_plan_line_ids=sorted({line["id"] for line in affected_lines}),
        material=unusable,
        current_plan_unactionable=unusable,
        reason_codes=codes,
        evidence_ref=reference,
    )


def supplier_events_for_run(session: Session, run_id: str) -> list[dict]:
    """Return the durable coalesced triggers belonging to one claimed run."""
    return [
        dict(row)
        for row in session.execute(
            select(db.events)
            .join(db.assessment_requests, db.assessment_requests.c.event_id == db.events.c.id)
            .where(db.assessment_requests.c.run_id == run_id)
            .order_by(db.events.c.timestamp, db.events.c.id)
        ).mappings()
    ]

"""Manager projections selected from verified persisted contingency results."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter
from sqlalchemy.orm import Session

from src import planning
from src.agent_contracts import EscalationReason
from src.multiday_projection import MultiDayProjection
from src.post_purchase_contingency import RESULT_KEY, read_post_purchase_result


class ManagerContingencyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["MANAGER_CONTINGENCY_PROJECTION_V1"] = "MANAGER_CONTINGENCY_PROJECTION_V1"
    run_id: str
    result_reference: str
    input_sha256: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    stale: bool
    plan_version_id: str | None
    candidate_reference: str | None
    complete: bool
    outcome: Literal["KEEP_CURRENT_PLAN", "REVISE_PLAN", "ESCALATE"]
    escalation_reason: EscalationReason | None
    findings: list[str]
    fixed_delivery_ids: list[str]
    existing_commitments_projection: MultiDayProjection | None
    with_recommendation_projection: MultiDayProjection | None
    limitations: list[str]


def read_projection(session: Session, run_id: str) -> ManagerContingencyProjection | None:
    run = planning.get_run(session, run_id)
    if RESULT_KEY not in run.snapshot:
        return None
    result = read_post_purchase_result(session, run_id)
    numerical = result.numerical_result or {}
    no_purchase = numerical.get("no_purchase")
    existing = no_purchase.get("projection") if isinstance(no_purchase, dict) else None
    validation = result.independent_validation or {}
    # A diagnostic incumbent is never a recommendation; use only the independently
    # validated additional candidate selected for REVISE_PLAN.
    recommended = validation.get("projection") if result.outcome == "REVISE_PLAN" else None
    adapter = TypeAdapter(MultiDayProjection)
    return ManagerContingencyProjection(
        run_id=run.id, result_reference=result.id, input_sha256=result.input_sha256,
        as_of=result.as_of, known_at=result.known_at,
        captured_state_revision=result.captured_state_revision,
        stale=planning.current_state_revision(session) != result.captured_state_revision,
        plan_version_id=run.plan_version_id,
        candidate_reference=result.candidate_reference if result.outcome == "REVISE_PLAN" else None,
        complete=result.complete, outcome=result.outcome,
        escalation_reason=result.escalation_reason, findings=result.findings,
        fixed_delivery_ids=result.fixed_delivery_ids,
        existing_commitments_projection=adapter.validate_python(existing) if existing is not None else None,
        with_recommendation_projection=adapter.validate_python(recommended) if recommended is not None else None,
        limitations=[
            "Bounded approved contingency domain; not a general forecast horizon.",
            "Each ingredient has its own protected end and verified prefix.",
            "Projected expiry quantities are not measured waste.",
            "Projection completeness is not full-economic optimality.",
        ],
    )

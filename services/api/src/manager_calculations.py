"""Version-bound numerical outputs for manager display, never model messages."""

import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session

from src import planning
from src.errors import ApiError
from src.forecasting import DishForecast
from src.inventory_projection import InventoryProjection
from src.promotion_forecasting import ForecastVersion
from src.sales_materiality_schemas import _json_safe

SNAPSHOT_KEY = "manager_calculation_outputs"


class ForecastDish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    baseline: DishForecast


class CalculationOutputs(BaseModel):
    """Stored numerical results; no live joins or recalculation on reads."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["MANAGER_CALCULATION_OUTPUTS_V1"] = "MANAGER_CALCULATION_OUTPUTS_V1"
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    policy_id: str
    policy_version: int
    forecast_input_id: str
    forecast_input_version: int
    candidate_id: str
    timezone: Literal["Asia/Singapore"] = "Asia/Singapore"
    bucket_boundary: Literal["START_INCLUSIVE_END_EXCLUSIVE"] = "START_INCLUSIVE_END_EXCLUSIVE"
    forecast_method: Literal["SEASONAL_BASELINE_V1"] = "SEASONAL_BASELINE_V1"
    portions_semantics: Literal["FRACTIONAL_EXPECTATION"] = "FRACTIONAL_EXPECTATION"
    censored_history_present: bool
    dishes: list[ForecastDish]
    forecast: ForecastVersion
    existing_commitments_projection: InventoryProjection
    with_recommendation_projection: InventoryProjection
    proposed_supply_ids: list[str]
    limitations: list[str]

    @field_serializer("forecast", when_used="json")
    def serialize_forecast(self, value: ForecastVersion):
        return _json_safe(value)


class CalculationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    content_sha256: str
    outputs: CalculationOutputs


class ManagerCalculationDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: Literal["AVAILABLE", "NOT_RECORDED"]
    current_state_revision: str
    stale: bool | None
    plan_version_id: str | None
    artifact: CalculationArtifact | None


def freeze_outputs(outputs: CalculationOutputs) -> CalculationArtifact:
    payload = outputs.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CalculationArtifact(
        id=f"manager-calculation:{outputs.run_id}:{digest}",
        content_sha256=digest,
        outputs=outputs,
    )


def read_outputs(session: Session, run_id: str) -> ManagerCalculationDisplay:
    run = planning.get_run(session, run_id)
    revision = planning.current_state_revision(session)
    raw = run.snapshot.get(SNAPSHOT_KEY)
    if raw is None:
        return ManagerCalculationDisplay(
            run_id=run.id, status="NOT_RECORDED", current_state_revision=revision,
            stale=None, plan_version_id=run.plan_version_id, artifact=None,
        )
    artifact = CalculationArtifact.model_validate(raw)
    if (
        artifact != freeze_outputs(artifact.outputs)
        or artifact.outputs.run_id != run.id
        or artifact.outputs.captured_state_revision != str(run.input_revision)
    ):
        raise ApiError(409, "CALCULATION_ARTIFACT_MISMATCH", "Stored outputs do not match their run")
    return ManagerCalculationDisplay(
        run_id=run.id, status="AVAILABLE", current_state_revision=revision,
        stale=revision != artifact.outputs.captured_state_revision,
        plan_version_id=run.plan_version_id, artifact=artifact,
    )

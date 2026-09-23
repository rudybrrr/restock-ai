"""Persist one non-actionable numerical artifact from a claimed frozen run."""

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import update
from sqlalchemy.orm import Session

from src import database as db
from src import planning
from src.contingency_stage_adapter import (
    StagedContingencyDiagnostic,
    calculate_staged_case,
)
from src.errors import ApiError
from src.operations import lock_inventory
from src.planning_schemas import PlanningRun

SNAPSHOT_KEY = "staged_contingency_artifact"


class StagedContingencyArtifact(BaseModel):
    """Full frozen result and independent validation; never a plan certificate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    run_id: str
    captured_state_revision: str
    input_sha256: str
    status: Literal["STAGED_DIAGNOSTIC"] = "STAGED_DIAGNOSTIC"
    actionable: Literal[False] = False
    diagnostic: StagedContingencyDiagnostic
    result: dict[str, JsonValue]
    independent_validation: dict[str, JsonValue] | None


def _jsonable(value: object) -> JsonValue:
    """Serialize numerical evidence losslessly, rejecting unknown result types."""
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ApiError(
                409, "CALCULATION_INCOMPLETE", "Numerical evidence has non-string keys"
            )
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return cast(JsonValue, value)
    raise ApiError(
        409, "CALCULATION_INCOMPLETE", "Numerical evidence cannot be serialized"
    )


def _sha256(value: JsonValue) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _artifact_id(
    run_id: str,
    revision: str,
    input_sha256: str,
    diagnostic: StagedContingencyDiagnostic,
    result: dict[str, JsonValue],
    validation: dict[str, JsonValue] | None,
) -> str:
    identity = _sha256(
        _jsonable(
            {
                "run_id": run_id,
                "revision": revision,
                "input_sha256": input_sha256,
                "diagnostic": diagnostic.model_dump(mode="json"),
                "result": result,
                "validation": validation,
            }
        )
    )
    return f"staged-contingency:{run_id}:{identity}"


def _verify_artifact(run: PlanningRun, artifact: StagedContingencyArtifact) -> None:
    frozen = run.snapshot.get("staged_contingency_case")
    if frozen is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "Staged input is missing")
    if (
        artifact.run_id != run.id
        or artifact.captured_state_revision != str(run.input_revision)
        or artifact.input_sha256 != _sha256(_jsonable(frozen))
        or artifact.id
        != _artifact_id(
            run.id,
            str(run.input_revision),
            artifact.input_sha256,
            artifact.diagnostic,
            artifact.result,
            artifact.independent_validation,
        )
    ):
        raise ApiError(
            409, "STATE_REVISION_STALE", "Staged artifact identity does not match run"
        )


def read_staged_artifact(session: Session, run_id: str) -> StagedContingencyArtifact:
    run = planning.get_run(session, run_id)
    raw = run.snapshot.get(SNAPSHOT_KEY)
    if raw is None:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Staged numerical artifact not calculated"
        )
    artifact = StagedContingencyArtifact.model_validate(raw)
    _verify_artifact(run, artifact)
    return artifact


def persist_staged_artifact(session: Session, run_id: str) -> StagedContingencyArtifact:
    """Calculate once from the claimed snapshot; never create a plan or order."""
    lock_inventory(session)
    run = planning.get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Only a claimed run can calculate")
    if planning.current_state_revision(session) != str(run.input_revision):
        raise ApiError(
            409, "STATE_REVISION_STALE", "Operational inputs changed since claim"
        )
    frozen = run.snapshot.get("staged_contingency_case")
    if frozen is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "No staged case for this run")
    input_sha256 = _sha256(_jsonable(frozen))
    existing = run.snapshot.get(SNAPSHOT_KEY)
    if existing is not None:
        artifact = StagedContingencyArtifact.model_validate(existing)
        _verify_artifact(run, artifact)
        return artifact

    computation = calculate_staged_case(run)
    result = cast(dict[str, JsonValue], _jsonable(computation.result))
    validation = (
        cast(dict[str, JsonValue], _jsonable(computation.independent_validation))
        if computation.independent_validation is not None
        else None
    )
    artifact = StagedContingencyArtifact(
        id=_artifact_id(
            run.id,
            str(run.input_revision),
            input_sha256,
            computation.diagnostic,
            result,
            validation,
        ),
        run_id=run.id,
        captured_state_revision=str(run.input_revision),
        input_sha256=input_sha256,
        diagnostic=computation.diagnostic,
        result=result,
        independent_validation=validation,
    )
    changed = session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run.id, db.planning_runs.c.status == "RUNNING")
        .values(
            snapshot={**run.snapshot, SNAPSHOT_KEY: artifact.model_dump(mode="json")}
        )
        .returning(db.planning_runs.c.id)
    ).scalar_one_or_none()
    if changed != run.id:
        raise ApiError(409, "RUN_NOT_RUNNING", "Claimed run changed during calculation")
    session.commit()
    return artifact

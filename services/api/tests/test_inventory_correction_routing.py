from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src import database as db
from src import planning
from src.agent_contracts import (
    AgentOutcome,
    AgentToolName,
    SpecialistType,
)
from src.backend_control_plane import run_backend_coordinator
from src.decision_engine_adapter import BackendProcurementTools
from src.evaluation.adapters import FirstSliceProcurementScript
from src.operations import record_event

ISSUE_TIME = datetime.fromisoformat("2026-02-15T22:00:00+08:00")


def sign_in(client: TestClient) -> None:
    client.headers.pop("Authorization", None)
    client.headers["Origin"] = "https://frontend.example"
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "test-manager-password"},
    )
    assert response.status_code == 200, response.text


class ProcurementOnlyClassifier:
    def classify(
        self, invocation, context_refs: Sequence[Any]
    ) -> Sequence[SpecialistType]:
        return [SpecialistType.PROCUREMENT]


class RecordingProcurementTools(BackendProcurementTools):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.calls: list[AgentToolName] = []

    def execute(self, request):
        self.calls.append(request.tool)
        return super().execute(request)


def _publish_initial_engine_plan(database_url: str) -> tuple[str, int]:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run = planning.request_run(session, ISSUE_TIME)
            claimed = planning.claim_run(session)
            assert claimed.id == run.id
            result = run_backend_coordinator(
                session,
                claimed.id,
                FirstSliceProcurementScript(),
                BackendProcurementTools(session),
                manual_classifier=ProcurementOnlyClassifier(),
            )
            assert result.completion.outcome is AgentOutcome.REVISE_PLAN
            assert result.publication_result is not None
            created = result.publication_result.created_plan_version
            assert created is not None
            return created.plan_id, created.version
    finally:
        engine.dispose()


def _submit_correction(client: TestClient, *, lot_id: str, amount: str) -> dict:
    sign_in(client)
    day = "/api/v1/daily-updates/2026-02-15"
    lots = client.get("/api/v1/inventory").json()
    dishes = client.get("/api/v1/menu-items").json()
    initial = {
        "cutoff": "2026-02-15T22:00:00+08:00",
        "counts": {lot["id"]: lot["quantity"] for lot in lots},
        "sales": {dish["id"]: 0 for dish in dishes},
    }
    assert client.post(day + "/draft", json=initial).status_code == 200
    assert client.post(day + "/submit").status_code == 200
    client.headers["Authorization"] = "Bearer test-agent-token"
    first = client.post("/api/v1/runs/claim")
    assert first.status_code == 200, first.text
    completed = client.post(
        f"/api/v1/runs/{first.json()['id']}/complete",
        json={"outcome": "ESCALATE", "escalation_reason": "MISSING_REQUIRED_DATA"},
    )
    assert completed.status_code == 200, completed.text
    client.headers.pop("Authorization", None)
    corrected = {**initial, "counts": {**initial["counts"], lot_id: amount}}
    assert client.post(day + "/draft", json=corrected).status_code == 200
    submitted = client.post(day + "/submit")
    assert submitted.status_code == 200, submitted.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def _assessment_payload(run: dict, context: dict, *, material: bool) -> dict:
    return {
        "material_change": material,
        "complete": True,
        "inventory_feasible": True,
        "assessed_lot_ids": context["assessed_lot_ids"],
        "assessed_ingredient_ids": context["assessed_ingredient_ids"],
        "findings": ([{"code": "CORRECTION_MATERIAL", "source": "authoritative"}] if material else []),
        "evidence_refs": context["required_evidence_refs"],
        "required_follow_up": [],
        "run_id": run["id"],
        "snapshot_reference": context["snapshot_reference"],
        "inventory_snapshot_reference": context["inventory_snapshot_reference"],
        "captured_state_revision": context["captured_state_revision"],
        "as_of": context["as_of"],
        "known_at": context["known_at"],
        "adjustment_event_ids": [item["id"] for item in context["adjustment_events"]],
        "plan_id": context["plan_id"],
        "plan_version_reference": context["plan_version_reference"],
    }


def _claim_correction_with_plan(
    client: TestClient, database_url: str, *, material: bool
) -> tuple[dict, str, int]:
    plan_id, plan_version = _publish_initial_engine_plan(database_url)
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    lot = next(
        item for item in lots if item["id"] == ("chicken-01" if material else lots[0]["id"])
    )
    run = _submit_correction(
        client,
        lot_id=lot["id"],
        amount=(
            str(float(lot["quantity"]) - 0.5)
            if material
            else str(float(lot["quantity"]) + 0.5)
        ),
    )
    context_response = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    )
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["plan_id"] == plan_id
    assert context["plan_version_reference"]
    result = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": _assessment_payload(run, context, material=material)},
    )
    assert result.status_code == 200, result.text
    return run, plan_id, plan_version


def test_safe_correction_routes_inventory_only_and_keeps_current_plan(
    client: TestClient, database_url: str
) -> None:
    run, plan_id, plan_version = _claim_correction_with_plan(
        client, database_url, material=False
    )
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            procurement = RecordingProcurementTools(session)
            execution = run_backend_coordinator(
                session,
                run["id"],
                FirstSliceProcurementScript(),
                procurement,
            )
            assert execution.completion.outcome is AgentOutcome.KEEP_CURRENT_PLAN
            assert procurement.calls == []
            assert execution.publication_result is not None
            assert execution.publication_result.created_plan_version is None
            current = session.execute(
                select(db.plan_versions).where(
                    db.plan_versions.c.plan_id == plan_id,
                    db.plan_versions.c.version == plan_version,
                )
            ).mappings().one()
            assert current["status"] == "PENDING_APPROVAL"
            assert any(
                event.action.value == "MATERIALITY_ASSESSED"
                and event.materiality is not None
                and event.materiality.material is False
                for event in execution.trace
            )
    finally:
        engine.dispose()


def test_material_correction_routes_procurement_and_publishes_engine_revision(
    client: TestClient, database_url: str
) -> None:
    run, plan_id, plan_version = _claim_correction_with_plan(
        client, database_url, material=True
    )
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            procurement = RecordingProcurementTools(session)
            execution = run_backend_coordinator(
                session,
                run["id"],
                FirstSliceProcurementScript(),
                procurement,
            )
            assert execution.completion.outcome is AgentOutcome.REVISE_PLAN
            assert execution.publication_result is not None
            created = execution.publication_result.created_plan_version
            assert created is not None
            assert created.status.value == "PENDING_APPROVAL"
            assert created.version == plan_version + 1
            assert created.plan_id == plan_id
            created_id = session.execute(
                select(db.plan_versions.c.id).where(
                    db.plan_versions.c.plan_id == plan_id,
                    db.plan_versions.c.version == created.version,
                )
            ).scalar_one()
            assert planning.read_plan(session, created_id).calculation_mode == "ENGINE"
            old = session.execute(
                select(db.plan_versions).where(
                    db.plan_versions.c.plan_id == plan_id,
                    db.plan_versions.c.version == plan_version,
                )
            ).mappings().one()
            assert old["status"] == "SUPERSEDED"
            assert procurement.calls == [
                AgentToolName.OPTIMISE_PURCHASE_PLAN,
                AgentToolName.VALIDATE_PURCHASE_PLAN,
            ]
    finally:
        engine.dispose()


def test_unknown_inventory_assessment_fails_closed_without_procurement(
    client: TestClient, database_url: str
) -> None:
    _publish_initial_engine_plan(database_url)
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    run = _submit_correction(client, lot_id=lots[0]["id"], amount="99")
    context = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    ).json()
    unknown = _assessment_payload(run, context, material=False)
    unknown.update({"complete": False, "material_change": None, "inventory_feasible": None})
    saved = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": unknown},
    )
    assert saved.status_code == 200, saved.text
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            procurement = RecordingProcurementTools(session)
            execution = run_backend_coordinator(
                session,
                run["id"],
                FirstSliceProcurementScript(),
                procurement,
            )
            assert execution.completion.outcome is AgentOutcome.ESCALATE
            assert execution.completion.escalation_reason is not None
            assert execution.completion.escalation_reason.value == "MISSING_REQUIRED_DATA"
            assert procurement.calls == []
    finally:
        engine.dispose()


def test_agent_cannot_override_material_inventory_assessment(
    client: TestClient, database_url: str
) -> None:
    _publish_initial_engine_plan(database_url)
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    run = _submit_correction(client, lot_id=lots[0]["id"], amount="99")
    context = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    ).json()
    saved = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": _assessment_payload(run, context, material=True)},
    )
    assert saved.status_code == 200, saved.text
    override = client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={"outcome": "KEEP_CURRENT_PLAN"},
    )
    assert override.status_code == 409, override.text
    assert override.json()["error"]["code"] == "UNCERTIFIED_OUTCOME"


def test_inventory_adjustment_context_mismatches_fail_closed(
    client: TestClient,
) -> None:
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    run = _submit_correction(client, lot_id=lots[0]["id"], amount="99")
    context = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    ).json()
    payload = _assessment_payload(run, context, material=False)

    for field, value in (
        ("assessed_lot_ids", ["wrong-lot"]),
        ("assessed_ingredient_ids", ["wrong-ingredient"]),
    ):
        mismatched = {**payload, field: value}
        response = client.put(
            f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
            json={"result": mismatched},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "INVENTORY_ADJUSTMENT_CONTEXT_MISMATCH"

    incomplete = {**payload, "evidence_refs": []}
    response = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": incomplete},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVENTORY_ADJUSTMENT_EVIDENCE_INCOMPLETE"


def test_inventory_adjustment_stale_revision_is_rejected(
    client: TestClient, database_url: str
) -> None:
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    run = _submit_correction(client, lot_id=lots[0]["id"], amount="99")
    context = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    ).json()
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            record_event(
                session,
                "SALES_UPDATED",
                "manager",
                {
                    "effective_at": "2026-02-15T22:00:00+08:00",
                    "instruction": "stale revision test",
                },
            )
            session.commit()
    finally:
        engine.dispose()

    response = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": _assessment_payload(run, context, material=False)},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_RUN_INPUT"

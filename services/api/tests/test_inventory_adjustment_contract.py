from decimal import Decimal

from fastapi.testclient import TestClient


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "test-manager-password"},
    )
    assert response.status_code == 200, response.text


def use_agent(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"


def complete_initial_submission(client: TestClient) -> tuple[str, dict, dict]:
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    dishes = client.get("/api/v1/menu-items").json()
    day = "/api/v1/daily-updates/2026-02-16"
    draft = {
        "cutoff": "2026-02-16T21:00:00+08:00",
        "counts": {lot["id"]: lot["quantity"] for lot in lots},
        "sales": {dish["id"]: 0 for dish in dishes},
    }
    assert client.post(day + "/draft", json=draft).status_code == 200
    submitted = client.post(day + "/submit")
    assert submitted.status_code == 200, submitted.text
    use_agent(client)
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    completed = client.post(
        f"/api/v1/runs/{claimed.json()['id']}/complete",
        json={"outcome": "ESCALATE", "escalation_reason": "MISSING_REQUIRED_DATA"},
    )
    assert completed.status_code == 200, completed.text
    del client.headers["Authorization"]
    return day, draft, lots[0]


def test_safe_inventory_correction_can_certify_keep_current_plan(
    client: TestClient,
) -> None:
    day, draft, corrected_lot = complete_initial_submission(client)
    corrected_quantity = Decimal(corrected_lot["quantity"]) + Decimal("0.5")
    corrected = {
        **draft,
        "counts": {**draft["counts"], corrected_lot["id"]: str(corrected_quantity)},
    }
    assert client.post(day + "/draft", json=corrected).status_code == 200
    submitted = client.post(day + "/submit")
    assert submitted.status_code == 200, submitted.text

    event = next(
        event
        for event in client.get("/api/v1/events").json()
        if event["type"] == "INVENTORY_ADJUSTED"
    )
    assert event["payload"]["revision_id"] == submitted.json()["id"]
    assert event["payload"]["adjustments"][0]["lot_id"] == corrected_lot["id"]
    assert Decimal(event["payload"]["adjustments"][0]["delta"]) == Decimal("0.5")

    use_agent(client)
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    context_response = client.get(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-context"
    )
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["adjustment_events"] == [event]
    assert context["captured_state_revision"] == str(run["input_revision"])
    assert next(
        lot for lot in context["inventory"] if lot["id"] == corrected_lot["id"]
    )["quantity"] == str(corrected_quantity)

    event_ids = [item["id"] for item in context["adjustment_events"]]
    result = {
        "material_change": False,
        "complete": True,
        "inventory_feasible": True,
        "assessed_lot_ids": context["assessed_lot_ids"],
        "assessed_ingredient_ids": context["assessed_ingredient_ids"],
        "findings": [],
        "evidence_refs": context["required_evidence_refs"],
        "required_follow_up": [],
        "run_id": run["id"],
        "snapshot_reference": context["snapshot_reference"],
        "inventory_snapshot_reference": context["inventory_snapshot_reference"],
        "captured_state_revision": context["captured_state_revision"],
        "as_of": context["as_of"],
        "known_at": context["known_at"],
        "adjustment_event_ids": event_ids,
        "plan_id": context["plan_id"],
        "plan_version_reference": context["plan_version_reference"],
    }
    saved = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": result},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["result_sha256"]
    manager_path = f"/api/v1/manager/runs/{run['id']}/inventory-adjustment"
    assert client.get(manager_path).status_code == 403
    del client.headers["Authorization"]
    displayed = client.get(manager_path)
    assert displayed.status_code == 200
    assert displayed.json() == saved.json()
    links = client.get(f"/api/v1/manager/events/{event['id']}/assessments")
    assert links.status_code == 200
    assert [link["run_id"] for link in links.json()] == [run["id"]]
    use_agent(client)
    completed = client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={"outcome": "KEEP_CURRENT_PLAN"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["outcome"] == "KEEP_CURRENT_PLAN"
    retry = client.put(
        f"/api/v1/runs/{run['id']}/inventory-adjustment-assessment",
        json={"result": result},
    )
    assert retry.status_code == 200
    assert retry.json()["result_sha256"] == saved.json()["result_sha256"]

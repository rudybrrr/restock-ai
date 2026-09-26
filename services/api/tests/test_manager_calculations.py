from decimal import Decimal

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from src import database as db
from src import planning
from src.manager_calculations import SNAPSHOT_KEY
from tests.test_assessment_worker import prepare_engine_plan, queue_manager_assessment


def test_sales_manager_read_preserves_issued_forecast_without_engine_request(client, database_url, monkeypatch):
    from src.assessment_worker import ensure_claimed_sales_materiality
    from src.sales_materiality_contracts import read_assessment
    from tests.test_assessment_worker import post_material_sales_coverage

    baseline, _ = prepare_engine_plan(client, database_url, monkeypatch)
    run_id, _, _ = post_material_sales_coverage(client, database_url, baseline["id"])
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            assert planning.claim_run(session).id == run_id
            ensure_claimed_sales_materiality(session, run_id)
            stored = read_assessment(session, run_id)
            forecast = stored.engine_request.model_dump(mode="json")["issued_forecast"]
        response = client.get(f"/api/v1/manager/runs/{run_id}/sales-materiality")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "engine_request" not in body
        assert body["issued_forecast"]["forecast"] == forecast
        assert body["issued_forecast"]["request_sha256"] == stored.request_sha256
        assert body["issued_forecast"]["plan_reference"] == stored.engine_request.plan_reference
        assert body["issued_forecast"]["dish_names"]
        assert body["issued_forecast"]["limitations"]
        assert body["result"]["complete"] is True
        assert body["result"]["projection"] is not None
    finally:
        engine.dispose()


def test_manager_reads_exact_stored_outputs_and_historical_results(client, database_url, monkeypatch):
    run, _ = prepare_engine_plan(client, database_url, monkeypatch)
    path = f"/api/v1/manager/runs/{run['id']}/calculation-results"
    response = client.get(path)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["status"] == "AVAILABLE"
    assert view["stale"] is False
    assert view["plan_version_id"] == run["plan_version_id"]
    outputs = view["artifact"]["outputs"]
    assert outputs["forecast"]["buckets"]
    assert outputs["dishes"]
    assert outputs["existing_commitments_projection"]["complete"] is True
    assert outputs["with_recommendation_projection"]["complete"] is True
    assert outputs["proposed_supply_ids"]
    for bucket in outputs["forecast"]["buckets"]:
        assert all(isinstance(q, str) and Decimal(q) >= 0 for q in bucket["expected_portions"].values())
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            persisted = planning.get_run(session, run["id"]).snapshot[SNAPSHOT_KEY]
            assert persisted == view["artifact"]
            session.execute(update(db.menu_items).values(name="Changed after calculation"))
            session.commit()
        # Historical output is not enriched with mutable menu names on read.
        assert client.get(path).json()["artifact"] == persisted
        changed = client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={"effective_at": "2026-02-16T08:00:00+08:00", "current_status": "UNAVAILABLE"},
        )
        assert changed.status_code == 200, changed.text
        historical = client.get(path).json()
        assert historical["stale"] is True
        assert historical["artifact"] == persisted
        with Session(engine) as session:
            stored_run = planning.get_run(session, run["id"])
            corrupted = dict(stored_run.snapshot)
            corrupted[SNAPSHOT_KEY]["content_sha256"] = "tampered"
            session.execute(update(db.planning_runs).where(db.planning_runs.c.id == run["id"]).values(snapshot=corrupted))
            session.commit()
        assert client.get(path).status_code == 409
    finally:
        engine.dispose()


def test_unrecorded_is_distinct_from_empty_and_manager_auth_required(client):
    run = queue_manager_assessment(client)
    path = f"/api/v1/manager/runs/{run['id']}/calculation-results"
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "NOT_RECORDED"
    assert response.json()["artifact"] is None
    client.cookies.clear()
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer test-agent-token"}).status_code == 403

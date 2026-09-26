import pytest
from pydantic import TypeAdapter

from src.multiday_projection import MultiDayProjection
from tests.test_post_purchase_contingency import (
    ISSUE,
    RECEIPT,
    forbid_model_construction,
    prepare_first_case,
    queue_worker_run,
    run_worker,
)


@pytest.mark.parametrize("shortfall", [False, True])
def test_manager_contingency_projection_matches_selected_persisted_result(
    client, database_url, monkeypatch, shortfall
):
    prepare_first_case(client, database_url)
    deliveries = client.get("/api/v1/deliveries").json()
    if shortfall:
        emergency = next(row for row in deliveries if row["kind"] == "EMERGENCY")
        updated = client.post(
            f"/api/v1/deliveries/{emergency['id']}/update",
            json={"expected_quantity": "2", "expected_at": RECEIPT,
                  "expected_expiry_date": "2026-02-17", "effective_at": ISSUE},
        )
        assert updated.status_code == 200, updated.text
    run_id = queue_worker_run(client)
    path = f"/api/v1/manager/runs/{run_id}/contingency-projection"
    assert client.get(path).json() is None
    forbid_model_construction(monkeypatch)
    result = run_worker(database_url)
    assert result.publication_status == "PUBLISHED"
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    stored = client.get(f"/api/v1/runs/{run_id}").json()["snapshot"]["post_purchase_contingency_result"]
    assert body["result_reference"] == stored["id"]
    assert body["fixed_delivery_ids"] == stored["fixed_delivery_ids"]
    projection = TypeAdapter(MultiDayProjection)
    assert projection.validate_python(body["existing_commitments_projection"]) == projection.validate_python(stored["numerical_result"]["no_purchase"]["projection"])
    if shortfall:
        assert body["outcome"] == "REVISE_PLAN"
        assert projection.validate_python(body["with_recommendation_projection"]) == projection.validate_python(stored["independent_validation"]["projection"])
        assert body["candidate_reference"] == stored["candidate_reference"]
        assert body["plan_version_id"] == result.publication_reference
    else:
        assert body["outcome"] == "KEEP_CURRENT_PLAN"
        assert body["with_recommendation_projection"] is None
        assert body["candidate_reference"] is None
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.get(path).status_code == 403

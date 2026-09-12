import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "start,final,status,difference",
    [
        ("00:00", 10, "MATCHED", 0),
        ("00:00", 12, "RECONCILIATION_DISCREPANCY", 2),
        ("10:00", 12, "INCOMPLETE_COVERAGE", None),
    ],
)
def test_daily_submission_preserves_comparison_without_deducting_counts(
    client: TestClient, start: str, final: int, status: str, difference: int | None
) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )
    batch = {
        "source": "simulator",
        "batch_id": "closing",
        "period_start": f"2026-02-16T{start}:00+08:00",
        "period_end": "2026-02-16T22:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    accepted = client.post("/api/v1/sales-batches", json=batch)
    assert accepted.status_code == 201, accepted.text
    assert (
        client.post("/api/v1/sales-batches", json=batch).json()["id"]
        == accepted.json()["id"]
    )
    dishes = {dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()}
    dishes["chicken-rice"] = final
    counts = {lot["id"]: "3" for lot in client.get("/api/v1/inventory").json()}
    path = "/api/v1/daily-updates/2026-02-16"
    assert (
        client.post(
            path + "/draft",
            json={"cutoff": batch["period_end"], "sales": dishes, "counts": counts},
        ).status_code
        == 200
    )
    submitted = client.post(path + "/submit")
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()["reconciliation"]
    assert result["status"] == status
    chicken = next(
        row for row in result["dishes"] if row["menu_item_id"] == "chicken-rice"
    )
    assert chicken["difference"] == difference
    assert chicken["batch_total"] == 10
    assert len(result["batch_ids"]) == 1
    assert all(
        lot["quantity"] == "3.000" for lot in client.get("/api/v1/inventory").json()
    )
    assert client.get(path).json()["revisions"][0]["reconciliation"] == result
    if status == "MATCHED":
        corrected = client.post(
            "/api/v1/sales-batches",
            json={
                **batch,
                "replaces_id": accepted.json()["id"],
                "sales": {"chicken-rice": 8},
            },
        )
        assert corrected.status_code == 201, corrected.text
        dishes["chicken-rice"] = 8
        assert (
            client.post(
                path + "/draft",
                json={"cutoff": batch["period_end"], "sales": dishes, "counts": counts},
            ).status_code
            == 200
        )
        revised = client.post(path + "/submit")
        assert revised.status_code == 200, revised.text
        assert revised.json()["reconciliation"]["status"] == "MATCHED"
        client.headers["Authorization"] = "Bearer test-agent-token"
        run = client.post("/api/v1/runs/claim")
        assert run.status_code == 200, run.text
        history = run.json()["snapshot"]["authoritative_daily_sales"]
        assert len(history) == 1
        assert history[0]["sales"]["chicken-rice"] == 8

from fastapi.testclient import TestClient


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def test_sales_batch_updates_an_estimate_without_mutating_physical_counts(
    client: TestClient,
) -> None:
    sign_in(client)
    body = {
        "source": "simulator",
        "batch_id": "morning-001",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    accepted = client.post("/api/v1/sales-batches", json=body)
    assert accepted.status_code == 201, accepted.text
    assert (
        client.post("/api/v1/sales-batches", json=body).json()["id"]
        == accepted.json()["id"]
    )
    estimate = client.get(
        "/api/v1/inventory/estimated", params={"as_of": body["period_end"]}
    )
    assert estimate.status_code == 200, estimate.text
    chicken = {
        lot["id"]: lot for lot in estimate.json() if lot["ingredient_id"] == "chicken"
    }
    assert chicken["chicken-01"]["quantity"] == "10.500"
    assert chicken["chicken-02"]["quantity"] == "5.000"
    assert chicken["chicken-01"]["provenance"] == "ESTIMATED"
    assert chicken["chicken-01"]["coverage_complete"] is True
    physical = {lot["id"]: lot for lot in client.get("/api/v1/inventory").json()}
    assert physical["chicken-01"]["quantity"] == "12.000"


def test_sales_correction_replaces_an_interval_and_overlaps_are_rejected(
    client: TestClient,
) -> None:
    sign_in(client)
    first = {
        "source": "simulator",
        "batch_id": "one",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    original = client.post("/api/v1/sales-batches", json=first).json()
    overlapping = {
        **first,
        "batch_id": "overlap",
        "period_start": "2026-02-16T00:00:00+08:00",
    }
    assert client.post("/api/v1/sales-batches", json=overlapping).status_code == 409
    correction = {
        **first,
        "batch_id": "one-corrected",
        "sales": {"chicken-rice": 4},
        "replaces_id": original["id"],
    }
    corrected = client.post("/api/v1/sales-batches", json=correction)
    assert corrected.status_code == 201
    assert (
        client.post("/api/v1/sales-batches", json=correction).json()["id"]
        == corrected.json()["id"]
    )
    estimate = client.get(
        "/api/v1/inventory/estimated", params={"as_of": first["period_end"]}
    ).json()
    chicken = next(lot for lot in estimate if lot["id"] == "chicken-01")
    assert chicken["quantity"] == "11.400"


def test_estimate_marks_a_gap_in_sales_coverage_incomplete(client: TestClient) -> None:
    sign_in(client)
    assert (
        client.post(
            "/api/v1/sales-batches",
            json={
                "source": "simulator",
                "batch_id": "after-gap",
                "period_start": "2026-02-16T02:00:00+08:00",
                "period_end": "2026-02-16T03:00:00+08:00",
                "sales": {},
            },
        ).status_code
        == 201
    )
    response = client.get(
        "/api/v1/inventory/estimated",
        params={"as_of": "2026-02-16T03:00:00+08:00"},
    )
    assert response.status_code == 200
    assert response.json()[0]["coverage_complete"] is False

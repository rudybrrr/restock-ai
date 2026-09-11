import pytest
from fastapi.testclient import TestClient

from src.main import app


def test_inventory_requires_credentials() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/inventory")
    assert response.status_code == 401
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_manager_signs_in_and_reads_seeded_inventory(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "manager",
            "password": "test-manager-password",
        },
        headers={"Origin": "https://frontend.example"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    response = client.get("/api/v1/inventory")
    assert response.status_code == 200
    lots = response.json()
    assert len(lots) == 9
    chicken = [lot for lot in lots if lot["ingredient_id"] == "chicken"]
    assert len(chicken) == 2
    assert chicken[0]["quantity"] == "12.000"
    assert chicken[0]["provenance"] == "PHYSICAL"
    assert chicken[0]["counted_at"] == "2026-02-15T22:00:00+08:00"
    assert chicken[0]["expiry_date"] != chicken[1]["expiry_date"]


def test_agent_can_read_catalog_but_cannot_logout_a_manager(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.get("/api/v1/auth/me").json()["role"] == "agent"
    for path, count in [
        ("menu-items", 5),
        ("ingredients", 8),
        ("suppliers", 3),
        ("recipes", 16),
        ("supplier-offers", 24),
        ("holidays", 2),
        ("inventory", 9),
    ]:
        response = client.get("/api/v1/" + path)
        assert response.status_code == 200
        assert len(response.json()) == count
    offer = client.get("/api/v1/supplier-offers").json()[0]
    assert offer["unit_price"] == "4.50"
    assert offer["currency"] == "SGD"
    assert offer["order_cutoff"]["kind"] == "LOCAL_TIME"
    assert offer["feasible_delivery_at"] == ["2026-02-16T08:00:00+08:00"]
    denied = client.post(
        "/api/v1/auth/logout", headers={"Origin": "https://frontend.example"}
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "MANAGER_REQUIRED"


@pytest.mark.parametrize("password", ["wrong", "test-agent-token", ""])
def test_wrong_or_agent_credentials_cannot_sign_in_as_manager(
    client: TestClient, password: str
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": password},
        headers={"Origin": "https://frontend.example"},
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_logout_revokes_session_and_rejects_cross_origin_mutations(
    client: TestClient,
) -> None:
    origin = {"Origin": "https://frontend.example"}
    credentials = {"username": "manager", "password": "test-manager-password"}
    for headers in [{}, {"Origin": "https://untrusted.example"}]:
        assert (
            client.post(
                "/api/v1/auth/login", json=credentials, headers=headers
            ).status_code
            == 403
        )
    assert (
        client.post("/api/v1/auth/login", json=credentials, headers=origin).status_code
        == 200
    )
    token = client.cookies.get("restock_session")
    assert (
        client.post(
            "/api/v1/auth/logout", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/inventory").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=origin).status_code == 204
    assert client.get("/api/v1/inventory").status_code == 401
    assert (
        client.get(
            "/api/v1/inventory", headers={"Cookie": f"restock_session={token}"}
        ).status_code
        == 401
    )


def test_cors_and_validation_contract(client: TestClient) -> None:
    for origin, allowed in [
        ("https://frontend.example", True),
        ("https://untrusted.example", False),
    ]:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert (
            response.headers.get("access-control-allow-origin") == origin
        ) is allowed
        if allowed:
            assert response.headers["access-control-allow-credentials"] == "true"
    response = client.post(
        "/api/v1/auth/login", json={}, headers={"Origin": "https://frontend.example"}
    )
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert (
        client.get(
            "/api/v1/inventory", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/inventory",
            headers={"Authorization": "Bearer test-manager-password"},
        ).status_code
        == 401
    )

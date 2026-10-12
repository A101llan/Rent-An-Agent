import pytest
from httpx import AsyncClient

from tests.conftest import error_body


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    register = await client.post("/api/v1/auth/register", json={
        "email": "test@example.com",
        "password": "TestPass123!",
        "role": "customer",
        "display_name": "Test User",
    })
    assert register.status_code == 201
    data = register.json()
    assert data["user"]["email"] == "test@example.com"
    assert "access_token" in data["tokens"]

    login = await client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "TestPass123!",
    })
    assert login.status_code == 200
    token = login.json()["tokens"]["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_login(client: AsyncClient):
    response = await client.post("/api/v1/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "wrong",
    })
    assert response.status_code == 401
    assert error_body(response)["code"] == "INVALID_CREDENTIALS"

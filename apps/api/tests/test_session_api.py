"""Tests for renter API: session tokens and hire endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_hire_agent_returns_session_token(client: AsyncClient, seed_data):
    token = seed_data["cust_a_token"]
    resp = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "hire_api_1"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["session_token"]
    assert data["session"]["id"]
    assert data["integration"]["auth"]["header"] == "X-Session-Token"
    assert "execute" in data["integration"]["endpoints"]


@pytest.mark.asyncio
async def test_execute_with_session_token_no_jwt(client: AsyncClient, seed_data):
    user_token = seed_data["cust_a_token"]
    hire_resp = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "hire_token_1"},
    )
    session_id = hire_resp.json()["session"]["id"]
    session_token = hire_resp.json()["session_token"]

    exec_resp = await client.post(
        f"/api/v1/sessions/{session_id}/execute",
        json={"input": "Analyze invoice #1001", "context": {"source": "erp"}},
        headers={"X-Session-Token": session_token},
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_session_token_rejected(client: AsyncClient, seed_data):
    user_token = seed_data["cust_a_token"]
    hire_resp = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "hire_bad_token_1"},
    )
    session_id = hire_resp.json()["session"]["id"]

    resp = await client.post(
        f"/api/v1/sessions/{session_id}/execute",
        json={"input": "test"},
        headers={"X-Session-Token": "invalid-token-value"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION_TOKEN"


@pytest.mark.asyncio
async def test_session_token_wrong_session_rejected(client: AsyncClient, seed_data):
    user_token = seed_data["cust_a_token"]
    hire_a = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "hire_cross_1"},
    )
    hire_b = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "hire_cross_2"},
    )
    session_a = hire_a.json()["session"]["id"]
    token_b = hire_b.json()["session_token"]

    resp = await client.post(
        f"/api/v1/sessions/{session_a}/execute",
        json={"input": "test"},
        headers={"X-Session-Token": token_b},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_integration_endpoint(client: AsyncClient, seed_data):
    user_token = seed_data["cust_a_token"]
    hire_resp = await client.post(
        "/api/v1/rentals/hire",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "hire_integration_1"},
    )
    session_id = hire_resp.json()["session"]["id"]
    session_token = hire_resp.json()["session_token"]

    resp = await client.get(
        f"/api/v1/sessions/{session_id}/integration",
        headers={"X-Session-Token": session_token},
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session_id
    assert "examples" in resp.json()

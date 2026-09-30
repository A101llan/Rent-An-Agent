"""Critical security and lifecycle tests."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import RentalSession, SessionStatus
from tests.conftest import error_body


@pytest.mark.asyncio
async def test_cross_tenant_session_access_rejected(client: AsyncClient, seed_data, db_session):
    """Customer B must not access Customer A's session."""
    token_a = seed_data["cust_a_token"]
    token_b = seed_data["cust_b_token"]

    rental_resp = await client.post(
        "/api/v1/rentals",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": "rental_a_1"},
    )
    assert rental_resp.status_code == 201
    rental_id = rental_resp.json()["id"]

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"rental_id": rental_id},
        headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": "session_a_1"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    # Customer B tries to access Customer A's session
    access_resp = await client.get(
        f"/api/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert access_resp.status_code == 403


@pytest.mark.asyncio
async def test_expired_session_execution_rejected(client: AsyncClient, seed_data, db_session):
    """Expired session must reject execution with 410."""
    token = seed_data["cust_a_token"]

    rental_resp = await client.post(
        "/api/v1/rentals",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rental_exp_1"},
    )
    rental_id = rental_resp.json()["id"]

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"rental_id": rental_id},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "session_exp_1"},
    )
    session_id = session_resp.json()["id"]

    # Force expire session in DB
    result = await db_session.execute(select(RentalSession).where(RentalSession.id == session_id))
    session = result.scalar_one()
    session.status = SessionStatus.EXPIRED
    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    exec_resp = await client.post(
        f"/api/v1/sessions/{session_id}/execute",
        json={"input": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exec_resp.status_code == 410
    assert error_body(exec_resp)["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_unauthenticated_execute_rejected(client: AsyncClient):
    """Unauthenticated users cannot execute agents."""
    resp = await client.post(
        "/api/v1/sessions/00000000-0000-0000-0000-000000000001/execute",
        json={"input": "x"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_full_lifecycle(client: AsyncClient, seed_data, db_session):
    """Create Rental → Session → Execute → Expire → Reject."""
    token = seed_data["cust_a_token"]

    rental_resp = await client.post(
        "/api/v1/rentals",
        json={
            "agent_slug": seed_data["agent_slug"],
            "pricing_plan_id": seed_data["plan_id"],
            "duration_minutes": 30,
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "lifecycle_rental_1"},
    )
    assert rental_resp.status_code == 201
    rental = rental_resp.json()

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"rental_id": rental["id"]},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "lifecycle_session_1"},
    )
    assert session_resp.status_code == 201
    session = session_resp.json()
    assert session["runtime_status"] == "running"

    exec_resp = await client.post(
        f"/api/v1/sessions/{session['id']}/execute",
        json={"input": "Analyze this invoice"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    # Expire session
    result = await db_session.execute(select(RentalSession).where(RentalSession.id == session["id"]))
    db_session_obj = result.scalar_one()
    db_session_obj.status = SessionStatus.EXPIRED
    db_session_obj.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    # Subsequent execution rejected
    reject_resp = await client.post(
        f"/api/v1/sessions/{session['id']}/execute",
        json={"input": "should fail"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reject_resp.status_code == 410

"""Test human approval workflow."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import ApprovalRequest, ApprovalStatus, AgentExecution, ExecutionStatus


@pytest.mark.asyncio
async def test_high_risk_action_requires_approval(client: AsyncClient, seed_data, db_session):
    token = seed_data["cust_a_token"]

    rental = await client.post(
        "/api/v1/rentals",
        json={"agent_slug": seed_data["agent_slug"], "pricing_plan_id": seed_data["plan_id"], "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "approval_rental_1"},
    )
    rental_id = rental.json()["id"]

    session = await client.post(
        "/api/v1/sessions",
        json={"rental_id": rental_id},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "approval_session_1"},
    )
    session_id = session.json()["id"]

    exec_resp = await client.post(
        f"/api/v1/sessions/{session_id}/execute",
        json={"input": "Please send email to supplier@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exec_resp.status_code == 200
    data = exec_resp.json()
    assert data["status"] == "waiting_for_approval"
    assert data["approval_id"] is not None

    approvals = await client.get(
        f"/api/v1/sessions/{session_id}/approvals",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approvals.status_code == 200
    assert len(approvals.json()) >= 1

    approval_id = data["approval_id"]
    resolve = await client.post(
        f"/api/v1/sessions/{session_id}/approvals/{approval_id}/resolve",
        json={"approved": True, "scope": "once"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "approved"

    result = await db_session.execute(
        select(AgentExecution).where(AgentExecution.id == data["execution_id"])
    )
    execution = result.scalar_one()
    assert execution.status == ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_deny_approval_cancels_execution(client: AsyncClient, seed_data, db_session):
    token = seed_data["cust_a_token"]

    rental = await client.post(
        "/api/v1/rentals",
        json={"agent_slug": seed_data["agent_slug"], "pricing_plan_id": seed_data["plan_id"], "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "deny_rental_1"},
    )
    session = await client.post(
        "/api/v1/sessions",
        json={"rental_id": rental.json()["id"]},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "deny_session_1"},
    )
    session_id = session.json()["id"]

    exec_resp = await client.post(
        f"/api/v1/sessions/{session_id}/execute",
        json={"input": "execute payment for invoice"},
        headers={"Authorization": f"Bearer {token}"},
    )
    approval_id = exec_resp.json()["approval_id"]

    deny = await client.post(
        f"/api/v1/sessions/{session_id}/approvals/{approval_id}/resolve",
        json={"approved": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deny.status_code == 200
    assert deny.json()["status"] == "denied"

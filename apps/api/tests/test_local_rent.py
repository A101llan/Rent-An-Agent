"""Local-rent MVP (cloud half): hire entitlement, sidecar claim/usage, execute guard.

The local agent fixture is built here (not via seed data) with a manifest whose
runtime.type == "local" and no image/digest, so it doesn't depend on the schema
relaxation owned by the Local Manifest Seeder.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import (
    Agent,
    AgentPricingPlan,
    AgentStatus,
    AgentVersion,
    PricingModel,
    RentalSession,
    RuntimeInstance,
    SessionStatus,
    UsageRecord,
    VersionStatus,
)
from app.services import rental as rental_service

LOCAL_MANIFEST = {
    "name": "Meeting Notes (local test)",
    "version": "0.1.0",
    "runtime": {"type": "local"},
    "io": {
        "output": {"summary": "str", "decisions": [], "action_items": [{"owner": "str", "task": "str"}],
                   "open_questions": []},
    },
}


@pytest_asyncio.fixture
async def local_agent(db_session, seed_data):
    server_agent = (await db_session.execute(select(Agent).where(Agent.slug == seed_data["agent_slug"]))).scalar_one()
    agent = Agent(
        developer_id=server_agent.developer_id, slug="local-notes-test", name="Local Notes Test",
        description="Local runtime test agent", category="productivity",
        status=AgentStatus.PUBLISHED, is_verified=True, published_at=datetime.now(UTC),
    )
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(agent_id=agent.id, version="0.1.0", manifest=LOCAL_MANIFEST, status=VersionStatus.VERIFIED)
    db_session.add(version)
    await db_session.flush()
    plan = AgentPricingPlan(
        agent_version_id=version.id, name="Local", pricing_model=PricingModel.PER_HOUR,
        price_minor=100, currency="USD", duration_minutes=30,
    )
    db_session.add(plan)
    await db_session.commit()
    return {**seed_data, "local_slug": agent.slug, "local_plan_id": str(plan.id)}


def _err(resp):
    """Error envelope: canonical {"error": {...}} from apps/api global handlers."""
    body = resp.json()
    assert "error" in body, body
    return body["error"]


class _NoNetworkHttpx:
    """Stand-in for the httpx module inside the rental service: any client creation is recorded."""

    def __init__(self):
        self.calls = 0
        outer = self

        class _Client:
            def __init__(self, *a, **kw):
                outer.calls += 1
                raise AssertionError("runtime-manager must not be called for local sessions")

        self.AsyncClient = _Client


@pytest.fixture
def rm_spy(monkeypatch):
    """Spy on _provision_runtime and block runtime-manager HTTP from the rental service."""
    state = {"provision_calls": 0}
    original = rental_service._provision_runtime

    async def spy(*args, **kwargs):
        state["provision_calls"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(rental_service, "_provision_runtime", spy)
    return state


async def _hire(client, token, slug, plan_id, key):
    resp = await client.post(
        "/api/v1/rentals/hire",
        json={"agent_slug": slug, "pricing_plan_id": plan_id, "duration_minutes": 30},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _hire_local(client, data, key):
    return await _hire(client, data["cust_a_token"], data["local_slug"], data["local_plan_id"], key)


async def _expire(db_session, session_id, *, status=SessionStatus.EXPIRED):
    s = (await db_session.execute(select(RentalSession).where(RentalSession.id == session_id))).scalar_one()
    s.status = status
    s.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()


# ------------------------------------------------------------------------------------ hire


@pytest.mark.asyncio
async def test_local_hire_skips_runtime_manager(client: AsyncClient, local_agent, db_session, rm_spy, monkeypatch):
    fake = _NoNetworkHttpx()
    monkeypatch.setattr(rental_service, "httpx", fake)

    data = await _hire_local(client, local_agent, "local_hire_1")

    assert rm_spy["provision_calls"] == 0
    assert fake.calls == 0
    assert data["session"]["runtime_provider"] == "local"
    assert data["runtime_provider"] == "local"
    assert data["session"]["session_token"] and data["session"]["session_token"] == data["session_token"]
    assert data["session"]["status"] == "active"
    assert data["session"]["runtime_status"] == "provisioning"
    assert data["local"]["session_id"] == data["session"]["id"]
    assert data["local"]["claim_endpoint"].endswith(f"/api/v1/sessions/{data['session']['id']}/local/claim")
    assert data["local"]["usage_endpoint"].endswith(f"/api/v1/sessions/{data['session']['id']}/usage")
    assert data["local"]["auth_header"] == "X-Session-Token"
    # billing-on-hire unchanged: rental is charged for the plan
    assert data["rental"]["total_cost_minor"] == 50
    assert data["rental"]["status"] == "active"

    runtime = (await db_session.execute(
        select(RuntimeInstance).where(RuntimeInstance.session_id == data["session"]["id"])
    )).scalar_one()
    assert runtime.runtime_provider == "local"
    assert runtime.runtime_identifier is None


@pytest.mark.asyncio
async def test_local_create_session_endpoint_also_skips_runtime_manager(
    client: AsyncClient, local_agent, rm_spy, monkeypatch
):
    fake = _NoNetworkHttpx()
    monkeypatch.setattr(rental_service, "httpx", fake)
    token = local_agent["cust_a_token"]
    rental = await client.post(
        "/api/v1/rentals",
        json={"agent_slug": local_agent["local_slug"], "pricing_plan_id": local_agent["local_plan_id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rental.status_code == 201
    resp = await client.post(
        "/api/v1/sessions", json={"rental_id": rental.json()["id"]}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201
    assert resp.json()["runtime_provider"] == "local"
    assert rm_spy["provision_calls"] == 0 and fake.calls == 0


@pytest.mark.asyncio
async def test_server_hire_path_unchanged(client: AsyncClient, local_agent, db_session, rm_spy):
    data = await _hire(client, local_agent["cust_a_token"], local_agent["agent_slug"], local_agent["plan_id"], "srv_1")
    assert rm_spy["provision_calls"] == 1
    assert data["session"]["runtime_status"] == "running"
    assert data["session"]["runtime_provider"] == "mock"
    assert data["runtime_provider"] == "mock"
    assert data["local"] is None
    assert "execute" in data["integration"]["endpoints"]
    runtime = (await db_session.execute(
        select(RuntimeInstance).where(RuntimeInstance.session_id == data["session"]["id"])
    )).scalar_one()
    assert runtime.runtime_provider == "mock"


# ------------------------------------------------------------------------------------ claim


@pytest.mark.asyncio
async def test_claim_with_session_token(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "claim_tok_1")
    sid = data["session"]["id"]
    resp = await client.post(f"/api/v1/sessions/{sid}/local/claim", headers={"X-Session-Token": data["session_token"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == sid
    assert body["manifest"]["runtime"]["type"] == "local"
    assert body["agent_slug"] == local_agent["local_slug"]
    assert body["agent_version"] == "0.1.0"
    assert body["runtime_provider"] == "local"
    # expiry NOT extended by claim
    assert datetime.fromisoformat(body["expires_at"]) == datetime.fromisoformat(data["session"]["expires_at"])
    runtime = (await db_session.execute(
        select(RuntimeInstance).where(RuntimeInstance.session_id == sid)
    )).scalar_one()
    assert runtime.status.value == "running"
    # re-claim (sidecar restart) is idempotent
    again = await client.post(f"/api/v1/sessions/{sid}/local/claim", headers={"X-Session-Token": data["session_token"]})
    assert again.status_code == 200
    assert again.json()["expires_at"] == body["expires_at"]


@pytest.mark.asyncio
async def test_claim_with_owner_jwt(client: AsyncClient, local_agent):
    data = await _hire_local(client, local_agent, "claim_jwt_1")
    sid = data["session"]["id"]
    resp = await client.post(
        f"/api/v1/sessions/{sid}/local/claim", headers={"Authorization": f"Bearer {local_agent['cust_a_token']}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_id"] == sid


@pytest.mark.asyncio
async def test_claim_rejects_wrong_token(client: AsyncClient, local_agent):
    a = await _hire_local(client, local_agent, "claim_wrong_1")
    b = await _hire_local(client, local_agent, "claim_wrong_2")
    sid = a["session"]["id"]
    for bad in ("not-a-real-token", b["session_token"]):
        resp = await client.post(f"/api/v1/sessions/{sid}/local/claim", headers={"X-Session-Token": bad})
        assert resp.status_code == 401
        assert _err(resp)["code"] == "INVALID_SESSION_TOKEN"


@pytest.mark.asyncio
async def test_claim_rejects_missing_or_invalid_auth(client: AsyncClient, local_agent):
    data = await _hire_local(client, local_agent, "claim_noauth_1")
    sid = data["session"]["id"]
    assert (await client.post(f"/api/v1/sessions/{sid}/local/claim")).status_code == 401
    resp = await client.post(f"/api/v1/sessions/{sid}/local/claim", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_claim_rejects_other_users_jwt(client: AsyncClient, local_agent):
    data = await _hire_local(client, local_agent, "claim_other_1")
    resp = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/local/claim",
        headers={"Authorization": f"Bearer {local_agent['cust_b_token']}"},
    )
    assert resp.status_code == 403
    assert _err(resp)["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_claim_unknown_session_404(client: AsyncClient, local_agent):
    unknown = uuid4()
    resp = await client.post(
        f"/api/v1/sessions/{unknown}/local/claim", headers={"Authorization": f"Bearer {local_agent['cust_a_token']}"}
    )
    assert resp.status_code == 404
    assert _err(resp)["code"] == "SESSION_NOT_FOUND"
    resp = await client.post(f"/api/v1/sessions/{unknown}/local/claim", headers={"X-Session-Token": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_claim_non_local_session_409(client: AsyncClient, local_agent):
    data = await _hire(client, local_agent["cust_a_token"], local_agent["agent_slug"], local_agent["plan_id"], "nl_1")
    resp = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/local/claim", headers={"X-Session-Token": data["session_token"]}
    )
    assert resp.status_code == 409
    assert _err(resp)["code"] == "SESSION_NOT_LOCAL"


@pytest.mark.asyncio
async def test_claim_expired_session_410(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "claim_exp_1")
    await _expire(db_session, data["session"]["id"])
    resp = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/local/claim", headers={"X-Session-Token": data["session_token"]}
    )
    assert resp.status_code == 410
    assert _err(resp)["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_claim_past_expiry_but_still_active_status_410(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "claim_exp_2")
    await _expire(db_session, data["session"]["id"], status=SessionStatus.ACTIVE)
    resp = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/local/claim", headers={"X-Session-Token": data["session_token"]}
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_claim_terminated_session_410(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "claim_term_1")
    s = (await db_session.execute(select(RentalSession).where(RentalSession.id == data["session"]["id"]))).scalar_one()
    s.status = SessionStatus.TERMINATED
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/local/claim", headers={"X-Session-Token": data["session_token"]}
    )
    assert resp.status_code == 410


# ------------------------------------------------------------------------------------ usage


async def _usage_count(db_session, sid):
    return (await db_session.execute(
        select(func.count()).select_from(UsageRecord).where(UsageRecord.session_id == sid)
    )).scalar_one()


@pytest.mark.asyncio
async def test_usage_writes_usage_record(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "usage_ok_1")
    sid = data["session"]["id"]
    resp = await client.post(
        f"/api/v1/sessions/{sid}/usage",
        json={"metric_type": "documents_processed", "quantity": 2, "unit": "count"},
        headers={"X-Session-Token": data["session_token"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] and body["session_id"] == sid
    assert body["metric_type"] == "documents_processed"
    assert body["quantity"] == 2.0 and body["unit"] == "count" and body["execution_id"] is None
    assert body["recorded_at"]
    rec = (await db_session.execute(select(UsageRecord).where(UsageRecord.id == body["id"]))).scalar_one()
    assert float(rec.quantity) == 2.0

    jwt_resp = await client.post(
        f"/api/v1/sessions/{sid}/usage",
        json={"metric_type": "input_tokens", "quantity": 1234.5, "unit": "tokens"},
        headers={"Authorization": f"Bearer {local_agent['cust_a_token']}"},
    )
    assert jwt_resp.status_code == 201
    assert await _usage_count(db_session, sid) == 2


@pytest.mark.asyncio
async def test_usage_rejects_invalid_auth(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "usage_auth_1")
    sid = data["session"]["id"]
    body = {"metric_type": "documents_processed", "quantity": 1, "unit": "count"}
    assert (await client.post(f"/api/v1/sessions/{sid}/usage", json=body)).status_code == 401
    r = await client.post(f"/api/v1/sessions/{sid}/usage", json=body, headers={"X-Session-Token": "nope"})
    assert r.status_code == 401
    r = await client.post(
        f"/api/v1/sessions/{sid}/usage", json=body, headers={"Authorization": f"Bearer {local_agent['cust_b_token']}"}
    )
    assert r.status_code == 403
    r = await client.post(f"/api/v1/sessions/{uuid4()}/usage", json=body, headers={"X-Session-Token": "nope"})
    assert r.status_code == 404
    assert await _usage_count(db_session, sid) == 0


@pytest.mark.asyncio
async def test_usage_rejects_expired_session(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "usage_exp_1")
    sid = data["session"]["id"]
    await _expire(db_session, sid)
    r = await client.post(
        f"/api/v1/sessions/{sid}/usage",
        json={"metric_type": "documents_processed", "quantity": 1, "unit": "count"},
        headers={"X-Session-Token": data["session_token"]},
    )
    assert r.status_code == 410
    assert _err(r)["code"] == "SESSION_EXPIRED"
    assert await _usage_count(db_session, sid) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"metric_type": "documents_processed", "quantity": 0, "unit": "count"},
        {"metric_type": "documents_processed", "quantity": -3, "unit": "count"},
        {"metric_type": "documents_processed", "unit": "count"},
        {"metric_type": "documents_processed", "quantity": 1, "unit": "count", "content": "secret meeting text"},
        {"metric_type": "has spaces and prose", "quantity": 1, "unit": "count"},
    ],
)
async def test_usage_rejects_invalid_body(client: AsyncClient, local_agent, db_session, payload):
    data = await _hire_local(client, local_agent, f"usage_bad_{uuid4().hex[:8]}")
    sid = data["session"]["id"]
    r = await client.post(f"/api/v1/sessions/{sid}/usage", json=payload, headers={"X-Session-Token": data["session_token"]})
    assert r.status_code == 422
    err = _err(r)
    assert err["code"] == "VALIDATION_ERROR"
    assert err["message"]
    assert await _usage_count(db_session, sid) == 0


@pytest.mark.asyncio
async def test_usage_rejects_non_local_session(client: AsyncClient, local_agent):
    data = await _hire(client, local_agent["cust_a_token"], local_agent["agent_slug"], local_agent["plan_id"], "nl_u1")
    r = await client.post(
        f"/api/v1/sessions/{data['session']['id']}/usage",
        json={"metric_type": "requests", "quantity": 1, "unit": "count"},
        headers={"X-Session-Token": data["session_token"]},
    )
    assert r.status_code == 409
    assert _err(r)["code"] == "SESSION_NOT_LOCAL"


@pytest.mark.asyncio
async def test_usage_rejects_foreign_execution_id(client: AsyncClient, local_agent, db_session):
    data = await _hire_local(client, local_agent, "usage_exec_1")
    sid = data["session"]["id"]
    r = await client.post(
        f"/api/v1/sessions/{sid}/usage",
        json={"metric_type": "requests", "quantity": 1, "unit": "count", "execution_id": str(uuid4())},
        headers={"X-Session-Token": data["session_token"]},
    )
    assert r.status_code == 400
    assert _err(r)["code"] == "INVALID_EXECUTION"
    assert await _usage_count(db_session, sid) == 0


# ------------------------------------------------------------------------------------ execute


@pytest.mark.asyncio
async def test_execute_on_local_session_returns_runtime_local(client: AsyncClient, local_agent, monkeypatch):
    fake = _NoNetworkHttpx()
    monkeypatch.setattr(rental_service, "httpx", fake)
    data = await _hire_local(client, local_agent, "exec_local_1")
    sid = data["session"]["id"]
    for headers in (
        {"X-Session-Token": data["session_token"]},
        {"Authorization": f"Bearer {local_agent['cust_a_token']}"},
    ):
        r = await client.post(f"/api/v1/sessions/{sid}/execute", json={"input": "summarize"}, headers=headers)
        assert r.status_code == 400
        err = _err(r)
        assert err["code"] == "RUNTIME_LOCAL"
        assert err["message"]
        assert "request_id" in err
    assert fake.calls == 0

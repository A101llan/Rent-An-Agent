"""
E2E helper: Hire the seeded customer-support-agent, complete onboarding,
and print the embed key for pasting into the Chrome extension popup.

Credentials (from seed.py):
  customer: customer@agenthub.dev / Customer123!
"""
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

BASE = "http://test"

async def run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:

        # ── 1. Login as customer ─────────────────────────────────────────────
        print("\n[1/6] Logging in as customer@agenthub.dev...")
        r = await c.post("/api/v1/auth/login", json={
            "email": "customer@agenthub.dev",
            "password": "Customer123!"
        })
        assert r.status_code == 200, f"Login failed ({r.status_code}): {r.text}"
        cust_token = r.json()["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {cust_token}"}
        print("  OK")

        # ── 2. Fetch agent detail to get pricing_plan_id ─────────────────────
        print("\n[2/6] Fetching customer-support-agent details...")
        r = await c.get("/api/v1/agents/customer-support-agent")
        assert r.status_code == 200, f"Agent fetch failed ({r.status_code}): {r.text}"
        agent_data = r.json()["agent"]
        plans = agent_data.get("pricing_plans", [])
        assert plans, "No pricing plans found"
        plan_id = plans[0]["id"]
        print(f"  Agent : {agent_data['name']}")
        print(f"  Plan  : {plans[0]['name']} (id={plan_id})")

        # ── 3. Hire the agent ─────────────────────────────────────────────────
        print("\n[3/6] Hiring customer-support-agent...")
        r = await c.post("/api/v1/rentals/hire", headers=headers, json={
            "agent_slug": "customer-support-agent",
            "pricing_plan_id": plan_id,
            "duration_minutes": 60
        })
        assert r.status_code in (200, 201), f"Hire failed ({r.status_code}): {r.text}"
        hire_data = r.json()
        embed_key = hire_data["embed"]["api_key"]
        print(f"  Hired : {hire_data['session']['agent_name']}")
        embed_headers = {"Authorization": f"Bearer {embed_key}"}

        # ── 4. Bootstrap to see onboarding questions ──────────────────────────
        print("\n[4/6] Bootstrapping session...")
        r = await c.get("/api/v1/embed/bootstrap", headers=embed_headers)
        assert r.status_code == 200, f"Bootstrap error ({r.status_code}): {r.text}"
        boot = r.json()
        print(f"  Agent            : {boot.get('agent_name')}")
        print(f"  Onboarding done  : {boot.get('onboarding_complete')}")
        print(f"  Questions        : {[q['id'] for q in boot.get('questions', [])]}")

        # ── 5. Submit onboarding answers ──────────────────────────────────────
        if not boot.get("onboarding_complete"):
            print("\n[5/6] Submitting onboarding answers...")
            sample_answers = {q["id"]: f"Sample answer for {q['id']}" for q in boot["questions"]}
            r = await c.post("/api/v1/embed/onboarding",
                             headers={**embed_headers, "Content-Type": "application/json"},
                             json={"answers": sample_answers})
            assert r.status_code == 200, f"Onboarding error ({r.status_code}): {r.text}"
            ob = r.json()
            print(f"  Onboarding complete: {ob.get('onboarding_complete')}")
            print(f"  Welcome message   : {ob.get('welcome_message','')[:80]}...")
        else:
            print("\n[5/6] Onboarding already complete, skipping.")

        # ── 6. Test a real chat message ───────────────────────────────────────
        print("\n[6/6] Sending a test chat message...")
        r = await c.post("/api/v1/embed/chat",
                         headers={**embed_headers, "Content-Type": "application/json"},
                         json={"message": "Hello! What can you help me with?", "context": {}})
        if r.status_code == 200:
            reply = r.json().get("reply", "(no reply field)")
            print(f"  Agent replied: {reply[:120]}")
        else:
            print(f"  Chat response ({r.status_code}): {r.text}")

        print()
        print("=" * 68)
        print("  BACKEND IS LIVE -- PASTE THIS KEY INTO THE EXTENSION POPUP:")
        print()
        print(f"  {embed_key}")
        print("=" * 68)
        print()

if __name__ == "__main__":
    asyncio.run(run())

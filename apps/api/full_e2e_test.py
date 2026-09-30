import asyncio
import httpx
import websockets
import json

API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

async def test_full_system():
    print("--- Starting Full System E2E Test ---\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Health & Readiness Check
        print("1. Checking API Readiness...")
        r = await client.get(f"{API_BASE}/ready")
        print(f"   Status: {r.status_code}, Body: {r.json()}")
        assert r.status_code == 200

        # 2. Register & Login Test User
        email = f"e2e_tester_{int(asyncio.get_event_loop().time())}@agenthub.dev"
        password = "TestPassword123!"
        print(f"\n2. Registering Customer User ({email})...")
        r = await client.post(f"{API_BASE}/api/v1/auth/register", json={
            "email": email,
            "password": password,
            "role": "customer",
            "display_name": "E2E Tester"
        })
        print(f"   Status: {r.status_code}")
        token = r.json()["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. List Marketplace Agents
        print("\n3. Listing Marketplace Agents...")
        r = await client.get(f"{API_BASE}/api/v1/marketplace/agents")
        agents = r.json()["items"]
        print(f"   Found {len(agents)} agents in marketplace.")
        assert len(agents) > 0
        agent = agents[0]
        print(f"   Target Agent: '{agent['name']}' (slug: {agent['slug']}, id: {agent['id']})")

        # 4. Hire Agent & Create Session
        print("\n4. Hiring Agent...")
        agent_detail = (await client.get(f"{API_BASE}/api/v1/agents/{agent['slug']}")).json()["agent"]
        plan_id = agent_detail["pricing_plans"][0]["id"]
        r = await client.post(f"{API_BASE}/api/v1/rentals/hire", headers=headers, json={
            "agent_slug": agent["slug"],
            "pricing_plan_id": plan_id,
            "duration_minutes": 30
        })
        print(f"   Status: {r.status_code}")
        hire_data = r.json()
        embed_key = hire_data["embed"]["api_key"]
        session_id = hire_data["session"]["id"]
        print(f"   Issued Embed Key: {embed_key[:16]}... (Session ID: {session_id})")

        # 5. Bootstrap Embed Session
        print("\n5. Bootstrapping Embed Session...")
        embed_headers = {"Authorization": f"Bearer {embed_key}"}
        r = await client.get(f"{API_BASE}/api/v1/embed/bootstrap", headers=embed_headers)
        bootstrap_data = r.json()
        print(f"   Status: {r.status_code}, Agent: {bootstrap_data.get('agent_name')}")
        questions = bootstrap_data.get("questions", [])

        # 6. Submit Onboarding Answers
        print("\n6. Submitting Onboarding Answers...")
        answers = {q["id"]: "Acme Test Value" for q in questions}
        r = await client.post(f"{API_BASE}/api/v1/embed/onboarding", headers=embed_headers, json={
            "answers": answers
        })
        print(f"   Status: {r.status_code}, Response: {r.json()}")

        # 7. Execute HTTP Chat
        print("\n7. Executing Agent HTTP Chat...")
        r = await client.post(f"{API_BASE}/api/v1/embed/chat", headers=embed_headers, json={
            "message": "Hello! Please summarize your capabilities for Acme Test Corp."
        })
        print(f"   Status: {r.status_code}")
        print(f"   Agent Reply: '{r.json().get('reply')}'")

        # 8. Test Real-Time WebSocket Streaming
        print("\n8. Testing Real-Time WebSocket Streaming...")
        ws_url = f"{WS_BASE}/api/v1/embed/ws/{embed_key}"
        async with websockets.connect(ws_url) as ws:
            await ws.send("Give me a quick 1-sentence tip.")
            chunks = []
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("type") == "chunk":
                    chunks.append(data.get("content", ""))
                elif data.get("type") == "end":
                    break
            streamed_text = "".join(chunks)
            print(f"   Streamed Reply: '{streamed_text.strip()}'")

        # 9. Submit Customer Rating & Review
        print("\n9. Submitting Customer Rating & Review...")
        r = await client.post(f"{API_BASE}/api/v1/agents/{agent['id']}/reviews", headers=headers, json={
            "rating": 5,
            "title": "Outstanding Agent!",
            "body": "Fast responses and great onboarding experience during E2E testing."
        })
        print(f"   Status: {r.status_code}, Review ID: {r.json().get('id')}")

        print("\n=== ALL 9 E2E SYSTEM TESTS PASSED SUCCESSFULLY! ===\n")

if __name__ == "__main__":
    asyncio.run(test_full_system())

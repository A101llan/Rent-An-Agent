import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import async_session_factory
from app.models import User, UserRole
from app.core.deps import get_current_user

async def test_vault_endpoints():
    print("\n--- Starting Vault API Test ---")
    
    # 1. Create a real user in the DB
    print("1. Authenticating test user...")
    async with async_session_factory() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.email == "test_vault@agenthub.dev"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email="test_vault@agenthub.dev",
                password_hash="mockhash",
                role=UserRole.DEVELOPER,
                is_active=True,
                is_verified=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
    # 2. Override the dependency
    async def override_get_current_user():
        return user
    
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 3. Test Connecting a Credential
        print(f"2. Connecting QuickBooks credential for user {user.id}...")
        response = await client.post("/api/v1/vault/connect", json={
            "provider": "quickbooks",
            "access_token": "mock_qb_access_token_123",
            "refresh_token": "mock_qb_refresh_token_456"
        })
        
        if response.status_code == 200:
            data = response.json()
            print(f"   [SUCCESS] Connected credential ID: {data['id']}")
        else:
            print(f"   [FAILED] {response.text}")
            
        # 4. Test Retrieving Credentials
        print("3. Retrieving connected credentials...")
        response = await client.get("/api/v1/vault/")
        if response.status_code == 200:
            data = response.json()
            print(f"   [SUCCESS] Found {len(data)} credential(s).")
            for cred in data:
                print(f"      - Provider: {cred['provider']}, Created: {cred['created_at']}")
        else:
            print(f"   [FAILED] {response.text}")
            
        # 5. Test Revoking Credential
        print("4. Revoking QuickBooks credential...")
        response = await client.delete("/api/v1/vault/quickbooks")
        if response.status_code == 200:
            print(f"   [SUCCESS] {response.json()['message']}")
        else:
            print(f"   [FAILED] {response.text}")

    print("--- Test Complete ---\n")

if __name__ == "__main__":
    asyncio.run(test_vault_endpoints())

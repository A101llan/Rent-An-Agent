"""
Vault Fernet Encryption — End-to-End Test

Tests:
  1. Register a customer user
  2. POST /vault/connect — store a credential (verify encrypted at rest)
  3. GET /vault/ — list credentials (verify token values are NOT returned)
  4. POST /vault/connect — upsert same provider (replace)
  5. DELETE /vault/{provider} — revoke credential
  6. Register admin user, POST /vault/rotate-key — verify rotation works
"""
import sys
import httpx
import asyncio
import asyncpg
import os

API = "http://localhost:8000"
DB_URL = "postgresql://agenthub:agenthub@localhost:5432/agenthub"

# Unique email for each test run
import time
SUFFIX = str(int(time.time()))
CUST_EMAIL = f"vaulttest_{SUFFIX}@example.com"
ADMIN_EMAIL = f"vaultadmin_{SUFFIX}@example.com"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  [PASS] {name}")
        passed += 1
    else:
        print(f"  [FAIL] {name}  -- {detail}")
        failed += 1


async def main():
    global passed, failed
    async with httpx.AsyncClient(base_url=API, timeout=15) as c:

        # ---- 1. Register customer ----
        print("\n== 1. Register customer ==")
        r = await c.post("/api/v1/auth/register", json={
            "email": CUST_EMAIL,
            "password": "VaultTest123!",
            "role": "customer",
            "display_name": "Vault Tester"
        })
        check("register customer", r.status_code == 201, f"status={r.status_code} body={r.text[:200]}")
        cust_token = r.json()["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {cust_token}"}

        # ---- 2. Store credential ----
        print("\n== 2. Store credential (POST /vault/connect) ==")
        r = await c.post("/api/v1/vault/connect", json={
            "provider": "github",
            "access_token": "ghp_SuperSecretGitHubToken123",
            "refresh_token": "ghr_RefreshToken456"
        }, headers=headers)
        check("store credential", r.status_code == 201, f"status={r.status_code} body={r.text[:300]}")
        cred_data = r.json()
        cred_id = cred_data.get("id")
        check("response has id", cred_id is not None)
        check("response has provider", cred_data.get("provider") == "github")
        # Verify token values are NOT in the response
        check("access_token NOT in response", "access_token" not in cred_data,
              f"keys={list(cred_data.keys())}")
        check("refresh_token NOT in response", "refresh_token" not in cred_data,
              f"keys={list(cred_data.keys())}")

        # ---- 2b. Verify encrypted at rest in the DB ----
        print("\n== 2b. Verify encrypted at rest (direct DB query) ==")
        conn = await asyncpg.connect(DB_URL)
        row = await conn.fetchrow(
            "SELECT access_token, refresh_token FROM vault_credentials WHERE id = $1",
            __import__("uuid").UUID(cred_id)
        )
        await conn.close()
        raw_access = row["access_token"]
        raw_refresh = row["refresh_token"]
        check("DB access_token is Fernet (starts with gAAAAA)",
              raw_access.startswith("gAAAAA"),
              f"actual prefix: {raw_access[:20]}...")
        check("DB access_token is NOT plaintext",
              raw_access != "ghp_SuperSecretGitHubToken123")
        check("DB refresh_token is Fernet (starts with gAAAAA)",
              raw_refresh.startswith("gAAAAA"),
              f"actual prefix: {raw_refresh[:20]}...")
        check("DB refresh_token is NOT plaintext",
              raw_refresh != "ghr_RefreshToken456")

        # Verify we can decrypt it with our vault_crypto module
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from app.core.vault_crypto import decrypt_token
        decrypted_access = decrypt_token(raw_access)
        decrypted_refresh = decrypt_token(raw_refresh)
        check("decrypted access_token matches original",
              decrypted_access == "ghp_SuperSecretGitHubToken123",
              f"got: {decrypted_access}")
        check("decrypted refresh_token matches original",
              decrypted_refresh == "ghr_RefreshToken456",
              f"got: {decrypted_refresh}")

        # ---- 3. List credentials ----
        print("\n== 3. List credentials (GET /vault/) ==")
        r = await c.get("/api/v1/vault/", headers=headers)
        check("list credentials", r.status_code == 200, f"status={r.status_code}")
        creds_list = r.json()
        check("one credential returned", len(creds_list) == 1, f"count={len(creds_list)}")
        check("provider is github", creds_list[0].get("provider") == "github")
        check("no access_token in list item", "access_token" not in creds_list[0])

        # ---- 4. Upsert (reconnect same provider) ----
        print("\n== 4. Upsert credential (POST /vault/connect same provider) ==")
        r = await c.post("/api/v1/vault/connect", json={
            "provider": "github",
            "access_token": "ghp_NewRefreshedToken789",
        }, headers=headers)
        check("upsert returns 201", r.status_code == 201, f"status={r.status_code}")
        upsert_data = r.json()
        check("same credential id reused", upsert_data.get("id") == cred_id,
              f"original={cred_id}, new={upsert_data.get('id')}")

        # Verify DB has the new encrypted value
        conn = await asyncpg.connect(DB_URL)
        row2 = await conn.fetchrow(
            "SELECT access_token, refresh_token FROM vault_credentials WHERE id = $1",
            __import__("uuid").UUID(cred_id)
        )
        await conn.close()
        decrypted_new = decrypt_token(row2["access_token"])
        check("upserted access_token decrypts to new value",
              decrypted_new == "ghp_NewRefreshedToken789",
              f"got: {decrypted_new}")
        check("refresh_token cleared on upsert without refresh",
              row2["refresh_token"] is None)

        # ---- 5. Delete credential ----
        print("\n== 5. Revoke credential (DELETE /vault/github) ==")
        r = await c.delete("/api/v1/vault/github", headers=headers)
        check("revoke returns 200", r.status_code == 200, f"status={r.status_code}")
        r = await c.get("/api/v1/vault/", headers=headers)
        check("no credentials remain", len(r.json()) == 0, f"count={len(r.json())}")

        # ---- 6. Admin key rotation ----
        print("\n== 6. Admin key rotation (POST /vault/rotate-key) ==")
        # First, store some credentials to rotate
        await c.post("/api/v1/vault/connect", json={
            "provider": "slack",
            "access_token": "xoxb-slack-token-abc",
        }, headers=headers)
        await c.post("/api/v1/vault/connect", json={
            "provider": "jira",
            "access_token": "jira-api-key-def",
            "refresh_token": "jira-refresh-ghi"
        }, headers=headers)

        # Register admin user
        r = await c.post("/api/v1/auth/register", json={
            "email": ADMIN_EMAIL,
            "password": "AdminPass123!",
            "role": "admin",
            "display_name": "Vault Admin"
        })
        # Might need to promote to admin manually — try the endpoint first
        if r.status_code == 201:
            admin_token = r.json()["tokens"]["access_token"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            # Promote to admin in DB
            conn = await asyncpg.connect(DB_URL)
            admin_uid = r.json()["user"]["id"]
            await conn.execute(
                "UPDATE users SET role = 'admin' WHERE id = $1",
                __import__("uuid").UUID(admin_uid)
            )
            await conn.close()

            # Re-login to get fresh token with updated role
            r = await c.post("/api/v1/auth/login", json={
                "email": ADMIN_EMAIL,
                "password": "AdminPass123!"
            })
            admin_token = r.json()["tokens"]["access_token"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            r = await c.post("/api/v1/vault/rotate-key", headers=admin_headers)
            check("rotate-key returns 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
            rotation = r.json()
            check("rotation rotated > 0", rotation.get("rotated", 0) > 0,
                  f"rotation={rotation}")
            check("rotation errors = 0", rotation.get("errors", -1) == 0,
                  f"errors={rotation.get('errors')}")
            print(f"    Rotation result: {rotation}")

        # Non-admin should be denied
        r = await c.post("/api/v1/vault/rotate-key", headers=headers)
        check("rotate-key denied for non-admin", r.status_code == 403, f"status={r.status_code}")

    # ---- Summary ----
    print(f"\n{'='*50}")
    print(f"  VAULT ENCRYPTION TEST RESULTS")
    print(f"  Passed: {passed}  |  Failed: {failed}")
    print(f"{'='*50}")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

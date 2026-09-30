#!/usr/bin/env python3
"""Example: log in, hire an agent, execute via session token (no JWT on execute)."""

import os
import sys

import httpx

API = os.environ.get("AGENTHUB_API", "http://localhost:8000")
EMAIL = os.environ.get("AGENTHUB_EMAIL", "customer@agenthub.dev")
PASSWORD = os.environ.get("AGENTHUB_PASSWORD", "Customer123!")
AGENT_SLUG = os.environ.get("AGENTHUB_AGENT", "invoice-analyzer")


def main() -> int:
    with httpx.Client(base_url=API, timeout=30) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
        )
        login.raise_for_status()
        access_token = login.json()["tokens"]["access_token"]

        agent = client.get(f"/api/v1/agents/{AGENT_SLUG}").json()["agent"]
        plan_id = agent["pricing_plans"][0]["id"]

        hire = client.post(
            "/api/v1/rentals/hire",
            json={
                "agent_slug": AGENT_SLUG,
                "pricing_plan_id": plan_id,
                "duration_minutes": 30,
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Idempotency-Key": f"example-{AGENT_SLUG}",
            },
        )
        hire.raise_for_status()
        data = hire.json()
        session_id = data["session"]["id"]
        session_token = data["session_token"]

        print(f"Session: {session_id}")
        print(f"Token:   {session_token[:16]}...")
        print()

        result = client.post(
            f"/api/v1/sessions/{session_id}/execute",
            headers={"X-Session-Token": session_token},
            json={
                "input": "Analyze invoice #INV-4421 for anomalies",
                "context": {"source": "erp", "invoice_id": "INV-4421"},
            },
        )
        result.raise_for_status()
        print("Execute response:")
        print(result.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())

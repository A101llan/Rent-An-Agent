"""Dev helper: hire meeting-notes-agent on a LOCAL dev AgentHub API and save the session.

Uses the seeded dev customer (apps/api/app/scripts/seed.py) unless overridden via
AGENTHUB_DEV_EMAIL / AGENTHUB_DEV_PASSWORD. Writes session_id + session_token to
.dev-hire.json (gitignored). The token is never printed.

  python scripts\\dev_hire.py [--agent meeting-notes-agent] [--minutes 60] [--out .dev-hire.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = os.getenv("AGENTHUB_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def call(method: str, path: str, payload=None, bearer: str | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
        return exc.code, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="meeting-notes-agent")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--out", default=str(ROOT / ".dev-hire.json"))
    ap.add_argument(
        "--runtime-provider",
        default="local",
        help="sent as runtime_provider in the hire body (ignored by APIs that don't support it yet)",
    )
    args = ap.parse_args()

    email = os.getenv("AGENTHUB_DEV_EMAIL", "customer@agenthub.dev")
    password = os.getenv("AGENTHUB_DEV_PASSWORD", "Customer123!")
    status, body = call("POST", "/api/v1/auth/login", {"email": email, "password": password})
    if status != 200:
        print(json.dumps({"step": "login", "status": status, "body": body}, indent=2))
        return 1
    jwt = body["tokens"]["access_token"]
    print(f"[1/3] login OK as {email}")

    status, body = call("GET", f"/api/v1/agents/{args.agent}")
    if status != 200:
        print(json.dumps({"step": "agent", "status": status, "body": body}, indent=2))
        return 1
    plans = body["agent"].get("pricing_plans") or []
    if not plans:
        print("no pricing plans for agent")
        return 1
    plan = plans[0]
    print(f"[2/3] agent {args.agent} plan={plan.get('name')} id={plan['id']}")

    hire_body = {"agent_slug": args.agent, "pricing_plan_id": plan["id"], "duration_minutes": args.minutes}
    if args.runtime_provider:
        hire_body["runtime_provider"] = args.runtime_provider
    status, body = call("POST", "/api/v1/rentals/hire", hire_body, bearer=jwt)
    if status not in (200, 201):
        print(json.dumps({"step": "hire", "status": status, "body": body}, indent=2))
        return 1
    sess = body["session"]
    record = {
        "api_base": API,
        "agent_slug": args.agent,
        "rental_id": body["rental"]["id"],
        "session_id": sess["id"],
        "session_status": sess.get("status"),
        "expires_at": sess.get("expires_at"),
        "runtime_status": sess.get("runtime_status"),
        "runtime_provider_requested": args.runtime_provider,
        "runtime_provider_returned": body.get("runtime_provider") or sess.get("runtime_provider"),
        "local": body.get("local"),
        "hired_at": datetime.now(timezone.utc).isoformat(),
        "session_token": body["session_token"],
    }
    Path(args.out).write_text(json.dumps(record, indent=2), encoding="utf-8")
    safe = {k: v for k, v in record.items() if k != "session_token"}
    safe["session_token"] = f"<redacted, {len(record['session_token'])} chars, saved to {args.out}>"
    print("[3/3] hire OK (HTTP %s)" % status)
    print(json.dumps(safe, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

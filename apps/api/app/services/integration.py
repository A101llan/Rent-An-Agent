"""Build integration metadata for renters calling the session API."""

from uuid import UUID


def build_session_integration(
    *,
    api_base_url: str,
    session_id: UUID,
    session_token: str | None = None,
) -> dict:
    base = api_base_url.rstrip("/")
    session_path = f"{base}/api/v1/sessions/{session_id}"
    token_header = f'  -H "X-Session-Token: {session_token}" \\' if session_token else '  -H "X-Session-Token: YOUR_SESSION_TOKEN" \\'

    return {
        "api_base_url": base,
        "session_id": str(session_id),
        "auth": {
            "type": "session_token",
            "header": "X-Session-Token",
            "description": "Use the session token returned when the session was created. Scoped to this session only.",
        },
        "endpoints": {
            "get_session": {"method": "GET", "path": f"/api/v1/sessions/{session_id}"},
            "execute": {"method": "POST", "path": f"/api/v1/sessions/{session_id}/execute"},
            "executions": {"method": "GET", "path": f"/api/v1/sessions/{session_id}/executions"},
            "approvals": {"method": "GET", "path": f"/api/v1/sessions/{session_id}/approvals"},
            "resolve_approval": {
                "method": "POST",
                "path": f"/api/v1/sessions/{session_id}/approvals/{{approval_id}}/resolve",
            },
            "extend": {"method": "POST", "path": f"/api/v1/sessions/{session_id}/extend"},
        },
        "examples": {
            "execute_curl": (
                f'curl -X POST "{session_path}/execute" \\\n'
                f"{token_header}\n"
                '  -H "Content-Type: application/json" \\\n'
                '  -d \'{"input": "Analyze invoice #INV-4421", "context": {"source": "erp"}}\''
            ),
            "execute_python": (
                "import httpx\n\n"
                f'SESSION_ID = "{session_id}"\n'
                f'BASE = "{base}"\n'
                f'SESSION_TOKEN = "{session_token or "YOUR_SESSION_TOKEN"}"\n\n'
                "resp = httpx.post(\n"
                '    f"{BASE}/api/v1/sessions/{SESSION_ID}/execute",\n'
                '    headers={"X-Session-Token": SESSION_TOKEN},\n'
                '    json={"input": "Analyze invoice #INV-4421", "context": {"source": "erp"}},\n'
                ")\n"
                "print(resp.json())"
            ),
        },
    }

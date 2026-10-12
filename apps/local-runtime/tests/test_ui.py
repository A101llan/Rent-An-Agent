"""/ui page + /ui/api endpoints (TestClient; claim/jobs/Ollama mocked)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config, jobs, main, ollama_notes, session, ui

H = {"X-AgentHub-UI": "1"}
SID = "35001634-0000-0000-0000-000000000000"
MANIFEST = {"runtime": {"type": "local"}, "onboarding": {"questions": [
    {"id": "meeting_type", "question": "What type of meetings?", "placeholder": "standup"},
    {"id": "output_format", "question": "Preferred format?"},
    {"id": "team_names", "question": "Recurring attendees?"}]}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "SESSION_STORE_PATH", tmp_path / ".session.json")
    monkeypatch.setattr(ui, "ollama_is_up", lambda: True)
    session._bound.clear()
    return TestClient(main.app)


def bound(monkeypatch):
    session._bound.update({"bound": True, "mode": "claimed", "session_id": SID, "session_token": "secret-token",
                           "manifest": MANIFEST, "remote": {"agent_slug": "meeting-notes-agent-local"}})


def test_page_served_with_security_headers(client):
    r = client.get("/ui")
    assert r.status_code == 200 and "AgentHub Local" in r.text
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "localStorage" not in r.text and "sessionStorage" not in r.text


def test_claim_ok_returns_questions_not_token(client, monkeypatch):
    def fake_claim(token, sid):
        assert token == "secret-token"
        bound(monkeypatch)
        return {"bound": True}
    monkeypatch.setattr(session, "claim_session", fake_claim)
    r = client.post("/ui/api/claim", json={"session_id": SID, "session_token": "secret-token"}, headers=H)
    j = r.json()
    assert r.status_code == 200 and j["ok"] and [q["id"] for q in j["session"]["questions"]] == \
        ["meeting_type", "output_format", "team_names"]
    assert "secret-token" not in r.text
    assert "secret-token" not in client.get("/ui/api/state").text


@pytest.mark.parametrize("status,api_code,needle", [
    (401, "INVALID_SESSION_TOKEN", "don't match"), (404, "SESSION_NOT_FOUND", "couldn't find"),
    (409, "SESSION_NOT_LOCAL", "Local"), (410, "SESSION_EXPIRED", "expired"),
    (422, "VALIDATION_ERROR", "invalid"), (503, None, "reach AgentHub")])
def test_claim_errors_are_plain_messages(client, monkeypatch, status, api_code, needle):
    err = {"bound": False, "status_code": status, "api_code": api_code,
           "error": "api_unreachable" if api_code is None else "x"}
    monkeypatch.setattr(session, "claim_session", lambda t, s: err)
    r = client.post("/ui/api/claim", json={"session_id": SID, "session_token": "t"}, headers=H)
    assert r.status_code == status and not r.json()["ok"] and needle in r.json()["message"]


def test_cross_origin_and_missing_header_rejected(client, monkeypatch):
    called = []
    monkeypatch.setattr(session, "claim_session", lambda t, s: called.append(1) or {"bound": True})
    body = {"session_id": SID, "session_token": "t"}
    assert client.post("/ui/api/claim", json=body, headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/ui/api/claim", json=body).status_code == 403  # no X-AgentHub-UI
    assert client.post("/session/claim", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/ui", headers={"Host": "evil.example:8765"}).status_code == 403  # DNS rebinding
    assert called == []
    ok = client.post("/ui/api/claim", json=body, headers={**H, "Origin": f"http://127.0.0.1:{config.PORT}"})
    assert ok.status_code == 200 and called == [1]


def _upload(client, name="notes.docx", data=b"PK\x03\x04fake"):
    return client.post(f"/ui/api/upload?filename={name}", content=data,
                       headers={**H, "Content-Type": "application/octet-stream"})


def test_upload_validation(client):
    assert _upload(client, "a.pdf").json()["code"] == "unsupported_file_type"
    assert _upload(client, "a.docx", b"not a zip").json()["code"] == "unsupported_file_type"
    j = _upload(client, "..\\..\\evil name.docx").json()
    assert j["ok"] and j["filename"] == "evil name.docx" and len(j["upload_id"]) == 32


def test_run_passes_onboarding_and_shows_result(client, monkeypatch):
    bound(monkeypatch)
    up = _upload(client).json()
    seen = {}

    def fake_extract(paths, out_path, *, job_id, onboarding=None, **k):
        seen["onboarding"], seen["paths"] = onboarding, paths
        payload = {"status": "completed", "output": {"summary": "S", "decisions": ["D1"],
                   "action_items": [{"owner": "A", "task": "T"}], "open_questions": ["Q"]},
                   "usage": {}, "source": "ollama", "onboarding": onboarding,
                   "input_truncated": {"truncated": True, "message": "Only the first 6000 of 9000 characters."},
                   "warnings": ["WARNING: INPUT TRUNCATED - x"], "session": {}, "usage_report": []}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload))
        return payload

    monkeypatch.setattr(jobs, "extract_to_file", fake_extract)
    monkeypatch.setattr(jobs.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())
    ans = {"meeting_type": "standup", "output_format": "json", "team_names": "Amina (PM)"}
    r = client.post("/ui/api/run", json={"upload_id": up["upload_id"], "onboarding": ans}, headers=H).json()
    assert r["ok"]
    assert seen["onboarding"] == ans and str(seen["paths"][0]).endswith("notes.docx")
    j = client.get(f"/ui/api/jobs/{r['job_id']}").json()
    assert j["status"] == "completed" and j["output"]["decisions"] == ["D1"] and j["onboarding"] == ans
    assert "6000" in j["truncation_message"] and j["warnings"]
    saved = client.get(j["json_url"])
    assert saved.status_code == 200 and saved.json()["onboarding"] == ans


def test_onboarding_not_in_prompt(monkeypatch):
    """Answers are recorded only; the Ollama request is built from the document text alone."""
    body, _ = ollama_notes._build_request("doc text")
    assert "standup" not in json.dumps(body)


def test_run_requires_claim(client):
    up = _upload(client).json()
    r = client.post("/ui/api/run", json={"upload_id": up["upload_id"]}, headers=H)
    assert r.status_code == 403 and "Claim your session" in r.json()["message"]


def test_run_rejects_bad_upload_id(client, monkeypatch):
    bound(monkeypatch)
    assert client.post("/ui/api/run", json={"upload_id": "../x"}, headers=H).json()["code"] == "upload_not_found"


@pytest.mark.parametrize("job,up,code,needle", [
    ({"error_code": "low_memory", "error": "x", "memory": {"free_mb": 900, "required_mb": 1300}}, True,
     "low_memory", "900 MB of RAM free, 1300 MB needed"),
    ({"error_code": "extraction_failed", "error": "ollama call failed: timed out"}, True, "timeout", "too long"),
    ({"error_code": "extraction_failed", "error": "ollama call failed: refused"}, False, "ollama_down", "Ollama"),
    ({"error_code": "extraction_failed", "error": "model output did not match schema"}, True,
     "extraction_failed", "couldn't produce"),
])
def test_job_failures_mapped(client, monkeypatch, job, up, code, needle):
    monkeypatch.setattr(ui, "ollama_is_up", lambda: up)
    jobs._jobs["jf"] = {"id": "jf", "type": "meeting-notes", "status": "failed", **job}
    j = client.get("/ui/api/jobs/jf").json()
    assert j["code"] == code and needle in j["message"]
    if code == "low_memory":
        assert "Close other apps" in j["message"] and "then retry" in j["message"]

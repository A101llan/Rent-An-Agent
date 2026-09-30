"""Sidecar <-> API contract (docs/local-runtime-contract.md) with mocked HTTP (urlopen)."""

import io
import json
import urllib.error

import pytest

from app import config, session

SID = "3b0d875f-0000-0000-0000-000000000000"
TOKEN = "t" * 43


def envelope(code, msg="x"):
    return {"detail": {"error": {"code": code, "message": msg, "request_id": "req-1"}}}


class Resp:
    def __init__(self, status, body):
        self.status = status
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(status, body):
    return urllib.error.HTTPError("http://x", status, "err", {}, io.BytesIO(json.dumps(body).encode()))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSION_STORE_PATH", tmp_path / ".session.json")
    monkeypatch.setattr(config, "USAGE_QUEUE_PATH", tmp_path / "usage-pending.jsonl")
    monkeypatch.setattr(config, "USAGE_FAILED_PATH", tmp_path / "usage-failed.jsonl")
    monkeypatch.setattr(config, "OFFLINE_STUB", False)
    monkeypatch.setattr(config, "AGENTHUB_API_BASE", "http://api.test")
    session._bound.clear()
    yield tmp_path


def mock(monkeypatch, *outcomes):
    """Each outcome: (status, body) | Exception. Consumed in order; last one repeats."""
    calls = []
    seq = list(outcomes)

    def fake(req, timeout=None):
        calls.append({"url": req.full_url, "method": req.get_method(),
                      "token": req.get_header("X-session-token"),
                      "body": json.loads(req.data) if req.data else None})
        out = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(out, Exception):
            raise out
        status, body = out
        if status >= 400:
            raise http_error(status, body)
        return Resp(status, body)

    monkeypatch.setattr(session.urllib.request, "urlopen", fake)
    return calls


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


CLAIM_OK = {"session_id": SID, "expires_at": "2099-01-01T00:00:00Z", "manifest": {"runtime": {"type": "local"}},
            "agent_slug": "meeting-notes-agent-local", "agent_version": "1.0.0", "runtime_provider": "local",
            "some_future_field": 1}


# ------------------------------------------------------------------ claim

def test_claim_200_binds_and_ignores_unknown_fields(monkeypatch):
    calls = mock(monkeypatch, (200, CLAIM_OK))
    r = session.claim_session(TOKEN, SID)
    assert r["bound"] and r["mode"] == "claimed" and r["session_id"] == SID
    assert r["expires_at"].startswith("2099-01-01")
    assert calls[0]["url"] == f"http://api.test/api/v1/sessions/{SID}/local/claim"
    assert calls[0]["method"] == "POST" and calls[0]["token"] == TOKEN
    assert session.require_active() is None


@pytest.mark.parametrize("status,code,err", [
    (401, "INVALID_SESSION_TOKEN", "unauthorized"),
    (404, "SESSION_NOT_FOUND", "session_not_found"),
    (409, "SESSION_NOT_LOCAL", "not_local_session"),
    (410, "SESSION_EXPIRED", "session_expired"),
    (422, "VALIDATION_ERROR", "validation_error"),
])
def test_claim_4xx_fails_closed_keyed_on_code(monkeypatch, status, code, err):
    mock(monkeypatch, (200, CLAIM_OK))
    assert session.claim_session(TOKEN, SID)["bound"]  # previously bound...
    mock(monkeypatch, (status, envelope(code)))
    r = session.claim_session(TOKEN, SID)
    assert not r["bound"] and r["fail_closed"]
    assert r["api_code"] == code and r["error"] == err and r["http_status"] == status
    assert session.require_active()["error"] == "session_not_bound"  # ...binding cleared


def test_claim_5xx_fails_closed(monkeypatch):
    mock(monkeypatch, (503, envelope("INTERNAL_ERROR")))
    r = session.claim_session(TOKEN, SID)
    assert not r["bound"] and r["fail_closed"] and r["http_status"] == 503
    assert session.require_active() is not None


def test_claim_network_error_fails_closed_without_stub(monkeypatch):
    mock(monkeypatch, urllib.error.URLError("refused"))
    r = session.claim_session(TOKEN, SID)
    assert not r["bound"] and r["error"] == "api_unreachable"


def test_claim_network_error_offline_stub_only_when_flag_set(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE_STUB", True)
    mock(monkeypatch, urllib.error.URLError("refused"))
    r = session.claim_session(TOKEN, SID)
    assert r["bound"] and r["mode"] == "offline_stub" and "OFFLINE STUB" in r["warning"]


def test_claim_4xx_with_offline_stub_still_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE_STUB", True)
    mock(monkeypatch, (401, envelope("INVALID_SESSION_TOKEN")))
    assert not session.claim_session(TOKEN, SID)["bound"]


# ------------------------------------------------------------------ usage

def bind(monkeypatch):
    mock(monkeypatch, (200, CLAIM_OK))
    assert session.claim_session(TOKEN, SID)["bound"]


def test_usage_201_sent_and_body_shape(monkeypatch):
    bind(monkeypatch)
    calls = mock(monkeypatch, (201, {"id": "u1", "metric_type": "requests", "quantity": 1.0, "unit": "count",
                                     "execution_id": None, "session_id": SID, "recorded_at": "2026-09-30T00:00:00Z", "extra": True}))
    r = session.report_usage_metric("requests", 1, "count")
    assert r["outcome"] == "sent" and r["cloud_row"]["id"] == "u1"
    assert calls[0]["url"].endswith(f"/sessions/{SID}/usage")
    assert calls[0]["body"] == {"metric_type": "requests", "quantity": 1, "unit": "count", "execution_id": None}


@pytest.mark.parametrize("status,code", [(401, "INVALID_SESSION_TOKEN"), (409, "SESSION_NOT_LOCAL"),
                                         (410, "SESSION_EXPIRED"), (422, "VALIDATION_ERROR")])
def test_usage_4xx_terminal_dropped(monkeypatch, isolated, status, code):
    bind(monkeypatch)
    mock(monkeypatch, (status, envelope(code)))
    r = session.report_usage_metric("requests", 1, "count")
    assert r["outcome"] == "failed" and r["api_code"] == code
    assert lines(config.USAGE_QUEUE_PATH) == []
    failed = lines(config.USAGE_FAILED_PATH)
    assert len(failed) == 1 and failed[0]["api_code"] == code and failed[0]["http_status"] == status


def test_usage_5xx_queued(monkeypatch):
    bind(monkeypatch)
    mock(monkeypatch, (502, envelope("BAD_GATEWAY")))
    r = session.report_usage_metric("input_tokens", 10, "tokens")
    assert r["outcome"] == "queued"
    q = lines(config.USAGE_QUEUE_PATH)
    assert len(q) == 1 and q[0]["payload"]["metric_type"] == "input_tokens"
    assert lines(config.USAGE_FAILED_PATH) == []


def test_usage_network_error_queued(monkeypatch):
    bind(monkeypatch)
    mock(monkeypatch, urllib.error.URLError("refused"))
    assert session.report_usage_metric("requests", 1, "count")["outcome"] == "queued"
    assert len(lines(config.USAGE_QUEUE_PATH)) == 1


def test_usage_zero_quantity_skipped_client_side(monkeypatch):
    bind(monkeypatch)
    calls = mock(monkeypatch, (201, {}))
    results = session.report_job_usage({"input_tokens": 0, "output_tokens": 5})
    assert [r["metric_type"] for r in results if r["outcome"] == "sent"] == ["requests", "output_tokens"]
    assert len(calls) == 2


# ------------------------------------------------------------------ sync

def test_sync_rules(monkeypatch):
    bind(monkeypatch)
    mock(monkeypatch, urllib.error.URLError("down"))
    for m in ("requests", "input_tokens", "output_tokens"):
        session.report_usage_metric(m, 1, "count")
    assert len(lines(config.USAGE_QUEUE_PATH)) == 3
    # row1 -> 201 sent/removed, row2 -> 422 terminal/removed+failed, row3 -> 503 kept
    mock(monkeypatch, (201, {"id": "a"}), (422, envelope("VALIDATION_ERROR")), (503, envelope("UNAVAILABLE")))
    r = session.sync_pending_usage()
    assert [x["outcome"] for x in r["results"]] == ["sent", "failed", "kept"]
    assert r["synced"] == 1 and r["remaining"] == 1
    q = lines(config.USAGE_QUEUE_PATH)
    assert len(q) == 1 and q[0]["payload"]["metric_type"] == "output_tokens" and q[0]["attempts"] == 1
    failed = lines(config.USAGE_FAILED_PATH)
    assert len(failed) == 1 and failed[0]["api_code"] == "VALIDATION_ERROR"
    # network error on sync -> still kept
    mock(monkeypatch, urllib.error.URLError("down"))
    r = session.sync_pending_usage()
    assert r["remaining"] == 1 and r["results"][0]["outcome"] == "kept"

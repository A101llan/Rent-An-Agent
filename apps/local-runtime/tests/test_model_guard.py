"""Friendly Ollama-down / model-missing errors, unload on timeout/abort, per-model RAM guard + fallback.

Ollama, RAM and the network are mocked.
"""

import io
import json
import socket
import urllib.error

import pytest

from app import cli, config, jobs, ollama_notes

GOOD = {"summary": "s", "decisions": ["d"], "action_items": [{"owner": "A", "task": "t"}], "open_questions": []}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake(monkeypatch):
    st = {"chat": [], "unload": [], "loaded": [], "tags": None, "chat_exc": None, "up": True}

    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if not st["up"]:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))
        if url.endswith("/api/ps"):
            return Resp(json.dumps({"models": [{"name": m} for m in st["loaded"]]}).encode())
        if url.endswith("/api/tags"):
            return Resp(json.dumps({"models": [{"name": m} for m in (st["tags"] or [])]}).encode())
        if url.endswith("/api/generate"):
            st["unload"].append(json.loads(req.data))
            return Resp(b"{}")
        if url.endswith("/api/chat"):
            body = json.loads(req.data)
            st["chat"].append({"model": body["model"], "timeout": timeout})
            if st["chat_exc"]:
                raise st["chat_exc"]
            return Resp(json.dumps({"message": {"content": json.dumps(GOOD)}, "eval_count": 5}).encode())
        if url.endswith("/api/version") or url.rstrip("/").endswith(":11434"):
            return Resp(b"{}")
        raise AssertionError(url)

    monkeypatch.setattr(ollama_notes.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ollama_notes, "ollama_is_up", lambda: st["up"])
    monkeypatch.setattr(ollama_notes, "free_ram_mb", lambda: st.get("ram", 8000))
    monkeypatch.setattr(config, "OLLAMA_MODEL", "big:3b")
    monkeypatch.setattr(config, "FALLBACK_MODEL", None)
    monkeypatch.setattr(config, "MODELS", {})
    for k in ("LOCAL_RUNTIME_TIMEOUT_S", "OLLAMA_TIMEOUT", "LOCAL_RUNTIME_MIN_FREE_MB", "LOCAL_RUNTIME_MIN_FREE_MB_LOADED"):
        monkeypatch.delenv(k, raising=False)
    return st


def test_ollama_down_is_friendly(fake):
    fake["up"] = False
    with pytest.raises(ollama_notes.OllamaDownError) as ei:
        ollama_notes.meeting_notes_response("x")
    msg = str(ei.value)
    assert ei.value.code == "ollama_down" and "OLLAMA NOT RUNNING" in msg and "10061" not in msg
    assert msg.startswith(ollama_notes.ollama_down_message())


def test_cli_ollama_down_prints_notice(fake, tmp_path, monkeypatch, capsys):
    fake["up"] = False
    doc = tmp_path / "n.txt"
    doc.write_text("Alice will ship it.")
    monkeypatch.setattr(config, "SESSION_STORE_PATH", tmp_path / ".s.json", raising=False)
    rc = cli.main([str(doc), "-o", str(tmp_path / "o.json"), "--dev-unbound"])
    err = capsys.readouterr().err
    assert rc == 4 and "OLLAMA NOT RUNNING" in err and "WinError" not in err


def test_model_missing_is_friendly(fake):
    fake["chat_exc"] = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"error":"model \\"big:3b\\" not found"}'))
    with pytest.raises(ollama_notes.ModelMissingError) as ei:
        ollama_notes.meeting_notes_response("x")
    assert "MODEL MISSING" in str(ei.value) and "ollama pull big:3b" in str(ei.value) and "HTTP 404" not in str(ei.value)


def test_timeout_unloads_model_and_is_coded(fake):
    fake["chat_exc"] = urllib.error.URLError(socket.timeout("timed out"))
    with pytest.raises(ollama_notes.ExtractionTimeoutError) as ei:
        ollama_notes.meeting_notes_response("x")
    assert ei.value.code == "timeout" and "unloaded" in str(ei.value)
    assert fake["unload"] == [{"model": "big:3b", "keep_alive": 0}]


def test_abort_running_job_unloads(fake, monkeypatch):
    called = []
    monkeypatch.setattr(ollama_notes, "unload_model", lambda model=None: called.append(model))
    monkeypatch.setattr(jobs.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: target()})())
    jobs._jobs["run1"] = {"id": "run1", "status": "running", "cancel_requested": False}
    jobs.cancel_job("run1")
    assert called == [None] and jobs._jobs["run1"]["status"] == "cancelled"


def test_per_model_limits_and_env_override(fake, monkeypatch):
    monkeypatch.setattr(config, "MODELS", {"big:3b": {"timeout_s": 180, "min_free_mb": 3000, "min_free_mb_loaded": 300}})
    lim = config.model_limits("big:3b")
    assert lim == {"timeout_s": 180.0, "min_free_mb": 3000, "min_free_mb_loaded": 300}
    assert config.model_limits("other")["min_free_mb"] == config.MIN_FREE_MB_COLD  # global value
    monkeypatch.setenv("LOCAL_RUNTIME_MIN_FREE_MB", "99")
    # an env var set for this run skips the per-model value (the global already holds the env value)
    assert config.model_limits("big:3b")["min_free_mb"] == config.MIN_FREE_MB_COLD
    fake["ram"] = 9000
    ollama_notes.meeting_notes_response("x")
    assert fake["chat"][-1]["timeout"] == 180.0


def _set_models(monkeypatch):
    monkeypatch.setattr(config, "MODELS", {"big:3b": {"min_free_mb": 3000, "min_free_mb_loaded": 300},
                                           "small:1b": {"min_free_mb": 1300, "min_free_mb_loaded": 300}})
    monkeypatch.setattr(config, "FALLBACK_MODEL", "small:1b")


def test_fallback_when_ram_short_for_primary(fake, monkeypatch):
    _set_models(monkeypatch)
    fake["ram"], fake["tags"] = 2000, ["big:3b", "small:1b"]
    r = ollama_notes.meeting_notes_response("x")
    assert fake["chat"][-1]["model"] == "small:1b" and r["meta"]["model"] == "small:1b"
    fb = r["meta"]["fallback"]
    assert fb["from"] == "big:3b" and fb["to"] == "small:1b" and fb["free_mb"] == 2000 and "small:1b" in fb["message"]


def test_no_fallback_when_primary_fits(fake, monkeypatch):
    _set_models(monkeypatch)
    fake["ram"] = 3500
    r = ollama_notes.meeting_notes_response("x")
    assert r["meta"]["model"] == "big:3b" and r["meta"]["fallback"] is None


def test_refuse_when_fallback_also_short(fake, monkeypatch):
    _set_models(monkeypatch)
    fake["ram"], fake["tags"] = 1000, ["big:3b", "small:1b"]
    with pytest.raises(ollama_notes.LowMemoryError) as ei:
        ollama_notes.meeting_notes_response("x")
    assert ei.value.required_mb == 3000 and fake["chat"] == []


def test_fallback_recorded_in_output_json_and_ui(fake, monkeypatch, tmp_path):
    _set_models(monkeypatch)
    fake["ram"], fake["tags"] = 2000, ["big:3b", "small:1b"]
    doc = tmp_path / "n.txt"
    doc.write_text("Alice will ship it.")
    out = tmp_path / "o.json"
    p = jobs.extract_to_file([doc], out, job_id="j", report_usage=False, session_info={})
    saved = json.loads(out.read_text())
    assert saved["model_used"] == "small:1b" and saved["model_fallback"]["to"] == "small:1b"
    from fastapi.testclient import TestClient

    from app import main, ui
    monkeypatch.setattr(ui, "ollama_is_up", lambda: True)
    jobs._jobs["jfb"] = {"id": "jfb", "status": "completed", "result_path": str(out),
                         "result": {"output": p["output"], "model_used": "small:1b", "model_fallback": p["model_fallback"]}}
    j = TestClient(main.app).get("/ui/api/jobs/jfb").json()
    assert j["model_used"] == "small:1b" and "small:1b" in j["model_fallback"]["message"]


@pytest.mark.parametrize("code,needle", [("ollama_down", "OLLAMA NOT RUNNING"), ("model_missing", "MODEL MISSING")])
def test_ui_shows_friendly_notice(monkeypatch, code, needle):
    from fastapi.testclient import TestClient

    from app import main, ui
    monkeypatch.setattr(ui, "ollama_is_up", lambda: code != "ollama_down")
    msg = ollama_notes.ollama_down_message() if code == "ollama_down" else ollama_notes.model_missing_message("big:3b")
    jobs._jobs["jx"] = {"id": "jx", "status": "failed", "error_code": code, "error": msg}
    j = TestClient(main.app).get("/ui/api/jobs/jx").json()
    assert j["code"] == code and needle in j["message"]

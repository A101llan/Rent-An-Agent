"""Job-safety: generation caps, timeout, input cap, RAM guard (no usage), setup pause. Ollama mocked."""

import io
import json
import sys
import types
from pathlib import Path

import pytest

from app import config, jobs, ollama_notes, service, session

GOOD = {"summary": "s", "decisions": ["d"], "action_items": [{"owner": "A", "task": "t"}], "open_questions": []}


class Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()
        self.status = 200

    def read(self):
        return self._b

    def __iter__(self):
        return iter([self._b])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def ollama(monkeypatch):
    """Mock Ollama: /api/ps (model loaded?) and /api/chat. Records chat requests + timeouts."""
    state = {"loaded": True, "chat": [], "timeouts": []}

    def fake(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/api/ps"):
            return Resp({"models": [{"name": config.OLLAMA_MODEL}] if state["loaded"] else []})
        if url.endswith("/api/chat"):
            state["chat"].append(json.loads(req.data))
            state["timeouts"].append(timeout)
            return Resp({"message": {"content": json.dumps(GOOD)}, "prompt_eval_count": 10, "eval_count": 5})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ollama_notes.urllib.request, "urlopen", fake)
    return state


@pytest.fixture
def ram(monkeypatch):
    box = {"mb": 4000}
    monkeypatch.setattr(ollama_notes, "free_ram_mb", lambda: box["mb"])
    return box


@pytest.mark.parametrize("prompt_file", [None, "decisions-v2"])
def test_request_has_caps_format_and_timeout(monkeypatch, ollama, ram, prompt_file):
    pf = None if prompt_file is None else str(Path(__file__).resolve().parents[1] / "prompts" / "decisions-v2.json")
    monkeypatch.setattr(config, "PROMPT_FILE", pf)
    r = ollama_notes.meeting_notes_response("Alice will ship it.")
    body = ollama["chat"][0]
    assert body["format"]  # "json" or the prompt's JSON schema
    assert body["options"]["num_predict"] == config.OLLAMA_NUM_PREDICT
    assert body["options"]["num_ctx"] == config.OLLAMA_NUM_CTX
    assert body["stream"] is False
    assert ollama["timeouts"][0] == config.OLLAMA_TIMEOUT_SECONDS
    if prompt_file:  # prompt-file options (temperature) are preserved, content untouched
        assert body["options"]["temperature"] == 0
        assert r["meta"]["prompt"] == "decisions-v2"
    assert r["meta"]["memory"]["model_loaded"] is True


def test_prompt_num_predict_lower_than_cap_is_kept():
    cap = config.OLLAMA_NUM_PREDICT
    assert ollama_notes._safety_options({"num_predict": 100})["num_predict"] == 100
    assert ollama_notes._safety_options({"num_predict": 99999})["num_predict"] == cap
    assert ollama_notes._safety_options({"num_predict": -1})["num_predict"] == cap


def test_timeout_maps_to_extraction_error(monkeypatch, ram):
    def boom(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/api/ps"):
            return Resp({"models": []})
        raise TimeoutError("timed out")

    monkeypatch.setattr(ollama_notes.urllib.request, "urlopen", boom)
    with pytest.raises(ollama_notes.ExtractionError, match="timed out"):
        ollama_notes.meeting_notes_response("x")


def test_truncate_input_notes_it():
    text = ("line of meeting text\n" * 1000)  # 21000 chars
    out, note = jobs.truncate_input(text, limit=8000)  # explicit limit, independent of defaults
    assert note["truncated"] and note["original_chars"] == 21000 and note["kept_chars"] <= 8000
    assert "truncated" in out and len(out) < 8100
    assert jobs.truncate_input("short", limit=8000) == ("short", None)


def _docx(path: Path, paragraphs: int) -> Path:
    import docx

    d = docx.Document()
    for i in range(paragraphs):
        d.add_paragraph(f"Item {i}: Brian will follow up on the payments retry work and report back next week.")
    d.save(path)
    return path


def test_large_docx_truncated_in_output_and_prompt(tmp_path, monkeypatch, ollama, ram):
    calls = []
    monkeypatch.setattr(session, "report_job_usage", lambda u, job_id=None: calls.append(u) or [])
    src = _docx(tmp_path / "big.docx", 600)  # ~50k chars
    payload = jobs.extract_to_file([src], tmp_path / "out.json", job_id="j1")
    assert payload["input_truncated"]["truncated"] is True
    assert payload["warnings"] and payload["warnings"][0].startswith("WARNING: INPUT TRUNCATED")
    assert payload["input_truncated"]["original_chars"] > 40000
    sent = ollama["chat"][0]["messages"][-1]["content"]
    assert len(sent) < config.MAX_INPUT_CHARS + 500
    saved = json.loads((tmp_path / "out.json").read_text())
    assert saved["input_truncated"]["kept_chars"] <= config.MAX_INPUT_CHARS
    assert calls  # normal run still meters


@pytest.mark.parametrize("loaded,delta,ok", [(False, -1, False), (False, 0, True), (True, -1, False), (True, 0, True)])
def test_ram_guard_thresholds(ollama, ram, loaded, delta, ok):
    need = config.MIN_FREE_MB_WARM if loaded else config.MIN_FREE_MB_COLD
    ollama["loaded"], ram["mb"] = loaded, need + delta
    if ok:
        assert ollama_notes.check_memory()["required_mb"] == need
    else:
        with pytest.raises(ollama_notes.LowMemoryError) as ei:
            ollama_notes.check_memory()
        msg = str(ei.value)
        assert f"{need - 1} MB of RAM free" in msg and f"{need} MB needed" in msg
        assert "Close other apps" in msg and "then retry" in msg
        assert ei.value.free_mb == need - 1 and ei.value.required_mb == need


def test_low_memory_job_fails_without_ollama_call_or_usage(tmp_path, monkeypatch, ollama, ram):
    ollama["loaded"], ram["mb"] = False, 100
    usage = []
    monkeypatch.setattr(session, "report_job_usage", lambda *a, **k: usage.append(a) or [])
    monkeypatch.setattr(session, "require_active", lambda: None)
    src = tmp_path / "n.txt"
    src.write_text("Alice will ship it.")
    jobs._jobs["j-low"] = {"id": "j-low", "type": "meeting-notes", "status": "queued", "input_paths": [str(src)],
                          "output_path": str(tmp_path / "o.json"), "cancel_requested": False}
    jobs._run_job("j-low")
    job = jobs.get_job("j-low")
    assert job["status"] == "failed" and job["error_code"] == "low_memory"
    assert "Close other apps" in job["error"] and job["memory"]["free_mb"] == 100
    assert ollama["chat"] == [] and usage == [] and not (tmp_path / "o.json").exists()


def test_psutil_missing_does_not_block(monkeypatch, ollama):
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert ollama_notes.free_ram_mb() is None
    assert ollama_notes.check_memory()["free_mb"] is None


def test_setup_pauses_on_ollama_down(monkeypatch, capsys):
    paused = []
    monkeypatch.setattr(service, "_wait_for_key", lambda *a, **k: paused.append(1))
    monkeypatch.setattr(ollama_notes, "ollama_is_up", lambda: False)
    assert service.setup(["--no-pull"]) == 2
    assert paused == [1]
    assert "Ollama" in capsys.readouterr().out
    paused.clear()
    assert service.setup(["--no-pull", "--no-pause"]) == 2 and paused == []


def test_setup_success_pauses_only_with_flag(monkeypatch):
    paused = []
    monkeypatch.setattr(service, "_wait_for_key", lambda *a, **k: paused.append(1))
    monkeypatch.setattr(ollama_notes, "ollama_is_up", lambda: True)
    monkeypatch.setattr(ollama_notes, "model_available", lambda *a: True)
    assert service.setup([]) == 0 and paused == []
    assert service.setup(["--pause"]) == 0 and paused == [1]


def test_wait_for_key_noop_without_console(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    service._wait_for_key()  # must not block


def test_config_reads_defaults_file_keys(tmp_path, monkeypatch):
    """env > config.json > config.defaults.json (full or short key) > hardcoded."""
    import importlib

    from app import config as cfg

    defaults = tmp_path / "config.defaults.json"
    # Exactly the keys Ollama Integrator committed in 2ddcae3.
    defaults.write_text(json.dumps({"model": "llama3.2:1b", "num_predict": 384, "num_ctx": 2048, "format": "json",
                                    "timeout_s": 120, "max_input_chars": 6000, "min_free_mb": 1300,
                                    "min_free_mb_loaded": 300}))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("LOCAL_RUNTIME_HOME", str(home))
    for k in ("OLLAMA_TIMEOUT", "LOCAL_RUNTIME_TIMEOUT_S", "LOCAL_RUNTIME_FORMAT", "LOCAL_RUNTIME_NUM_PREDICT", "LOCAL_RUNTIME_NUM_CTX", "LOCAL_RUNTIME_MAX_INPUT_CHARS",
              "LOCAL_RUNTIME_MIN_FREE_MB", "LOCAL_RUNTIME_MIN_FREE_MB_LOADED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LOCAL_RUNTIME_DEFAULTS_FILE", str(defaults))
    try:
        c = importlib.reload(cfg)
        assert (c.OLLAMA_NUM_CTX, c.OLLAMA_NUM_PREDICT, c.OLLAMA_TIMEOUT_SECONDS) == (2048, 384, 120.0)
        assert (c.MAX_INPUT_CHARS, c.MIN_FREE_MB_COLD, c.MIN_FREE_MB_WARM) == (6000, 1300, 300)
        (home / "config.json").write_text(json.dumps({"LOCAL_RUNTIME_NUM_CTX": 3000}))
        monkeypatch.setenv("LOCAL_RUNTIME_NUM_PREDICT", "200")
        c = importlib.reload(cfg)
        assert c.OLLAMA_NUM_CTX == 3000 and c.OLLAMA_NUM_PREDICT == 200 and c.MIN_FREE_MB_COLD == 1300
        assert c.OLLAMA_FORMAT == "json"
        monkeypatch.setenv("LOCAL_RUNTIME_TIMEOUT_S", "99999")  # clamped to 900
        monkeypatch.setenv("LOCAL_RUNTIME_MIN_FREE_MB", "abc")  # invalid -> hardcoded fallback
        c = importlib.reload(cfg)
        assert c.OLLAMA_TIMEOUT_SECONDS == 900.0 and c.MIN_FREE_MB_COLD == 1500
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


def test_temperature_default_does_not_override_prompt_options(monkeypatch):
    monkeypatch.setattr(ollama_notes, "load_prompt_override", lambda: {
        "name": "p", "system": "s", "user_template": "{notes}", "options": {"temperature": 0.3}})
    body, _ = ollama_notes._build_request("x")
    assert body["options"]["temperature"] == 0.3
    monkeypatch.setattr(ollama_notes, "load_prompt_override", lambda: None)
    body, _ = ollama_notes._build_request("x")
    assert body["options"]["temperature"] == 0


def test_url_timeout_message(monkeypatch, ram):
    import socket
    import urllib.error

    def boom(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/api/ps"):
            return Resp({"models": []})
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(ollama_notes.urllib.request, "urlopen", boom)
    with pytest.raises(ollama_notes.ExtractionError, match="timed out after"):
        ollama_notes.meeting_notes_response("x")

"""Proof: device-side Ollama health check (marketplace_sdk.ollama_local.check_ollama).

Does NOT stop Ollama or remove models. The not_running / not_ollama branches are exercised by
temporarily relaxing the port allowlist *inside this process* to a closed port / a non-Ollama
HTTP service (AgentHub API on :8000), so the real connection-refused / 404 code paths run.
Writes .dev-tools/ollama-proof-healthcheck.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from ollama_proof_lib import ROOT, now_eat, ol, write_evidence

cases = []


def case(name, expect, fn, note=""):
    res = fn()
    d = res.to_dict() if hasattr(res, "to_dict") else res
    ok = d.get("code") == expect
    cases.append({"case": name, "expected_code": expect, "got_code": d.get("code"), "pass": ok, "note": note, "result": d})
    print(f"{'PASS' if ok else 'FAIL'} {name}: {d.get('code')} - {d.get('message')}", flush=True)


case("ollama up, configured model", "ok", lambda: ol.check_ollama())
case("ollama up, configured model, probe (load + 1 token)", "ok", lambda: ol.check_ollama(probe=True))
case("model missing (nonexistent name)", "model_missing", lambda: ol.check_ollama(model="llama3.2:does-not-exist"))
case("model missing (plausible but not pulled)", "model_missing", lambda: ol.check_ollama(model="phi3:mini"))
for url, why in [
    ("http://localhost:11434", "localhost may resolve to ::1 on Windows"),
    ("http://0.0.0.0:11434", "bind-all address"),
    ("http://192.168.1.50:11434", "LAN host"),
    ("http://ollama.example.com:11434", "remote host"),
    ("https://127.0.0.1:11434", "wrong scheme"),
    ("http://127.0.0.1:11435", "wrong port"),
]:
    case(f"wrong host: {url}", "wrong_host", lambda u=url: ol.check_ollama(base_url=u), why)

orig_port = ol.ALLOWED_PORT
try:
    ol.ALLOWED_PORT = 11499
    case("not running (closed port 11499, allowlist relaxed in-process)", "not_running",
         lambda: ol.check_ollama(base_url="http://127.0.0.1:11499"), "simulates Ollama stopped without stopping it")
    ol.ALLOWED_PORT = 8000
    case("not ollama (AgentHub API on :8000, allowlist relaxed in-process)", "not_ollama",
         lambda: ol.check_ollama(base_url="http://127.0.0.1:8000"), "another HTTP service on the port")
finally:
    ol.ALLOWED_PORT = orig_port


def chat_wrong_host():
    try:
        ol.chat_json("s", "u", schema={"type": "object"}, validate=lambda d: (d, []), base_url="http://10.0.0.5:11434")
        return {"code": "no_error"}
    except ol.LocalLLMError as e:
        return e.to_dict()


case("chat_json refuses non-loopback URL before sending data", "wrong_host", chat_wrong_host)

# /invoke failure path end-to-end (Meeting Notes agent) with a missing model via the config env var
env = dict(os.environ, AGENTHUB_LOCAL_MODEL="llama3.2:does-not-exist", PYTHONIOENCODING="utf-8")
code = ("import json,sys; sys.path.insert(0, r'%s'); from fastapi.testclient import TestClient; import main; "
        "print(json.dumps(TestClient(main.app).post('/invoke', json={'input': 'Ann: I will send the deck Friday.'}).json()))"
        % (ROOT / "agents" / "meeting-notes-agent"))
p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
inv = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"stderr": p.stderr[-500:]}
cases.append({"case": "meeting-notes /invoke with AGENTHUB_LOCAL_MODEL=llama3.2:does-not-exist", "expected_code": "model_missing",
              "got_code": (inv.get("error") or {}).get("code"), "pass": (inv.get("error") or {}).get("code") == "model_missing"
              and inv.get("status") == "failed", "result": inv, "note": "fails clearly; no canned notes"})
print(cases[-1]["case"], cases[-1]["got_code"], inv.get("status"))

cli = subprocess.run([sys.executable, "-m", "marketplace_sdk.ollama_local", "--check"], capture_output=True, text=True,
                     cwd=str(ROOT / "packages" / "agent-sdk" / "src"))
cli_missing = subprocess.run([sys.executable, "-m", "marketplace_sdk.ollama_local", "--check", "--model", "nope:1b"],
                             capture_output=True, text=True, cwd=str(ROOT / "packages" / "agent-sdk" / "src"))
path = write_evidence("ollama-proof-healthcheck.json", {
    "generated_at": now_eat(), "timezone": "Africa/Nairobi (EAT, UTC+3)",
    "helper": "packages/agent-sdk/src/marketplace_sdk/ollama_local.py::check_ollama",
    "config": ol.load_config().to_dict(),
    "all_pass": all(c["pass"] for c in cases),
    "cases": cases,
    "cli": {"ok_run": {"exit_code": cli.returncode, "stdout": cli.stdout},
            "missing_model_run": {"exit_code": cli_missing.returncode, "stdout": cli_missing.stdout}},
})
print("wrote", path, "all_pass=", all(c["pass"] for c in cases))
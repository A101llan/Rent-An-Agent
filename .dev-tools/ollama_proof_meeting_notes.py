"""Proof: Meeting Notes agent on local llama3.2:1b via the agent's /invoke path.

Path exercised per run:  input file -> sidecar reader (apps/local-runtime/app/jobs._read_source)
-> POST /invoke on agents/meeting-notes-agent/main.py (FastAPI TestClient) -> notes_extract
-> marketplace_sdk.ollama_local.chat_json -> Ollama 127.0.0.1:11434.
Also runs the CURRENT sidecar extractor (apps/local-runtime/app/ollama_notes.py) once per input as a baseline.

Usage: python .dev-tools/ollama_proof_meeting_notes.py
Writes .dev-tools/ollama-proof-meeting-notes-agent.json
"""

from __future__ import annotations

import json
import sys
import time

from ollama_proof_lib import INPUTS, ROOT, kw_any, now_eat, read_input, run_suite, write_evidence

AGENT_DIR = ROOT / "agents" / "meeting-notes-agent"
sys.path.insert(0, str(AGENT_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import main as agent_main  # noqa: E402  agents/meeting-notes-agent/main.py

EXPECTED = json.loads((INPUTS / "meeting-notes" / "expected.json").read_text(encoding="utf-8"))
client = TestClient(agent_main.app)


def contract_ok(out):
    errs = []
    if not isinstance(out, dict):
        return False, ["output not an object"]
    if set(out) != {"summary", "decisions", "action_items", "open_questions"}:
        errs.append(f"keys {sorted(out)}")
    if not isinstance(out.get("summary"), str) or not out.get("summary", "").strip():
        errs.append("summary")
    for k in ("decisions", "open_questions"):
        if not isinstance(out.get(k), list) or not all(isinstance(x, str) for x in out[k]):
            errs.append(k)
    ai = out.get("action_items")
    if not isinstance(ai, list) or not all(
        isinstance(a, dict) and set(a) == {"owner", "task"} and all(isinstance(a[x], str) for x in a) for a in ai
    ):
        errs.append("action_items")
    return not errs, errs


def grade(name, out):
    exp = EXPECTED[name]
    detail = {"decisions": [], "decisions_forbidden_hit": [], "actions": [], "actions_forbidden_hit": [], "open_questions": []}
    pts = total = 0
    for d in exp["decisions_required"]:
        hit = any(all(kw_any(x, grp) for grp in d["all"]) for x in out["decisions"])
        detail["decisions"].append({"id": d["id"], "found": hit}); pts += hit; total += 1
    for d in exp["decisions_forbidden"]:
        if any(kw_any(x, d["any"]) for x in out["decisions"]):
            detail["decisions_forbidden_hit"].append(d["id"])
    for a in exp["actions"]:
        matches = [x for x in out["action_items"] if kw_any(x["task"], a["task"])]
        task_found = bool(matches)
        owner_ok = any(kw_any(x["owner"], a["owner"]) for x in matches)
        detail["actions"].append({"id": a["id"], "task_found": task_found, "owner_correct": owner_ok,
                                   "owners_given": [x["owner"] for x in matches]})
        pts += task_found + owner_ok; total += 2
    for a in exp.get("actions_forbidden", []):
        if any(kw_any(x["task"], a["task"]) for x in out["action_items"]):
            detail["actions_forbidden_hit"].append(a["id"])
    for q in exp["open_questions"]:
        hit = any(kw_any(x, q["any"]) for x in out["open_questions"])
        detail["open_questions"].append({"id": q["id"], "found": hit}); pts += hit; total += 1
    penalties = len(detail["decisions_forbidden_hit"]) + len(detail["actions_forbidden_hit"])
    detail["score"] = round(max(0.0, (pts - penalties) / total), 3)
    detail["points"] = f"{pts}/{total} minus {penalties} reversed/forbidden items"
    return detail


def invoke(text):
    r = client.post("/invoke", json={"input": text, "context": {}})
    return r.json()


def legacy_baseline(inputs):
    """Current sidecar extractor, unchanged (apps/local-runtime/app/ollama_notes.py)."""
    from app.ollama_notes import CANNED_MEETING_OUTPUT, meeting_notes_response

    out = []
    for name, text in inputs:
        t0 = time.perf_counter()
        r = meeting_notes_response(text)
        wall = int((time.perf_counter() - t0) * 1000)
        ok, errs = contract_ok(r["output"])
        is_canned = r["output"] == CANNED_MEETING_OUTPUT
        out.append({"input": name, "source": r.get("source"), "is_canned_output": is_canned,
                    "valid_contract": ok, "latency_ms": wall, "output": r["output"],
                    "grade": grade(name, r["output"]) if ok and not is_canned else None})
        print(f"[{now_eat()}] legacy sidecar {name}: source={r.get('source')} canned={is_canned} {wall}ms", flush=True)
    return out


if __name__ == "__main__":
    files = sorted(p for p in (INPUTS / "meeting-notes").iterdir() if p.suffix in {".txt", ".md", ".docx"})
    inputs = [(p.name, read_input(p)) for p in files]
    report = run_suite("meeting-notes-agent", invoke, inputs, grade, contract_ok)
    report["code_path"] = ("file -> apps/local-runtime/app/jobs._read_source -> POST /invoke agents/meeting-notes-agent/main.py "
                           "-> notes_extract.extract_meeting_notes -> marketplace_sdk.ollama_local.chat_json -> Ollama 127.0.0.1:11434")
    report["inputs"] = [{"file": f".dev-tools/ollama-proof/inputs/meeting-notes/{n}", "chars_read": len(t), "text": t} for n, t in inputs]
    report["expected"] = EXPECTED
    report["legacy_sidecar_baseline"] = legacy_baseline(inputs)
    path = write_evidence("ollama-proof-meeting-notes-agent.json", report)
    print(json.dumps(report["summary"], indent=1))
    print("wrote", path)
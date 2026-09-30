"""Model x prompt comparison for Meeting Notes on local Ollama (data for the default choice).

Inputs: apps/local-runtime/fixtures/sample-meeting.docx + the 3 messy transcripts in
.dev-tools/ollama-proof/inputs/meeting-notes/, all read with the sidecar's own reader
(apps/local-runtime/app/jobs._read_source).

Prompts:
  sidecar-builtin            apps/local-runtime/app/ollama_notes.py built-in prompt, single call (current sidecar default)
  sidecar-decisions-v2       apps/local-runtime/prompts/decisions-v2.json via the sidecar code path
  mn-v1-rules                marketplace_sdk/prompts/meeting-notes.v1-rules.json via notes_extract (clean+schema+validate+repair)
  mn-v2-decisions-first      marketplace_sdk/prompts/meeting-notes.v2-decisions-first.json via notes_extract (2 passes)

Usage: python .dev-tools/ollama_model_compare.py MODEL[,MODEL...] [PROMPT,PROMPT...] [INPUT-substring,...]
Appends to .dev-tools/ollama-model-compare-meeting-notes.json (one row per model/prompt/input run).
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from ollama_proof_lib import DEV, INPUTS, ROOT, ChatCapture, kw_any, now_eat, read_input, set_decoding

sys.path.insert(0, str(ROOT / "agents" / "meeting-notes-agent"))
import notes_extract  # noqa: E402
from app import config as sc_config, ollama_notes as sc_notes  # noqa: E402  (sidecar, read-only use)

OUT = DEV / "ollama-model-compare-meeting-notes.json"
EXPECTED = {**json.loads((INPUTS / "meeting-notes" / "expected.json").read_text(encoding="utf-8")),
            **json.loads((INPUTS / "meeting-notes" / "expected-fixture.json").read_text(encoding="utf-8"))}
EXPECTED.pop("_doc", None)
FILES = [ROOT / "apps" / "local-runtime" / "fixtures" / "sample-meeting.docx"] + sorted(
    p for p in (INPUTS / "meeting-notes").iterdir() if p.suffix in {".txt", ".md", ".docx"})
ALL_PROMPTS = ["sidecar-builtin", "sidecar-decisions-v2", "mn-v1-rules", "mn-v2-decisions-first", "mn-v3-decisions-cues"]


def grade(name: str, out: dict) -> dict:
    exp = EXPECTED[name]
    dec = [any(all(kw_any(x, g) for g in d["all"]) for x in out["decisions"]) for d in exp["decisions_required"]]
    forb = [d["id"] for d in exp["decisions_forbidden"] if any(kw_any(x, d["any"]) for x in out["decisions"])]
    forb += [a["id"] for a in exp.get("actions_forbidden", []) if any(kw_any(x["task"], a["task"]) for x in out["action_items"])]
    acts = []
    for a in exp["actions"]:
        m = [x for x in out["action_items"] if kw_any(x["task"], a["task"])]
        acts.append({"id": a["id"], "task_found": bool(m), "owner_correct": any(kw_any(x["owner"], a["owner"]) for x in m),
                     "owners_given": [x["owner"] for x in m]})
    oq = [any(kw_any(x, q["any"]) for x in out["open_questions"]) for q in exp["open_questions"]]
    return {
        "decision_recall": round(sum(dec) / len(dec), 3),
        "decisions_found": [d["id"] for d, ok in zip(exp["decisions_required"], dec) if ok],
        "reversed_or_forbidden_hits": forb,
        "action_recall_task_and_owner": round(sum(a["task_found"] and a["owner_correct"] for a in acts) / len(acts), 3),
        "action_recall_task_only": round(sum(a["task_found"] for a in acts) / len(acts), 3),
        "open_question_recall": round(sum(oq) / len(oq), 3),
        "actions": acts,
        "n_decisions_output": len(out["decisions"]),
        "n_actions_output": len(out["action_items"]),
    }


def run_one(model: str, prompt: str, text: str) -> dict:
    set_decoding(0.0, 42)
    with ChatCapture() as cap:
        t0 = time.perf_counter()
        err = None
        out = meta = None
        try:
            if prompt.startswith("sidecar-"):
                sc_config.OLLAMA_MODEL = model
                sc_config.PROMPT_FILE = None if prompt == "sidecar-builtin" else str(ROOT / "apps" / "local-runtime" / "prompts" / "decisions-v2.json")
                import urllib.request as _u  # sidecar uses urllib directly; capture wall time only
                r = sc_notes.extract_meeting_notes_via_ollama(text)
                if r:
                    out, meta = r["output"], r.get("meta")
                else:
                    err = sc_notes._last_error
            else:
                pid = "meeting-notes." + prompt[3:]
                r = notes_extract.extract_meeting_notes(text, model=model, prompt=pid)
                out, meta = r["output"], {k: v for k, v in r["meta"].items() if k != "raw_outputs"}
                meta["raw_outputs"] = r["meta"]["raw_outputs"]
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"[:500]
        wall = int((time.perf_counter() - t0) * 1000)
    return {"output": out, "meta": meta, "error": err, "latency_ms": wall,
            "ollama_calls": [{k: v for k, v in c.items() if k != "content"} for c in cap.calls]}


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["model"], r["prompt"]), []).append(r)
    out = []
    for (m, p), rs in sorted(groups.items()):
        ok = [r for r in rs if r["valid_json_contract"]]
        g = [r["grade"] for r in ok]
        mean = lambda k: round(statistics.mean([x[k] for x in g]), 3) if g else 0.0  # noqa: E731
        out.append({
            "model": m, "prompt": p, "runs": len(rs), "inputs": sorted({r["input"] for r in rs}),
            "json_valid_rate": round(len(ok) / len(rs), 3),
            "decision_recall_mean": mean("decision_recall"),
            "action_recall_task_and_owner_mean": mean("action_recall_task_and_owner"),
            "action_recall_task_only_mean": mean("action_recall_task_only"),
            "open_question_recall_mean": mean("open_question_recall"),
            "reversed_or_forbidden_hits_total": sum(len(x["reversed_or_forbidden_hits"]) for x in g),
            "latency_s_median": round(statistics.median([r["latency_ms"] for r in rs]) / 1000, 1),
            "latency_s_max": round(max(r["latency_ms"] for r in rs) / 1000, 1),
            "sample_meeting_docx": next(({"decision_recall": r["grade"]["decision_recall"],
                                          "action_recall": r["grade"]["action_recall_task_and_owner"]}
                                         for r in ok if r["input"] == "sample-meeting.docx"), None),
        })
    return out


def regrade() -> int:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    for r in data["rows"]:
        if r.get("output") is not None:
            r["grade"] = grade(r["input"], r["output"])
    data["expected"] = EXPECTED
    data["summary"] = summarize(data["rows"])
    data["regraded_at"] = now_eat()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(data["summary"], indent=1))
    return 0


def main() -> int:
    if sys.argv[1] == "--regrade":
        return regrade()
    models = sys.argv[1].split(",")
    prompts = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else ALL_PROMPTS
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"rows": []}
    texts = {p.name: read_input(p) for p in FILES if not only or any(o in p.name for o in only)}
    for model in models:
        for prompt in prompts:
            for name, text in texts.items():
                res = run_one(model, prompt, text)
                out = res["output"]
                row = {"model": model, "prompt": prompt, "input": name, "at": now_eat(),
                       "valid_json_contract": out is not None, **res,
                       "grade": grade(name, out) if out is not None else None}
                data["rows"].append(row)
                data.update({
                    "generated_at": now_eat(), "timezone": "Africa/Nairobi (EAT, UTC+3)",
                    "inputs": {n: {"chars_read_by_sidecar_reader": len(t)} for n, t in
                               {p.name: read_input(p) for p in FILES}.items()},
                    "expected": EXPECTED, "decoding": "temperature 0, seed 42, num_ctx 4096 (mn-*), JSON schema (mn-*, sidecar-decisions-v2)",
                    "summary": summarize(data["rows"]),
                })
                OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
                g = row["grade"] or {}
                print(f"[{now_eat()}] {model:12s} {prompt:22s} {name:40s} valid={out is not None} "
                      f"dec={g.get('decision_recall')} act={g.get('action_recall_task_and_owner')} "
                      f"{res['latency_ms']/1000:.0f}s err={res['error']}", flush=True)
    print(json.dumps(summarize(data["rows"]), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
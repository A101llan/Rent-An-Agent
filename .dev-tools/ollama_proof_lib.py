"""Shared helpers for the local-Ollama proof scripts in .dev-tools/ (not shipped)."""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".dev-tools"
INPUTS = DEV / "ollama-proof" / "inputs"
EAT = timezone(timedelta(hours=3), "EAT")  # Africa/Nairobi, no DST

for p in (ROOT / "packages" / "agent-sdk" / "src", ROOT / "apps" / "local-runtime"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import marketplace_sdk.ollama_local as ol  # noqa: E402


def now_eat() -> str:
    return datetime.now(EAT).isoformat(timespec="seconds")


def read_input(path: Path) -> str:
    """Read exactly like the local-runtime sidecar does (apps/local-runtime/app/jobs.py)."""
    from app.jobs import _read_source  # sidecar's reader (txt/md/docx)

    return _read_source(path)


class ChatCapture:
    """Wrap ollama_local._http_json to record every /api/chat reply (raw model output)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._orig = ol._http_json

    def __enter__(self):
        def wrapped(method, url, body=None, timeout=5.0):
            t0 = time.perf_counter()
            resp = self._orig(method, url, body, timeout)
            if url.endswith("/api/chat"):
                self.calls.append({
                    "content": (resp.get("message") or {}).get("content", ""),
                    "prompt_eval_count": resp.get("prompt_eval_count"),
                    "eval_count": resp.get("eval_count"),
                    "total_duration_ms": int((resp.get("total_duration") or 0) / 1e6),
                    "load_duration_ms": int((resp.get("load_duration") or 0) / 1e6),
                    "temperature": body["options"]["temperature"],
                    "seed": body["options"]["seed"],
                    "wall_ms": int((time.perf_counter() - t0) * 1000),
                })
            return resp

        ol._http_json = wrapped
        return self

    def __exit__(self, *exc):
        ol._http_json = self._orig
        return False


def set_decoding(temperature: float, seed: int) -> None:
    ol.DEFAULT_TEMPERATURE = temperature
    ol.DEFAULT_SEED = seed


def kw_any(text: str, kws: list[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in kws)


def summarize(runs: list[dict], key=lambda r: (r["input"], r["mode"])) -> list[dict]:
    groups: dict = {}
    for r in runs:
        groups.setdefault(key(r), []).append(r)
    out = []
    for (inp, mode), rs in groups.items():
        lat = [r["latency_ms"] for r in rs]
        graded = [r["grade"]["score"] for r in rs if r.get("grade")]
        out.append({
            "input": inp,
            "mode": mode,
            "runs": len(rs),
            "valid_contract": sum(1 for r in rs if r["valid_contract"]),
            "pass_rate": round(sum(1 for r in rs if r["valid_contract"]) / len(rs), 3),
            "needed_repair": sum(1 for r in rs if max(r.get("attempts") or [1]) > 1),
            "latency_ms_median": int(statistics.median(lat)),
            "latency_ms_max": max(lat),
            "quality_score_mean": round(statistics.mean(graded), 3) if graded else None,
            "distinct_outputs": len({json.dumps(r.get("output"), sort_keys=True) for r in rs}),
        })
    return out


def write_evidence(name: str, payload: dict) -> Path:
    path = DEV / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

MODES = {
    # production decoding (what the agent ships with)
    "production_t0": {"temperature": 0.0, "seeds": [42, 42, 42]},
    # sampling noise to stress JSON validity + repair path
    "stress_t0.7": {"temperature": 0.7, "seeds": [101, 202, 303]},
}


def run_suite(agent_slug: str, invoke, inputs: list[tuple[str, object]], grade, contract_ok,
              modes: dict | None = None, extra: dict | None = None) -> dict:
    """invoke(input_obj) -> /invoke JSON response. inputs: [(name, input_obj)]."""
    modes = modes or MODES
    runs = []
    chk = ol.check_ollama(probe=True)
    for mode, cfg in modes.items():
        for name, inp in inputs:
            for i, seed in enumerate(cfg["seeds"]):
                set_decoding(cfg["temperature"], seed)
                with ChatCapture() as cap:
                    t0 = time.perf_counter()
                    resp = invoke(inp)
                    wall = int((time.perf_counter() - t0) * 1000)
                out = resp.get("output") if resp.get("status") == "completed" else None
                ok, errs = contract_ok(out) if out is not None else (False, [f"status={resp.get('status')} error={resp.get('error')}"])
                g = grade(name, out) if ok else None
                runs.append({
                    "agent": agent_slug, "input": name, "mode": mode, "run": i + 1,
                    "temperature": cfg["temperature"], "seed": seed,
                    "status": resp.get("status"), "source": resp.get("source"),
                    "valid_contract": ok, "contract_errors": errs,
                    "attempts": (resp.get("meta") or {}).get("attempts"),
                    "chunks": (resp.get("meta") or {}).get("chunks"),
                    "warnings": (resp.get("meta") or {}).get("warnings"),
                    "latency_ms": wall, "usage": resp.get("usage"),
                    "output": out, "error": resp.get("error"),
                    "raw_model_outputs": [c["content"] for c in cap.calls],
                    "ollama_calls": [{k: v for k, v in c.items() if k != "content"} for c in cap.calls],
                    "grade": g,
                })
                (DEV / "ollama-proof" / f"{agent_slug}.partial.json").write_text(
                    json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")
                print(f"[{now_eat()}] {agent_slug} {mode} {name} run{i+1}: status={resp.get('status')} valid={ok} "
                      f"attempts={(resp.get('meta') or {}).get('attempts')} {wall}ms score={g and g['score']}", flush=True)
    set_decoding(0.0, 42)
    return {
        "agent_slug": agent_slug,
        "model": ol.default_model(),
        "ollama_base_url": ol.default_base_url(),
        "generated_at": now_eat(),
        "timezone": "Africa/Nairobi (EAT, UTC+3)",
        "health_check": chk.to_dict(),
        "decoding": {"num_ctx": ol.DEFAULT_NUM_CTX, "format": "JSON schema", "retries": 1, "modes": modes},
        "summary": summarize(runs),
        "runs": runs,
        **(extra or {}),
    }
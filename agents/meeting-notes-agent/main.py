"""Meeting Notes Agent — implements /invoke for container and local runtimes.

Extraction runs on a local Ollama model (default llama3.2:1b on
http://127.0.0.1:11434) via ``notes_extract`` (schema-constrained JSON,
temperature 0, validation + one repair retry, chunking).

No silent canned output: if Ollama is not running / the model is missing /
the model returns invalid JSON twice, /invoke returns ``status="failed"`` with
``error.code`` in {not_running, model_missing, wrong_host, timeout, not_ollama,
invalid_output, empty_input}.  Set MEETING_NOTES_ALLOW_CANNED=1 only for
cloud demos that must render something without a model (``source="canned"``).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from notes_extract import (  # noqa: E402  (sibling module; adds in-repo SDK to sys.path)
    MEETING_SCHEMA,
    LocalLLMError,
    check_ollama,
    extract_meeting_notes,
    make_validator,
)

CANNED_MEETING_OUTPUT = {
    "summary": "Team aligned on Q4 launch timeline and ownership of follow-ups.",
    "decisions": [
        "Ship beta by Oct 15",
        "Use weekly standup for launch blockers only",
    ],
    "action_items": [
        {"owner": "Alex", "task": "Draft launch checklist and share by Friday"},
        {"owner": "Jordan", "task": "Fix onboarding email bug before beta"},
        {"owner": "Sam", "task": "Confirm design freeze with stakeholders"},
    ],
    "open_questions": [
        "Do we need a soft launch for existing customers?",
        "Who owns post-launch metrics dashboard?",
    ],
}

CANNED_MEETING_USAGE = {"input_tokens": 90, "output_tokens": 120}


def _allow_canned() -> bool:
    return os.getenv("MEETING_NOTES_ALLOW_CANNED", "0").lower() in {"1", "true", "yes"}


def _parse_meeting_json(raw: str) -> dict | None:
    """Back-compat: parse + validate a raw model reply against the contract."""
    from marketplace_sdk.ollama_local import parse_json_loose

    try:
        normalized, errs = make_validator(raw or "", [])(parse_json_loose(raw))
    except Exception:  # noqa: BLE001
        return None
    return normalized if not errs else None


def extract_meeting_notes_via_ollama(notes: str) -> dict | None:
    """Back-compat wrapper: {output, usage} or None on any failure."""
    try:
        r = extract_meeting_notes(notes)
        return {"output": r["output"], "usage": r["usage"]}
    except Exception:  # noqa: BLE001
        return None


def meeting_notes_response(notes: str) -> dict:
    """Run local extraction; failed (not canned) on error unless explicitly allowed."""
    try:
        r = extract_meeting_notes(notes)
        return {
            "status": "completed",
            "output": r["output"],
            "usage": r["usage"],
            "source": "ollama",
            "model": r["model"],
            "meta": {k: v for k, v in r["meta"].items() if k != "raw_outputs"},
        }
    except LocalLLMError as exc:
        err = {"code": exc.code, "message": exc.message}
        usage = exc.details.get("usage") or {"input_tokens": 0, "output_tokens": 0}
    except Exception as exc:  # noqa: BLE001
        err = {"code": "internal_error", "message": str(exc)[:300]}
        usage = {"input_tokens": 0, "output_tokens": 0}
    if _allow_canned():
        return {
            "status": "completed",
            "output": dict(CANNED_MEETING_OUTPUT),
            "usage": dict(CANNED_MEETING_USAGE),
            "source": "canned",
            "error": err,
        }
    return {"status": "failed", "error": err, "usage": usage, "source": "ollama"}


app = FastAPI(title="Meeting Notes Agent")


class InvokeRequest(BaseModel):
    input: str | dict
    context: dict = {}


def _input_text(input_data: str | dict) -> str:
    if isinstance(input_data, str):
        return input_data
    for key in ("message", "text", "transcript", "notes"):
        if isinstance(input_data.get(key), str):
            return input_data[key]
    return str(input_data)


@app.post("/invoke")
async def invoke(body: InvokeRequest):
    return meeting_notes_response(_input_text(body.input))


@app.get("/health")
async def health():
    chk = check_ollama()
    return {"status": "ok", "ollama": chk.to_dict()}


__all__ = ["app", "meeting_notes_response", "MEETING_SCHEMA"]
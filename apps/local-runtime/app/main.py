"""AgentHub local-runtime FastAPI sidecar (127.0.0.1 only)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import config, session
from .jobs import cancel_job, get_job, start_meeting_notes_job
from .ollama_notes import model_available, ollama_is_up, prompt_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="AgentHub Local Runtime", version=config.VERSION)


class BindBody(BaseModel):
    session_token: str
    session_id: str | None = None


class ClaimBody(BaseModel):
    session_id: str
    session_token: str


class MeetingNotesBody(BaseModel):
    input_paths: list[str] | None = None
    pick_files: bool = False
    output_path: str | None = None


class SyncBody(BaseModel):
    session_token: str | None = None


def _raise_for(result: dict[str, Any]) -> None:
    code = int(result.get("status_code") or 400)
    detail = {k: v for k, v in result.items() if k != "status_code"}
    raise HTTPException(status_code=code, detail=detail)


@app.get("/health")
def health() -> dict[str, Any]:
    summary = session.public_summary()
    up = ollama_is_up()
    info = prompt_info()
    return {
        "ok": True,
        "ollama": "up" if up else "down",
        "version": config.VERSION,
        "model": info["model"],
        "model_available": model_available() if up else None,
        "prompt": info["prompt"],
        "frozen": config.FROZEN,
        "home": str(config.HOME),
        "api_base": config.AGENTHUB_API_BASE,
        "offline_stub_enabled": config.OFFLINE_STUB,
        "session": {"bound": summary["bound"], "mode": summary["mode"], "session_id": summary["session_id"]},
        "usage_pending": len(session.pending_usage()),
    }


@app.get("/session")
def session_info() -> dict[str, Any]:
    return session.public_summary()


@app.post("/session/claim")
def session_claim(body: ClaimBody) -> dict[str, Any]:
    """Cloud POST /api/v1/sessions/{id}/local/claim. Fails closed on any non-200."""
    result = session.claim_session(body.session_token, body.session_id)
    if not result.get("bound"):
        _raise_for(result)
    return result


@app.post("/session/bind")
def session_bind(body: BindBody) -> dict[str, Any]:
    """Alias of /session/claim (session_id required)."""
    result = session.bind_session(body.session_token, body.session_id)
    if not result.get("bound"):
        _raise_for(result)
    return result


@app.post("/jobs/meeting-notes")
def create_meeting_notes_job(body: MeetingNotesBody) -> dict[str, Any]:
    result = start_meeting_notes_job(
        input_paths=body.input_paths,
        pick_files=body.pick_files,
        output_path=body.output_path,
    )
    if "error" in result:
        _raise_for(result)
    return result


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": job["id"],
        "type": job["type"],
        "status": job["status"],
        "result_path": job.get("result_path"),
        "result": job.get("result"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "input_paths": job.get("input_paths"),
    }


@app.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, Any]:
    job = cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"id": job["id"], "status": job["status"]}


@app.get("/usage/pending")
def usage_pending() -> dict[str, Any]:
    rows = session.pending_usage()
    return {"count": len(rows), "queue_path": str(config.USAGE_QUEUE_PATH), "rows": rows}


@app.post("/usage/sync")
def usage_sync(body: SyncBody | None = None) -> dict[str, Any]:
    return session.sync_pending_usage(token_override=(body.session_token if body else None))


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    run()

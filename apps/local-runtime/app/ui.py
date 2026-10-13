"""Claim-and-run page for renters: GET /ui + small JSON endpoints under /ui/api.

Security (localhost sidecar, see docs/DECISIONS.md D7):
  * served on 127.0.0.1 only (service.serve forces it);
  * Host must be 127.0.0.1:<port> / localhost:<port> (blocks DNS rebinding);
  * state-changing requests must have no foreign Origin and carry X-AgentHub-UI: 1
    (a custom header forces a CORS preflight, which this app never approves);
  * the session token is posted once to /ui/api/claim and kept only in the sidecar
    (same .session.json as the API path); the page never stores it.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, session
from .jobs import get_job, start_meeting_notes_job
from .ollama_notes import ollama_is_up

router = APIRouter()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UI_HEADER = "x-agenthub-ui"

# Plain-language messages keyed on contract / sidecar codes.
MESSAGES: dict[str, str] = {
    "INVALID_SESSION_TOKEN": "That session ID and token don't match. Copy both again from your AgentHub hire page.",
    "unauthorized": "That session ID and token don't match. Copy both again from your AgentHub hire page.",
    "SESSION_NOT_FOUND": "AgentHub couldn't find that session. Check the session ID on your hire page.",
    "session_not_found": "AgentHub couldn't find that session. Check the session ID on your hire page.",
    "SESSION_NOT_LOCAL": "This hire runs in the cloud, not on your PC. Hire the 'Local' version of the agent to use it here.",
    "not_local_session": "This hire runs in the cloud, not on your PC. Hire the 'Local' version of the agent to use it here.",
    "SESSION_EXPIRED": "This session has expired or ended. Extend it or hire again on AgentHub.",
    "session_expired": "This session has expired or ended. Extend it or hire again on AgentHub.",
    "VALIDATION_ERROR": "AgentHub rejected the request as invalid. Check the session ID and try again.",
    "validation_error": "AgentHub rejected the request as invalid. Check the session ID and try again.",
    "api_unreachable": "Can't reach AgentHub right now. Check your internet connection and try again.",
    "session_not_bound": "Claim your session first (step 1).",
    "low_memory": "Your PC doesn't have enough free memory to run the AI model safely. Close other apps "
                  "(browser tabs, Office, games) and try again. Nothing was processed and you were not charged.",
    "timeout": "The AI model took too long and was stopped. Try a shorter document or close other apps, then "
               "try again. You were not charged.",
    "ollama_down": "The local AI engine (Ollama) isn't running. Start 'Ollama' from the Start menu "
                   "(or install it from ollama.com/download/windows), then try again.",
    "model_missing": "The AI model isn't downloaded yet. Open 'Setup - check Ollama and model' from the Start menu "
                     "(or run 'ollama pull <model>'), then try again. You were not charged.",
    "extraction_failed": "The AI model couldn't produce meeting notes for this document. Try again, or try "
                         "a different document. You were not charged.",
    "unsupported_file_type": "Please choose a Word document (.docx).",
    "upload_too_large": "That file is too large (limit 20 MB).",
    "upload_not_found": "The uploaded file was not found. Pick the document again.",
    "forbidden_origin": "This page can only be used from this PC's AgentHub Local window.",
}


def friendly(code: str | None, fallback: str | None = None) -> str:
    return MESSAGES.get(code or "", fallback or "Something went wrong. Please try again.")


def classify_job_error(job: dict[str, Any]) -> str:
    code = job.get("error_code")
    if code in ("low_memory", "ollama_down", "model_missing", "timeout"):
        return code
    text = (job.get("error") or "").lower()
    if "session_not_bound" in text:
        return "session_not_bound"
    if "session_expired" in text:
        return "session_expired"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if code == "extraction_failed" or "ollama" in text:
        return "extraction_failed" if ollama_is_up() else "ollama_down"
    return "extraction_failed"


def _err(status: int, code: str, message: str | None = None, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "code": code,
                                                     "message": message or friendly(code), **extra})


# ---------------------------------------------------------------- guard

def _allowed_hosts() -> set[str]:
    return {f"127.0.0.1:{config.PORT}", f"localhost:{config.PORT}"}


class LocalOnlyGuard(BaseHTTPMiddleware):
    """Reject DNS-rebinding hosts on /ui*, and cross-origin state-changing requests everywhere."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        host = (request.headers.get("host") or "").lower()
        origin = request.headers.get("origin")
        if path.startswith("/ui") and host not in _allowed_hosts() and host != "testserver":
            return _err(403, "forbidden_origin", "Bad Host header")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            allowed_origins = {f"http://{h}" for h in _allowed_hosts()} | {"http://testserver"}
            if origin and origin.lower() not in allowed_origins:
                return _err(403, "forbidden_origin")
            if path.startswith("/ui/api") and request.headers.get(UI_HEADER) != "1":
                return _err(403, "forbidden_origin", "Missing X-AgentHub-UI header")
        return await call_next(request)


# ---------------------------------------------------------------- page

def _ui_html_path() -> Path | None:
    for base in (config.INSTALL_DIR, config.RESOURCE_ROOT, config.PACKAGE_ROOT):
        p = base / "ui" / "index.html"
        if p.exists():
            return p
    return None


@router.get("/ui", response_class=HTMLResponse)
def ui_page() -> HTMLResponse:
    p = _ui_html_path()
    if not p:
        return HTMLResponse("<h1>AgentHub Local</h1><p>UI files are missing; reinstall.</p>", status_code=500)
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                   "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    })


# ---------------------------------------------------------------- api

class UiClaim(BaseModel):
    session_id: str
    session_token: str


class UiRun(BaseModel):
    upload_id: str
    onboarding: dict[str, str] = {}


def onboarding_questions(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    qs = ((manifest or {}).get("onboarding") or {}).get("questions") or []
    out = []
    for q in qs:
        if isinstance(q, dict) and q.get("id") and q.get("question"):
            item: dict[str, Any] = {"id": str(q["id"]), "question": str(q["question"]),
                                    "placeholder": str(q.get("placeholder") or "")}
            # Closed-set answers (same contract as the web widget): render as a dropdown.
            opts = q.get("options")
            if isinstance(opts, list):
                opts = [str(o) for o in opts if isinstance(o, (str, int, float)) and str(o).strip()]
                if opts:
                    item["options"] = opts
                    item["allow_other"] = bool(q.get("allow_other"))
            out.append(item)
    return out


def _session_view() -> dict[str, Any]:
    b = session.get_bound()
    s = session.public_summary()
    return {"bound": s["bound"], "session_id": s["session_id"], "expires_at": s["expires_at"],
            "mode": s["mode"], "agent_slug": (b.get("remote") or {}).get("agent_slug"),
            "questions": onboarding_questions(b.get("manifest"))}


@router.get("/ui/api/state")
def ui_state() -> dict[str, Any]:
    return {"ok": True, "ollama": "up" if ollama_is_up() else "down", "session": _session_view()}


@router.post("/ui/api/claim")
def ui_claim(body: UiClaim):
    r = session.claim_session(body.session_token, body.session_id)
    if not r.get("bound"):
        code = r.get("api_code") or r.get("error") or "claim_failed"
        return _err(int(r.get("status_code") or 400), code, friendly(code, r.get("message")))
    return {"ok": True, "session": _session_view()}


_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def _upload_dir() -> Path:
    d = config.HOME / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/ui/api/upload")
async def ui_upload(request: Request, filename: str = "document.docx"):
    base = re.split(r"[\\/]", filename)[-1]
    name = _SAFE.sub("_", base).strip(". ")[:120] or "document.docx"
    if not name.lower().endswith(".docx"):
        return _err(400, "unsupported_file_type")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        return _err(413, "upload_too_large")
    if not data.startswith(b"PK"):
        return _err(400, "unsupported_file_type")
    upload_id = uuid.uuid4().hex
    folder = _upload_dir() / upload_id
    folder.mkdir()
    (folder / name).write_bytes(data)
    return {"ok": True, "upload_id": upload_id, "filename": name, "bytes": len(data)}


@router.post("/ui/api/run")
def ui_run(body: UiRun):
    if not re.fullmatch(r"[0-9a-f]{32}", body.upload_id):
        return _err(400, "upload_not_found")
    folder = _upload_dir() / body.upload_id
    files = list(folder.glob("*.docx")) if folder.is_dir() else []
    if not files:
        return _err(404, "upload_not_found")
    onboarding = {str(k)[:64]: str(v)[:1000] for k, v in (body.onboarding or {}).items()}
    out = config.OUT_DIR / f"meeting-notes-{body.upload_id[:8]}.json"
    r = start_meeting_notes_job(input_paths=[str(files[0])], output_path=str(out), onboarding=onboarding)
    if "error" in r:
        return _err(int(r.get("status_code") or 400), r["error"], friendly(r["error"], r.get("detail")))
    return {"ok": True, "job_id": r["job_id"]}


@router.get("/ui/api/jobs/{job_id}")
def ui_job(job_id: str):
    job = get_job(job_id)
    if not job:
        return _err(404, "job_not_found", "Job not found.")
    out: dict[str, Any] = {"ok": True, "job_id": job_id, "status": job["status"]}
    if job["status"] == "failed":
        code = classify_job_error(job)
        msg = friendly(code)
        mem = job.get("memory")
        if code == "low_memory" and mem:
            msg = (f"Not enough free memory: {mem['free_mb']} MB of RAM free, {mem['required_mb']} MB needed. "
                   "Close other apps (browser tabs, Office, games), then retry. "
                   "Nothing was processed and you were not charged.")
        if job.get("error_code") in ("ollama_down", "model_missing") and job.get("error"):
            msg = job["error"]
        out.update({"ok": False, "code": code, "message": msg, "memory": mem})
    elif job["status"] == "completed":
        res = job.get("result") or {}
        trunc = res.get("input_truncated")
        out.update({
            "output": res.get("output"),
            "input_truncated": trunc,
            "truncation_message": (trunc or {}).get("message"),
            "warnings": res.get("warnings") or [],
            "onboarding": res.get("onboarding"),
            "model_used": res.get("model_used"),
            "model_fallback": res.get("model_fallback"),
            "json_url": f"/ui/api/jobs/{job_id}/json",
            "result_path": res.get("result_path"),
        })
    return out


@router.get("/ui/api/jobs/{job_id}/json")
def ui_job_json(job_id: str):
    job = get_job(job_id)
    path = job and job.get("result_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "result not found")
    return FileResponse(path, media_type="application/json", filename=Path(path).name)

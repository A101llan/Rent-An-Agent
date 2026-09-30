"""In-memory meeting-notes job store and runner."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, session
from .ollama_notes import meeting_notes_response

logger = logging.getLogger("local-runtime.jobs")

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".docx"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_docx(path: Path) -> str:
    try:
        import docx  # type: ignore  # python-docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise RuntimeError(
            "python-docx not installed; pip install -r requirements.txt to read .docx"
        ) from exc
    document = docx.Document(str(path))
    lines: list[str] = []
    # Walk body in document order so tables stay next to their headings.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if text and (not cells or cells[-1] != text):  # merged cells repeat
                        cells.append(text)
                if cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return _read_docx(path)
    raise RuntimeError(f"unsupported file type: {suffix or '(none)'} - use .txt/.md/.docx")


def _pick_files_tk() -> list[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("tkinter filedialog unavailable") from exc
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    paths = filedialog.askopenfilenames(
        title="Select meeting notes files",
        filetypes=[
            ("Meeting notes", "*.docx *.txt *.md *.markdown"),
            ("Word", "*.docx"),
            ("Text / Markdown", "*.txt *.md *.markdown"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return [str(p) for p in paths]


def _output_path(input_paths: list[Path], requested: str | None = None) -> Path:
    if requested:
        return Path(requested)
    if input_paths:
        return input_paths[0].parent / "meeting-notes.json"
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    return config.OUT_DIR / "meeting-notes.json"


def extract_to_file(
    input_paths: list[Path],
    out_path: Path,
    *,
    job_id: str,
    report_usage: bool = True,
    session_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read inputs, run Ollama extraction, report usage, write JSON. Shared by server + CLI."""
    chunks: list[str] = []
    for path in input_paths:
        if not path.exists():
            raise FileNotFoundError(f"input not found: {path}")
        chunks.append(_read_source(path))
    if not any(c.strip() for c in chunks):
        raise RuntimeError("no input text - provide input_paths or pick_files")

    notes = "\n\n---\n\n".join(chunks)
    result = meeting_notes_response(notes)

    # Canned demo output (LOCAL_RUNTIME_ALLOW_CANNED=1) is never metered.
    metered = report_usage and result.get("source") == "ollama"
    usage_report = session.report_job_usage(result.get("usage") or {}, job_id=job_id) if metered else []
    payload = {
        "status": result["status"],
        "output": result["output"],
        "usage": result["usage"],
        "source": result.get("source"),
        "model_meta": result.get("meta"),
        "job_id": job_id,
        "input_paths": [str(p) for p in input_paths],
        "session": session_info if session_info is not None else session.public_summary(),
        "usage_report": usage_report,
        "written_at": _now_iso(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["result_path"] = str(out_path)
    return payload


def _run_job(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("cancel_requested"):
            if job:
                job["status"] = "cancelled"
                job["finished_at"] = _now_iso()
            return
        job["status"] = "running"
        job["started_at"] = _now_iso()
        input_paths = [Path(p) for p in job.get("input_paths") or []]
        requested_out = job.get("output_path")

    try:
        denied = session.require_active()
        if denied:
            raise RuntimeError(f"{denied['error']}: {denied['detail']}")

        out_path = _output_path(input_paths, requested_out)
        payload = extract_to_file(input_paths, out_path, job_id=job_id)

        with _lock:
            job = _jobs[job_id]
            if job.get("cancel_requested"):
                job["status"] = "cancelled"
            else:
                job["status"] = "completed"
                job["result_path"] = str(out_path)
                job["result"] = {
                    "status": payload["status"],
                    "output": payload["output"],
                    "usage": payload["usage"],
                    "source": payload.get("source"),
                    "model_meta": payload.get("model_meta"),
                    "result_path": str(out_path),
                    "session": payload["session"],
                    "usage_report": payload["usage_report"],
                }
            job["finished_at"] = _now_iso()
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = str(exc)
            job["finished_at"] = _now_iso()


def start_meeting_notes_job(
    input_paths: list[str] | None = None,
    pick_files: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    denied = session.require_active()
    if denied:
        return denied

    paths = list(input_paths or [])
    if pick_files and not paths:
        try:
            picked = _pick_files_tk()
        except Exception as exc:
            return {
                "error": "pick_files_unavailable",
                "detail": str(exc),
                "hint": "pass input_paths for CLI/headless, or ensure tkinter GUI works",
                "status_code": 501,
            }
        if not picked:
            return {"error": "no_files_selected", "status_code": 400}
        paths = picked

    if not paths:
        return {
            "error": "input_required",
            "detail": "provide input_paths and/or pick_files",
            "status_code": 400,
        }
    bad = [p for p in paths if Path(p).suffix.lower() not in SUPPORTED_SUFFIXES]
    if bad:
        return {
            "error": "unsupported_file_type",
            "detail": f"supported: {sorted(SUPPORTED_SUFFIXES)}",
            "files": bad,
            "status_code": 400,
        }

    job_id = str(uuid.uuid4())
    record = {
        "id": job_id,
        "type": "meeting-notes",
        "status": "queued",
        "input_paths": paths,
        "output_path": output_path,
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "result_path": None,
        "result": None,
        "error": None,
        "cancel_requested": False,
    }
    with _lock:
        _jobs[job_id] = record

    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        job["cancel_requested"] = True
        if job["status"] in {"queued", "running"}:
            job["status"] = "cancelled"
            job["finished_at"] = _now_iso()
        return dict(job)

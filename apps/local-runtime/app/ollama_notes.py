"""Meeting-notes extraction via local Ollama (ported from agents/meeting-notes-agent/main.py).

Model and prompt come from config (owned by the Ollama Integrator):
  LOCAL_RUNTIME_MODEL (fallback OLLAMA_MODEL, then config.defaults.json, then llama3.2:1b)
  LOCAL_RUNTIME_PROMPT_FILE (unset -> config.defaults.json prompt_file, i.e. prompts/decisions-v2.json;
                             "" or "builtin" -> built-in prompt below)
"""

from __future__ import annotations

import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger("local-runtime.ollama")

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

BUILTIN_PROMPT_NAME = "builtin"
DEFAULT_USER_TEMPLATE = "Extract meeting notes from the following text:\n\n{notes}"

_last_error: str | None = None


def _meeting_extraction_prompt(notes: str) -> tuple[str, str]:
    """Built-in prompt (unchanged default)."""
    system = (
        "You extract structured meeting notes. "
        "Respond with ONLY valid JSON (no markdown fences, no commentary) matching this schema:\n"
        '{"summary": string, "decisions": [string], '
        '"action_items": [{"owner": string, "task": string}], '
        '"open_questions": [string]}\n'
        "If a field is unknown use an empty string or empty list."
    )
    user = DEFAULT_USER_TEMPLATE.format(notes=notes)
    return system, user


def _resolve_prompt_path(raw: str) -> Path | None:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p if p.exists() else None
    for base in (config.HOME, config.INSTALL_DIR, config.RESOURCE_ROOT, Path.cwd()):
        cand = base / p
        if cand.exists():
            return cand
    return None


def load_prompt_override() -> dict[str, Any] | None:
    """Parse LOCAL_RUNTIME_PROMPT_FILE. Returns None (built-in) if unset or invalid.

    .txt  -> whole file is the system prompt.
    .json -> {"name"?, "system": str, "user_template"?: str with {notes},
              "examples"?: [{"input": str, "output": obj}], "format"?: "json"|schema,
              "options"?: {...ollama request options}}
    """
    raw = config.PROMPT_FILE
    if not raw:
        return None
    path = _resolve_prompt_path(raw)
    if not path:
        logger.warning("LOCAL_RUNTIME_PROMPT_FILE not found (%s) - using built-in prompt", raw)
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
            if not isinstance(data, dict) or not isinstance(data.get("system"), str):
                raise ValueError("prompt JSON needs a string 'system'")
        else:
            data = {"system": text}
        data.setdefault("name", path.stem)
        tmpl = data.get("user_template") or DEFAULT_USER_TEMPLATE
        if "{notes}" not in tmpl:
            raise ValueError("user_template must contain {notes}")
        data["user_template"] = tmpl
        data["path"] = str(path)
        return data
    except Exception as exc:
        logger.warning("invalid prompt file %s (%s) - using built-in prompt", path, exc)
        return None


def prompt_info() -> dict[str, Any]:
    ov = load_prompt_override()
    return {"model": config.OLLAMA_MODEL, "prompt": ov["name"] if ov else BUILTIN_PROMPT_NAME,
            "prompt_file": ov["path"] if ov else None}


def _safety_options(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge prompt-file options with sidecar caps; caps always win (lower num_predict kept)."""
    opts = dict(extra or {})
    cap = config.OLLAMA_NUM_PREDICT
    cur = opts.get("num_predict")
    opts["num_predict"] = min(cur, cap) if isinstance(cur, int) and cur > 0 else cap
    opts["num_ctx"] = config.OLLAMA_NUM_CTX
    return opts


def _build_request(notes: str) -> tuple[dict[str, Any], str]:
    body, name = _build_request_raw(notes)
    if not body.get("format") or (body.get("format") == "json" and not load_prompt_override()):
        body["format"] = config.OLLAMA_FORMAT
    body["options"] = _safety_options(body.get("options"))
    body["options"].setdefault("temperature", 0)  # prompt file's own temperature wins
    return body, name


def _build_request_raw(notes: str) -> tuple[dict[str, Any], str]:
    ov = load_prompt_override()
    if not ov:
        system, user = _meeting_extraction_prompt(notes)
        body = {
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        return body, BUILTIN_PROMPT_NAME
    messages: list[dict[str, str]] = [{"role": "system", "content": ov["system"]}]
    for ex in ov.get("examples") or []:
        if isinstance(ex, dict) and "input" in ex and "output" in ex:
            messages.append({"role": "user", "content": ov["user_template"].format(notes=ex["input"])})
            out = ex["output"]
            messages.append({"role": "assistant", "content": out if isinstance(out, str) else json.dumps(out)})
    messages.append({"role": "user", "content": ov["user_template"].format(notes=notes)})
    body: dict[str, Any] = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": ov.get("format") or "json",
    }
    if isinstance(ov.get("options"), dict):
        body["options"] = ov["options"]
    return body, str(ov["name"])


def _parse_meeting_json(raw: str) -> dict | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    for key in ("summary", "decisions", "action_items", "open_questions"):
        if key not in data:
            return None
    if not isinstance(data["summary"], str):
        return None
    if not isinstance(data["decisions"], list) or not all(
        isinstance(x, str) for x in data["decisions"]
    ):
        return None
    if not isinstance(data["open_questions"], list) or not all(
        isinstance(x, str) for x in data["open_questions"]
    ):
        return None
    if not isinstance(data["action_items"], list):
        return None
    for item in data["action_items"]:
        if not isinstance(item, dict):
            return None
        if "owner" not in item or "task" not in item:
            return None
        if not isinstance(item["owner"], str) or not isinstance(item["task"], str):
            return None
    return {
        "summary": data["summary"],
        "decisions": data["decisions"],
        "action_items": [{"owner": i["owner"], "task": i["task"]} for i in data["action_items"]],
        "open_questions": data["open_questions"],
    }


def ollama_is_up() -> bool:
    """Return True if Ollama /api/tags responds."""
    try:
        req = urllib.request.Request(f"{config.OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def ollama_models() -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return None


def model_available(model: str | None = None) -> bool | None:
    model = model or config.OLLAMA_MODEL
    names = ollama_models()
    if names is None:
        return None
    want = model if ":" in model else f"{model}:latest"
    return want in names or model in names


def extract_meeting_notes_via_ollama(notes: str) -> dict | None:
    """Call local Ollama for structured meeting extraction. None on any failure."""
    global _last_error
    _last_error = None
    try:
        body, prompt_name = _build_request(notes)
        req = urllib.request.Request(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
        wall = time.perf_counter() - t0
        data = json.loads(raw)
        content = (data.get("message") or {}).get("content", "")
        parsed = _parse_meeting_json(content)
        if not parsed:
            _last_error = f"model output did not match schema: {content[:200]!r}"
            return None
        usage = {
            "input_tokens": data.get("prompt_eval_count") or max(1, len(notes.split())),
            "output_tokens": data.get("eval_count") or max(1, len(content.split())),
        }
        ns = 1e9
        meta = {
            "model": body["model"],
            "prompt": prompt_name,
            "wall_seconds": round(wall, 2),
            "load_seconds": round((data.get("load_duration") or 0) / ns, 2),
            "prompt_eval_seconds": round((data.get("prompt_eval_duration") or 0) / ns, 2),
            "eval_seconds": round((data.get("eval_duration") or 0) / ns, 2),
        }
        return {"output": parsed, "usage": usage, "source": "ollama", "meta": meta}
    except (TimeoutError, socket.timeout):
        _last_error = (f"ollama timed out after {config.OLLAMA_TIMEOUT_SECONDS:.0f}s (timeout_s / "
                       "LOCAL_RUNTIME_TIMEOUT_S); the model is too slow on this PC or Ollama is stuck")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        _last_error = f"ollama HTTP {exc.code}: {detail}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            _last_error = f"ollama timed out after {config.OLLAMA_TIMEOUT_SECONDS:.0f}s (timeout_s / LOCAL_RUNTIME_TIMEOUT_S)"
        else:
            _last_error = f"ollama unreachable at {config.OLLAMA_BASE_URL}: {exc.reason}"
    except Exception as exc:
        _last_error = f"ollama call failed: {exc}"
    logger.warning("extraction failed: %s", _last_error)
    return None


class ExtractionError(RuntimeError):
    code = "extraction_failed"


class LowMemoryError(ExtractionError):
    code = "low_memory"

    def __init__(self, message: str, free_mb: int | None = None, required_mb: int | None = None):
        super().__init__(message)
        self.free_mb, self.required_mb = free_mb, required_mb


def model_loaded(model: str | None = None) -> bool:
    """True if Ollama already has the model resident (/api/ps)."""
    model = model or config.OLLAMA_MODEL
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_BASE_URL}/api/ps", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = {m.get("name") or m.get("model") for m in data.get("models", [])}
        want = model if ":" in model else f"{model}:latest"
        return want in names or model in names
    except Exception:
        return False


def free_ram_mb() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available // (1024 * 1024))
    except Exception:
        return None


def check_memory() -> dict[str, Any]:
    """Raise LowMemoryError if there is not enough free RAM to run safely."""
    free = free_ram_mb()
    loaded = model_loaded()
    need = config.MIN_FREE_MB_WARM if loaded else config.MIN_FREE_MB_COLD
    info = {"free_mb": free, "required_mb": need, "model_loaded": loaded}
    if free is not None and free < need:
        raise LowMemoryError(free_mb=free, required_mb=need, message=
            f"Not enough free memory to run the meeting-notes model safely: {free} MB of RAM free, "
            f"{need} MB needed. Close other apps (browser tabs, Office, etc.) to free about "
            f"{need - free} MB, then retry. "
            "Nothing was processed and no usage was reported."
        )
    return info


def runtime_notices() -> list[str]:
    """Persistent, human-readable problems (Ollama down, model missing, low RAM). Empty = ready."""
    notices: list[str] = []
    if not ollama_is_up():
        notices.append(f"OLLAMA NOT RUNNING: nothing answers at {config.OLLAMA_BASE_URL}. Start Ollama "
                       "(or install it from https://ollama.com/download/windows). Jobs will fail until then.")
    elif model_available() is False:
        notices.append(f"MODEL MISSING: {config.OLLAMA_MODEL!r} is not pulled. Run 'ollama pull "
                       f"{config.OLLAMA_MODEL}' or 'agenthub-local-runtime.exe setup'.")
    free = free_ram_mb()
    need = config.MIN_FREE_MB_COLD
    if free is not None and free < need and not model_loaded():
        notices.append(f"LOW MEMORY: {free} MB free, {need} MB needed to load the model. Close other apps; "
                       "jobs will be refused until there is room.")
    return notices


def meeting_notes_response(notes: str) -> dict:
    """Ollama extraction. Canned output only if LOCAL_RUNTIME_ALLOW_CANNED=1 (labeled).

    Raises LowMemoryError before calling Ollama when free RAM is below the threshold.
    """
    memory = check_memory()
    result = extract_meeting_notes_via_ollama(notes)
    if result:
        result["meta"]["memory"] = memory
    if result:
        return {
            "status": "completed",
            "output": result["output"],
            "usage": result["usage"],
            "source": "ollama",
            "meta": result["meta"],
        }
    if config.ALLOW_CANNED:
        return {
            "status": "completed",
            "output": dict(CANNED_MEETING_OUTPUT),
            "usage": dict(CANNED_MEETING_USAGE),
            "source": "canned",
            "meta": {"model": None, "prompt": None, "warning": f"CANNED DEMO OUTPUT ({_last_error})"},
        }
    raise ExtractionError(
        f"extraction failed with model {config.OLLAMA_MODEL!r}: {_last_error}. "
        "Check Ollama is running and the model is pulled (ollama pull <model>)."
    )

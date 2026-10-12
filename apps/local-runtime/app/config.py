"""Local-runtime configuration.

Precedence: environment variable > config.json in the data dir > default.
Model and prompt also read the checked-in config.defaults.json (next to app/ in dev,
next to the exe when installed): env var > config.json > config.defaults.json > hardcoded.
Frozen (installed) builds keep state under %LOCALAPPDATA%\\AgentHub\\LocalRuntime.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
VERSION = "0.1.0"  # matches manifest runtime.min_sidecar_version; override via LOCAL_RUNTIME_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
# Where bundled read-only resources (prompts/) live: PyInstaller dir when frozen.
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PACKAGE_ROOT))
INSTALL_DIR = Path(sys.executable).resolve().parent if FROZEN else PACKAGE_ROOT


def _default_home() -> Path:
    if FROZEN:
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AgentHub" / "LocalRuntime"
    return PACKAGE_ROOT


HOME = Path(os.getenv("LOCAL_RUNTIME_HOME", str(_default_home())))
CONFIG_FILE = HOME / "config.json"


def _file_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_FILE = _file_config()

# Checked-in defaults for model + prompt (shipped with the code, not user-edited).
DEFAULTS_FILE = next(
    (d / "config.defaults.json" for d in (INSTALL_DIR, RESOURCE_ROOT) if (d / "config.defaults.json").exists()),
    INSTALL_DIR / "config.defaults.json",
)


def _defaults_config() -> dict:
    try:
        data = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_DEFAULTS = _defaults_config()


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None and value != "":
        return value
    value = _FILE.get(name)
    if value is not None and value != "":
        return str(value)
    return default


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


VERSION = _get("LOCAL_RUNTIME_VERSION", VERSION) or VERSION
HOST = _get("HOST", "127.0.0.1") or "127.0.0.1"
PORT = int(_get("PORT", "8765") or "8765")

AGENTHUB_API_BASE = (_get("AGENTHUB_API_BASE", "http://127.0.0.1:8000") or "").rstrip("/")
API_TIMEOUT_SECONDS = float(_get("AGENTHUB_API_TIMEOUT", "5") or "5")

OLLAMA_BASE_URL = (_get("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
# Model + prompt are owned by the Ollama Integrator; the sidecar only reads config.
# LOCAL_RUNTIME_MODEL is sidecar-specific (preferred); OLLAMA_MODEL is honoured for
# back-compat. Then config.defaults.json "model", then the hardcoded llama3.2:1b.
DEFAULT_MODEL = "llama3.2:1b"
OLLAMA_MODEL = (
    _get("LOCAL_RUNTIME_MODEL") or _get("OLLAMA_MODEL") or str(_DEFAULTS.get("model") or "") or DEFAULT_MODEL
)
OLLAMA_TIMEOUT_SECONDS = float(_get("OLLAMA_TIMEOUT", "300") or "300")
# Prompt file (.json or .txt, see README). LOCAL_RUNTIME_PROMPT_FILE (env, then config.json)
# wins; an explicit empty value or "builtin" selects the built-in prompt. If it is not set
# anywhere, config.defaults.json "prompt_file" is used, resolved against that file's folder
# (the package/install dir, never the cwd). A missing/invalid file -> built-in prompt.
# Relative LOCAL_RUNTIME_PROMPT_FILE paths resolve against HOME (data dir), then the install dir.
BUILTIN_PROMPT_VALUES = {"", "builtin", "built-in", "none"}


def _prompt_file_setting() -> str | None:
    for raw in (os.environ.get("LOCAL_RUNTIME_PROMPT_FILE"), _FILE.get("LOCAL_RUNTIME_PROMPT_FILE")):
        if raw is not None:
            raw = str(raw).strip()
            return None if raw.lower() in BUILTIN_PROMPT_VALUES else raw
    raw = str(_DEFAULTS.get("prompt_file") or "").strip()
    if raw.lower() in BUILTIN_PROMPT_VALUES:
        return None
    p = Path(raw)
    return str(p if p.is_absolute() else DEFAULTS_FILE.parent / p)


PROMPT_FILE = _prompt_file_setting()
# Canned demo output when Ollama fails. Off by default: a failed extraction
# fails the job (and reports no usage) instead of returning fake notes.
ALLOW_CANNED = _truthy(_get("LOCAL_RUNTIME_ALLOW_CANNED"))

# Dev/offline stub: ONLY used when the cloud API is unreachable. Any HTTP
# response from claim other than 200 fails closed regardless of this flag.
OFFLINE_STUB = _truthy(_get("LOCAL_RUNTIME_OFFLINE_STUB"))

OUT_DIR = Path(_get("LOCAL_RUNTIME_OUT", str(HOME / "out")) or HOME / "out")
LOG_DIR = Path(_get("LOCAL_RUNTIME_LOG_DIR", str(HOME / "logs")) or HOME / "logs")
SESSION_STORE_PATH = Path(_get("LOCAL_RUNTIME_SESSION_FILE", str(HOME / ".session.json")) or "")
USAGE_QUEUE_PATH = Path(_get("LOCAL_RUNTIME_USAGE_QUEUE", str(HOME / "usage-pending.jsonl")) or "")
USAGE_FAILED_PATH = Path(_get("LOCAL_RUNTIME_USAGE_FAILED", str(HOME / "usage-failed.jsonl")) or "")

CLAIM_PATH_TEMPLATE = "/api/v1/sessions/{session_id}/local/claim"
USAGE_PATH_TEMPLATE = "/api/v1/sessions/{session_id}/usage"

for _d in (HOME, OUT_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

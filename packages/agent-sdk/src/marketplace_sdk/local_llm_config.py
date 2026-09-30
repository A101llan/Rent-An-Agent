"""Single config source for local-Ollama model + prompt choice (AgentHub-wide).

Resolution order (first non-empty wins):
  model        AGENTHUB_LOCAL_MODEL  > LOCAL_RUNTIME_MODEL > OLLAMA_MODEL    > defaults file "model"
  ollama url   AGENTHUB_OLLAMA_URL   > OLLAMA_BASE_URL                       > defaults file "ollama_url"
  prompt       AGENTHUB_MEETING_NOTES_PROMPT (prompt id or path to .json)    > defaults file "prompts"."meeting-notes"
  num_ctx      AGENTHUB_OLLAMA_NUM_CTX > OLLAMA_NUM_CTX                      > defaults file "num_ctx"
  defaults     AGENTHUB_LOCAL_LLM_CONFIG (path to a JSON file) > local_llm_defaults.json next to this module

Prompt files live in ``marketplace_sdk/prompts/<id>.json`` and use the same
shape as apps/local-runtime prompt files ({name, system, user_template,
examples, format, options}) plus optional ``strategy``/``passes``/``leak_tokens``.

CLI:  python -m marketplace_sdk.local_llm_config   -> prints the resolved config as JSON
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULTS_FILE = HERE / "local_llm_defaults.json"
PROMPTS_DIR = HERE / "prompts"


@dataclass(frozen=True)
class LocalLLMConfig:
    model: str
    ollama_url: str
    num_ctx: int
    keep_alive: str
    meeting_notes_prompt: str
    defaults_file: str
    sources: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _env(*names: str) -> tuple[str | None, str | None]:
    for n in names:
        v = os.getenv(n)
        if v not in (None, ""):
            return v, f"env:{n}"
    return None, None


def _defaults() -> tuple[dict, Path]:
    raw, _ = _env("AGENTHUB_LOCAL_LLM_CONFIG")
    path = Path(raw).expanduser() if raw else DEFAULTS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data if isinstance(data, dict) else {}), path
    except Exception:
        return {}, path


def load_config() -> LocalLLMConfig:
    d, path = _defaults()
    src: dict = {}

    def pick(key: str, envs: tuple[str, ...], file_val, hard_default):
        v, s = _env(*envs)
        if v is None and file_val not in (None, ""):
            v, s = file_val, f"file:{path.name}"
        if v is None:
            v, s = hard_default, "builtin"
        src[key] = s
        return v

    model = pick("model", ("AGENTHUB_LOCAL_MODEL", "LOCAL_RUNTIME_MODEL", "OLLAMA_MODEL"), d.get("model"), "llama3.2:1b")
    url = pick("ollama_url", ("AGENTHUB_OLLAMA_URL", "OLLAMA_BASE_URL"), d.get("ollama_url"), "http://127.0.0.1:11434")
    ctx = pick("num_ctx", ("AGENTHUB_OLLAMA_NUM_CTX", "OLLAMA_NUM_CTX"), d.get("num_ctx"), 4096)
    ka = pick("keep_alive", ("AGENTHUB_OLLAMA_KEEP_ALIVE", "OLLAMA_KEEP_ALIVE"), d.get("keep_alive"), "15m")
    prompt = pick("meeting_notes_prompt", ("AGENTHUB_MEETING_NOTES_PROMPT",),
                  (d.get("prompts") or {}).get("meeting-notes"), "meeting-notes.v2-decisions-first")
    return LocalLLMConfig(model=str(model), ollama_url=str(url).rstrip("/"), num_ctx=int(ctx),
                          keep_alive=str(ka), meeting_notes_prompt=str(prompt),
                          defaults_file=str(path), sources=src)


def resolve_prompt_path(prompt: str) -> Path:
    """Prompt id (e.g. 'meeting-notes.v2-decisions-first') or a path to a .json/.txt file."""
    p = Path(prompt).expanduser()
    if p.suffix and p.exists():
        return p
    cand = PROMPTS_DIR / f"{prompt}.json"
    if cand.exists():
        return cand
    raise FileNotFoundError(f"prompt {prompt!r} not found (looked for a file path and {cand})")


def load_prompt(prompt: str | None = None) -> dict:
    """Load a prompt file. Default: the configured meeting-notes prompt."""
    prompt = prompt or load_config().meeting_notes_prompt
    path = resolve_prompt_path(prompt)
    if path.suffix.lower() == ".txt":
        data = {"system": path.read_text(encoding="utf-8")}
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("name", path.stem)
    data.setdefault("strategy", "single")
    data.setdefault("user_template", "Extract meeting notes from the following text:\n\n{notes}")
    data["path"] = str(path)
    return data


if __name__ == "__main__":
    print(json.dumps(load_config().to_dict(), indent=2))
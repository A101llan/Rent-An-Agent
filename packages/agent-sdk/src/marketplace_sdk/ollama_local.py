"""Local Ollama client + device health check for AgentHub agents (stdlib only).

Used by agents that can run on-device with a small local model (default
``llama3.2:1b``) and by the local-runtime sidecar.  Design rules:

* Loopback only: the base URL must be ``http://127.0.0.1:11434``.  Anything
  else (``localhost`` that may resolve to ::1, LAN IPs, remote hosts, https,
  other ports) is rejected with ``code="wrong_host"`` so user data never leaves
  the device and there is no silent cloud fallback.
* Clear failure codes: ``ok | wrong_host | not_running | timeout | not_ollama |
  model_missing | model_load_failed``.
* Structured output: ``chat_json`` sends a JSON schema via Ollama ``format``,
  temperature 0 + fixed seed, validates the reply with a caller-supplied
  validator and does ONE repair retry (feeding the validation errors back).

CLI::

    python -m marketplace_sdk.ollama_local --check [--model llama3.2:1b] [--probe]

Exit code 0 when ok, 2 otherwise; prints the CheckResult as JSON.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:1b"
ALLOWED_HOST = "127.0.0.1"
ALLOWED_PORT = 11434

from .local_llm_config import load_config  # single config source (env > defaults file)

# One num_ctx for every call so Ollama never reloads the model between agents.
# 4096 = Ollama's default context, so callers that don't set num_ctx (e.g. the
# sidecar's builtin prompt) share the loaded model instead of forcing a reload.
DEFAULT_NUM_CTX = load_config().num_ctx
DEFAULT_KEEP_ALIVE = load_config().keep_alive
# Production decoding is deterministic. Test harnesses may override these module
# attributes (e.g. temperature 0.7 + varied seed) to stress the validate/repair path.
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 42

Validator = Callable[[Any], "tuple[dict | None, list[str]]"]


class LocalLLMError(RuntimeError):
    """Raised when the local model cannot produce a valid result."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}


@dataclass
class CheckResult:
    ok: bool
    code: str
    message: str
    base_url: str
    model: str
    ollama_version: str | None = None
    models_available: list[str] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def default_base_url() -> str:
    """AGENTHUB_OLLAMA_URL > OLLAMA_BASE_URL > local_llm_defaults.json."""
    return load_config().ollama_url


def default_model() -> str:
    """AGENTHUB_LOCAL_MODEL > LOCAL_RUNTIME_MODEL > OLLAMA_MODEL > local_llm_defaults.json."""
    return load_config().model


def validate_local_url(base_url: str) -> str | None:
    """Return an error message if ``base_url`` is not http://127.0.0.1:11434."""
    try:
        parsed = urllib.parse.urlparse(base_url)
    except ValueError:
        return f"unparseable Ollama URL {base_url!r}"
    host = parsed.hostname or ""
    port = parsed.port or (80 if parsed.scheme == "http" else None)
    if parsed.scheme != "http":
        return f"Ollama URL must be http://{ALLOWED_HOST}:{ALLOWED_PORT} (got scheme {parsed.scheme!r})"
    if host != ALLOWED_HOST:
        hint = " ('localhost' can resolve to ::1 on Windows; Ollama listens on 127.0.0.1)" if host == "localhost" else ""
        return (
            f"Ollama must be reached on {ALLOWED_HOST}:{ALLOWED_PORT} only; got host {host!r}{hint}. "
            "Local agents never send data off-device."
        )
    if port != ALLOWED_PORT:
        return f"Ollama must be on port {ALLOWED_PORT}; got {port}"
    if parsed.path not in ("", "/"):
        return f"Ollama URL must not have a path; got {parsed.path!r}"
    return None


def _http_json(method: str, url: str, body: dict | None = None, timeout: float = 5.0) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    # Never honour HTTP(S)_PROXY for loopback traffic.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _model_matches(wanted: str, available: list[str]) -> bool:
    def norm(n: str) -> str:
        return n if ":" in n else f"{n}:latest"

    return norm(wanted) in {norm(a) for a in available}


def check_ollama(
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 3.0,
    probe: bool = False,
) -> CheckResult:
    """Check Ollama is reachable on 127.0.0.1:11434 and ``model`` is pulled.

    ``probe=True`` additionally loads the model and generates 1 token (slow on
    first load, ~10s on CPU) to catch corrupt / un-loadable models.
    """
    model = model or default_model()
    base_url = (base_url or default_base_url()).rstrip("/")
    t0 = time.perf_counter()

    def done(ok: bool, code: str, message: str, **kw: Any) -> CheckResult:
        return CheckResult(
            ok=ok, code=code, message=message, base_url=base_url, model=model,
            latency_ms=int((time.perf_counter() - t0) * 1000), **kw,
        )

    err = validate_local_url(base_url)
    if err:
        return done(False, "wrong_host", err)

    try:
        ver = _http_json("GET", f"{base_url}/api/version", timeout=timeout)
    except urllib.error.HTTPError as exc:
        return done(False, "not_ollama", f"{base_url} answered HTTP {exc.code} on /api/version; it is not Ollama (another service is using port {ALLOWED_PORT}?)")
    except (socket.timeout, TimeoutError):
        return done(False, "timeout", f"Ollama at {base_url} did not answer within {timeout}s (hung or overloaded). Restart the Ollama app.")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return done(False, "timeout", f"Ollama at {base_url} did not answer within {timeout}s (hung or overloaded). Restart the Ollama app.")
        return done(False, "not_running", f"Ollama is not running on {base_url} ({reason}). Start the Ollama app or run `ollama serve`.")
    except (ValueError, json.JSONDecodeError):
        return done(False, "not_ollama", f"{base_url} answered /api/version with non-JSON; it is not Ollama (another service is using port {ALLOWED_PORT}?)")
    except OSError as exc:
        return done(False, "not_running", f"Ollama is not running on {base_url} ({exc}). Start the Ollama app or run `ollama serve`.")

    version = ver.get("version") if isinstance(ver, dict) else None
    if not version:
        return done(False, "not_ollama", f"{base_url}/api/version returned {str(ver)[:120]!r}; not an Ollama server")

    try:
        tags = _http_json("GET", f"{base_url}/api/tags", timeout=timeout)
        names = sorted({m.get("name") or m.get("model") for m in tags.get("models", []) if isinstance(m, dict)} - {None})
    except Exception as exc:  # noqa: BLE001
        return done(False, "not_ollama", f"Ollama {version} /api/tags failed: {exc}", ollama_version=version)

    if not _model_matches(model, names):
        return done(
            False, "model_missing",
            f"Model {model!r} is not pulled in Ollama {version}. Run: ollama pull {model}. "
            f"Available: {', '.join(names) if names else '(none)'}",
            ollama_version=version, models_available=names,
        )

    if probe:
        try:
            _http_json(
                "POST", f"{base_url}/api/generate",
                {"model": model, "prompt": "ok", "stream": False, "keep_alive": DEFAULT_KEEP_ALIVE,
                 "options": {"num_predict": 1, "num_ctx": DEFAULT_NUM_CTX}},
                timeout=120,
            )
        except Exception as exc:  # noqa: BLE001
            return done(False, "model_load_failed", f"Model {model!r} is pulled but failed to load/generate: {exc}",
                        ollama_version=version, models_available=names)

    return done(True, "ok", f"Ollama {version} on {base_url} with {model} ready",
                ollama_version=version, models_available=names)


def require_ollama(model: str | None = None, base_url: str | None = None) -> CheckResult:
    """Like check_ollama but raises LocalLLMError(code, message) on failure."""
    res = check_ollama(model=model, base_url=base_url)
    if not res.ok:
        raise LocalLLMError(res.code, res.message, {"check": res.to_dict()})
    return res


def parse_json_loose(raw: str) -> Any:
    """Parse model output as JSON, tolerating code fences / leading chatter."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty model output")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def chunk_text(text: str, max_chars: int = 6000, overlap_lines: int = 2) -> list[str]:
    """Split on line boundaries into chunks <= max_chars (a 1b model degrades fast on long input)."""
    if len(text) <= max_chars:
        return [text]
    lines = text.splitlines()
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        while len(line) > max_chars:  # pathological single line
            if cur:
                chunks.append("\n".join(cur))
                cur, size = [], 0
            chunks.append(line[:max_chars])
            line = line[max_chars:]
        if size + len(line) + 1 > max_chars and cur:
            chunks.append("\n".join(cur))
            cur = cur[-overlap_lines:] if overlap_lines else []
            size = sum(len(x) + 1 for x in cur)
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def chat_json(
    system: str,
    user: str,
    *,
    schema: dict,
    validate: Validator,
    model: str | None = None,
    base_url: str | None = None,
    retries: int = 1,
    timeout: float = 300.0,
    num_predict: int = 1024,
    extra_messages: list[dict] | None = None,
) -> dict:
    """Call /api/chat with JSON-schema constrained output and validate it.

    Returns ``{"output", "usage", "attempts", "raw_outputs", "latency_ms", "model"}``.
    Raises ``LocalLLMError`` (code ``wrong_host`` / ``ollama_error`` /
    ``invalid_output``) if no valid result after ``1 + retries`` attempts.
    """
    model = model or default_model()
    base_url = (base_url or default_base_url()).rstrip("/")
    err = validate_local_url(base_url)
    if err:
        raise LocalLLMError("wrong_host", err)

    messages: list[dict] = [{"role": "system", "content": system}]
    messages += extra_messages or []
    messages.append({"role": "user", "content": user})

    raw_outputs: list[str] = []
    errors_seen: list[list[str]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.perf_counter()
    for attempt in range(1 + max(0, retries)):
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "keep_alive": DEFAULT_KEEP_ALIVE,
            "options": {
                "temperature": DEFAULT_TEMPERATURE,
                "seed": DEFAULT_SEED + attempt,
                "num_ctx": DEFAULT_NUM_CTX,
                "num_predict": num_predict,
            },
        }
        try:
            data = _http_json("POST", f"{base_url}/api/chat", body, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            code = "model_missing" if exc.code == 404 else "ollama_error"
            raise LocalLLMError(code, f"Ollama /api/chat HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LocalLLMError("not_running", f"Ollama /api/chat unreachable at {base_url}: {exc}") from exc

        content = (data.get("message") or {}).get("content", "")
        raw_outputs.append(content)
        usage["input_tokens"] += int(data.get("prompt_eval_count") or 0)
        usage["output_tokens"] += int(data.get("eval_count") or 0)
        try:
            parsed = parse_json_loose(content)
            normalized, errs = validate(parsed)
        except (ValueError, json.JSONDecodeError) as exc:
            normalized, errs = None, [f"not valid JSON: {exc}"]
        if normalized is not None and not errs:
            return {
                "output": normalized,
                "usage": usage,
                "attempts": attempt + 1,
                "raw_outputs": raw_outputs,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model": model,
            }
        errors_seen.append(errs)
        # Repair turn: show the model its own reply + the validation errors.
        messages = messages + [
            {"role": "assistant", "content": content[:4000]},
            {"role": "user", "content": (
                "That JSON was rejected: " + "; ".join(errs)[:800]
                + ". Reply again with ONLY the corrected JSON object, same schema, using facts from the text."
            )},
        ]
    raise LocalLLMError(
        "invalid_output",
        f"{model} did not return valid JSON after {1 + max(0, retries)} attempts",
        {"errors": errors_seen, "raw_outputs": raw_outputs, "usage": usage,
         "latency_ms": int((time.perf_counter() - t0) * 1000)},
    )


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="AgentHub local Ollama health check")
    ap.add_argument("--check", action="store_true", help="run the health check (default)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--probe", action="store_true", help="also load the model and generate 1 token")
    args = ap.parse_args(argv)
    res = check_ollama(model=args.model, base_url=args.base_url, probe=args.probe)
    print(json.dumps(res.to_dict(), indent=2))
    return 0 if res.ok else 2


if __name__ == "__main__":
    raise SystemExit(_main())
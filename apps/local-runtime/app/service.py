"""Entry point for the packaged sidecar (agenthub-local-runtime.exe).

  agenthub-local-runtime.exe [serve]          run the sidecar on 127.0.0.1:8765 (default)
  agenthub-local-runtime.exe setup [--no-pull] [--open-browser]
                                              check Ollama; pull the configured model if absent
  agenthub-local-runtime.exe check            print diagnostics JSON
  agenthub-local-runtime.exe notes <files> [cli options]   one-shot extraction (app.cli)
  agenthub-local-runtime.exe version
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import socket
import sys
import urllib.request
import webbrowser

from . import config

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"


def _ensure_streams(log_name: str) -> None:
    """Windowless/hidden launches may have no stdout/stderr; send them to a log file."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        fh = open(config.LOG_DIR / f"{log_name}.stdio.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh


def _setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "sidecar.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _existing_sidecar(host: str, port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) and "ollama" in data else None
    except Exception:
        return None


def serve() -> int:
    _ensure_streams("sidecar")
    _setup_logging()
    log = logging.getLogger("local-runtime.service")
    host, port = config.HOST, config.PORT
    if host not in {"127.0.0.1", "localhost"}:
        log.warning("HOST=%s requested; forcing 127.0.0.1 (localhost-only sidecar)", host)
        host = "127.0.0.1"
    if _port_in_use(host, port):
        other = _existing_sidecar(host, port)
        if other:
            log.info("a sidecar is already running on %s:%s (version %s); exiting", host, port, other.get("version"))
            return 0
        log.error("port %s:%s is in use by another program; not starting", host, port)
        return 3
    import uvicorn

    from .main import app

    log.info(
        "starting AgentHub local runtime %s on %s:%s (home=%s model=%s frozen=%s)",
        config.VERSION, host, port, config.HOME, config.OLLAMA_MODEL, config.FROZEN,
    )
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    return 0


def _pull_model(model: str) -> bool:
    body = json.dumps({"model": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{config.OLLAMA_BASE_URL}/api/pull", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    last = ""
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            for line in resp:
                try:
                    evt = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if evt.get("error"):
                    print(f"\n  pull error: {evt['error']}")
                    return False
                status = evt.get("status", "")
                total, done = evt.get("total"), evt.get("completed")
                msg = f"{status} {done * 100 // total}%" if total and done else status
                if msg != last:
                    print(f"\r  {msg[:70]:<70}", end="", flush=True)
                    last = msg
        print()
        return True
    except Exception as exc:
        print(f"\n  pull failed: {exc}")
        return False


def setup(argv: list[str]) -> int:
    from .ollama_notes import model_available, ollama_is_up, prompt_info

    no_pull = "--no-pull" in argv
    open_browser = "--open-browser" in argv
    info = prompt_info()
    print(f"AgentHub Local Runtime {config.VERSION}")
    print(f"  data dir : {config.HOME}")
    print(f"  model    : {info['model']}  (prompt: {info['prompt']})")
    print(f"  Ollama   : {config.OLLAMA_BASE_URL}")
    if not ollama_is_up():
        exe = os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
        if os.path.exists(exe):
            print("\n[!] Ollama is installed but not running. Start 'Ollama' from the Start menu, then re-run setup.")
        else:
            print(f"\n[!] Ollama was not found. Install it from {OLLAMA_DOWNLOAD_URL} and re-run setup")
            print("    (Start menu > AgentHub Local Runtime > Setup / check Ollama).")
            if open_browser:
                webbrowser.open(OLLAMA_DOWNLOAD_URL)
        return 2
    print("  Ollama is running.")
    avail = model_available()
    if avail:
        print(f"  Model {info['model']} is already pulled.")
        return 0
    if no_pull:
        print(f"  Model {info['model']} is NOT pulled (skipped: --no-pull).")
        return 1
    print(f"  Pulling {info['model']} (first run only; this can take a while)...")
    ok = _pull_model(info["model"])
    print("  Model ready." if ok else "  [!] Model pull failed; re-run setup later.")
    return 0 if ok else 1


def check() -> int:
    from .ollama_notes import model_available, ollama_is_up, prompt_info

    up = ollama_is_up()
    running = _existing_sidecar("127.0.0.1", config.PORT)
    print(json.dumps({
        "version": config.VERSION,
        "frozen": config.FROZEN,
        "home": str(config.HOME),
        "config_file": str(config.CONFIG_FILE),
        "api_base": config.AGENTHUB_API_BASE,
        "ollama": "up" if up else "down",
        **prompt_info(),
        "model_available": model_available() if up else None,
        "sidecar_running_on_port": bool(running),
        "port": config.PORT,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"
    rest = argv[1:]
    if cmd == "serve":
        return serve()
    if cmd == "setup":
        return setup(rest)
    if cmd == "check":
        return check()
    if cmd == "version":
        print(config.VERSION)
        return 0
    if cmd == "notes":
        from .cli import main as cli_main

        return cli_main(rest)
    print(__doc__)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())

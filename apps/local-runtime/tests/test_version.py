"""Runtime version is consistent across sidecar, /health and installer."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, main


def test_version_is_0_2_0_everywhere(monkeypatch):
    monkeypatch.delenv("LOCAL_RUNTIME_VERSION", raising=False)
    assert config.VERSION == "0.2.0"
    monkeypatch.setattr(main, "ollama_is_up", lambda: False)
    assert TestClient(main.app).get("/health").json()["version"] == "0.2.0"
    iss = (Path(__file__).resolve().parents[1] / "installer" / "agenthub-local-runtime.iss").read_text(encoding="utf-8")
    assert re.search(r'#define AppVersion "([^"]+)"', iss).group(1) == config.VERSION

import os
import sys
import tempfile
from pathlib import Path

# Isolate state before app.* is imported (no real .session.json / queue files touched).
os.environ["LOCAL_RUNTIME_HOME"] = tempfile.mkdtemp(prefix="lr-test-")
for k in ("LOCAL_RUNTIME_SESSION_FILE", "LOCAL_RUNTIME_USAGE_QUEUE", "LOCAL_RUNTIME_USAGE_FAILED",
          "LOCAL_RUNTIME_OFFLINE_STUB", "AGENTHUB_SESSION_TOKEN"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

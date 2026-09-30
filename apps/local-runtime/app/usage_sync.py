"""Retry locally queued usage rows: python -m app.usage_sync [--hire-file .dev-hire.json]"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync usage-pending.jsonl to the AgentHub API")
    parser.add_argument("--hire-file", default=None, help="JSON with session_token for queued rows' session")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    token = None
    if args.hire_file:
        token = json.loads(Path(args.hire_file).read_text(encoding="utf-8")).get("session_token")
    result = session.sync_pending_usage(token_override=token)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

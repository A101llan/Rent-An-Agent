"""One-shot CLI: claim session -> extract meeting notes -> write JSON -> report usage.

  python -m app.cli fixtures\\sample-meeting.docx --hire-file .dev-hire.json -o out\\e2e.json
  python -m app.cli notes.docx --session-id <uuid>        # token from AGENTHUB_SESSION_TOKEN
  python -m app.cli notes.docx                            # reuse claimed session in .session.json
  python -m app.cli notes.docx --dev-unbound              # no session, no usage (labeled dev run)

Fails closed (exit 3, no extraction) on any non-200 claim response.
Tokens are never accepted on argv (use env or --hire-file).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from . import config, session
from .jobs import SUPPORTED_SUFFIXES, extract_to_file
from .ollama_notes import ExtractionError


def _load_hire_file(path: Path) -> tuple[str | None, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("session_id"), data.get("session_token")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHub local-runtime meeting-notes CLI")
    parser.add_argument("inputs", nargs="+", help="Input .docx/.txt/.md paths")
    parser.add_argument("-o", "--output", default=None, help="Output JSON path (default: out/proof-notes.json)")
    parser.add_argument("--session-id", default=None, help="Session to claim (token from AGENTHUB_SESSION_TOKEN)")
    parser.add_argument("--hire-file", default=None, help="JSON with session_id + session_token (from scripts/dev_hire.py)")
    parser.add_argument("--offline-stub", action="store_true", help="Allow labeled stub bind ONLY if the API is unreachable")
    parser.add_argument("--dev-unbound", action="store_true", help="Run with no session at all (no usage reported)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if args.offline_stub:
        config.OFFLINE_STUB = True

    paths = [Path(p) for p in args.inputs]
    for path in paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            return 1
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            print(f"unsupported: {path} (supported {sorted(SUPPORTED_SUFFIXES)})", file=sys.stderr)
            return 1

    sid, token = args.session_id, os.getenv("AGENTHUB_SESSION_TOKEN")
    if args.hire_file:
        hsid, htoken = _load_hire_file(Path(args.hire_file))
        sid, token = sid or hsid, htoken or token

    report_usage = True
    session_info = None
    if sid or token:
        if not (sid and token):
            print("need both session_id and session token (env AGENTHUB_SESSION_TOKEN or --hire-file)", file=sys.stderr)
            return 2
        claim = session.claim_session(token, sid)
        print(json.dumps({"claim": {k: v for k, v in claim.items() if k != "manifest"}}, indent=2, default=str))
        if not claim.get("bound"):
            print("FAIL CLOSED: claim did not return 200; extraction NOT run.", file=sys.stderr)
            return 3
    elif session.require_active() is None:
        print(json.dumps({"using_stored_session": session.public_summary()}, indent=2, default=str))
    elif args.dev_unbound:
        report_usage = False
        session_info = {"bound": False, "mode": "dev_unbound", "warning": "DEV RUN: no session claimed, usage not reported"}
    else:
        print("no claimed session: pass --hire-file/--session-id, or --dev-unbound for a labeled dev run", file=sys.stderr)
        return 2

    denied = session.require_active() if report_usage else None
    if denied:
        print(json.dumps(denied, indent=2, default=str), file=sys.stderr)
        return 3

    out = Path(args.output) if args.output else config.OUT_DIR / "proof-notes.json"
    try:
        payload = extract_to_file(
            paths, out, job_id=f"cli-{uuid.uuid4()}", report_usage=report_usage, session_info=session_info
        )
    except ExtractionError as exc:
        print(f"EXTRACTION FAILED (no usage reported): {exc}", file=sys.stderr)
        return 4
    print(
        json.dumps(
            {
                "wrote": str(out),
                "source": payload.get("source"),
                "model_meta": payload.get("model_meta"),
                "session": payload.get("session"),
                "usage_report": payload.get("usage_report"),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

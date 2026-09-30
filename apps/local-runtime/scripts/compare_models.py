"""Compare model/prompt combos on a fixture (data for the Ollama Integrator; picks nothing).

  python scripts\\compare_models.py fixtures\\sample-meeting.docx llama3.2:1b qwen2.5:3b --prompts builtin,prompts\\decisions-v2.json
Writes out\\model-compare\\summary.json and one JSON per run.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, ollama_notes  # noqa: E402
from app.jobs import _read_source  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("models", nargs="+")
    ap.add_argument("--prompts", default="builtin")
    args = ap.parse_args()
    text = _read_source(Path(args.fixture))
    outdir = ROOT / "out" / "model-compare"
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for model in args.models:
        for prompt in args.prompts.split(","):
            config.OLLAMA_MODEL = model
            config.PROMPT_FILE = None if prompt == "builtin" else prompt
            t0 = time.perf_counter()
            res = ollama_notes.extract_meeting_notes_via_ollama(text)
            wall = round(time.perf_counter() - t0, 1)
            tag = f"{model.replace(':', '_')}__{Path(prompt).stem}"
            row = {"model": model, "prompt": prompt, "wall_seconds": wall, "ok": bool(res)}
            if res:
                o = res["output"]
                row.update({
                    "decisions": len(o["decisions"]), "action_items": len(o["action_items"]),
                    "open_questions": len(o["open_questions"]), "usage": res["usage"], "meta": res["meta"],
                })
                (outdir / f"{tag}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
            else:
                row["error"] = ollama_notes._last_error
            rows.append(row)
            print(json.dumps(row), flush=True)
    (outdir / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

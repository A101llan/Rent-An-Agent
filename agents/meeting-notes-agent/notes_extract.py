"""Hardened Meeting Notes extraction on a local Ollama model (llama3.2:1b).

Contract: {summary: str, decisions: [str], action_items: [{owner, task}], open_questions: [str]}

Hardening for a 1b model:
* transcript pre-clean (leading timestamps, filler words, stutters) + speaker roster hint
* JSON-schema constrained decoding (Ollama ``format``), temperature 0, fixed seed
* validation/normalisation + one repair retry (marketplace_sdk.ollama_local.chat_json)
* owner guard: an owner that never appears in the transcript becomes "Unassigned"
* chunking for long transcripts (map per chunk, merge + one summary pass)

No canned fallback here: on failure ``LocalLLMError`` is raised with a clear code.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from marketplace_sdk.ollama_local import (  # type: ignore
        LocalLLMError, chat_json, check_ollama, chunk_text, default_model,
    )
    from marketplace_sdk.local_llm_config import load_prompt  # type: ignore
except ImportError:  # dev tree / sidecar: use the in-repo SDK
    _sdk = Path(__file__).resolve().parents[2] / "packages" / "agent-sdk" / "src"
    if _sdk.is_dir():
        sys.path.insert(0, str(_sdk))
    from marketplace_sdk.ollama_local import (  # type: ignore  # noqa: E402
        LocalLLMError, chat_json, check_ollama, chunk_text, default_model,
    )
    from marketplace_sdk.local_llm_config import load_prompt  # type: ignore  # noqa: E402

UNASSIGNED = "Unassigned"
# ~2000 tokens: fits num_ctx 4096 with prompt + 700 output tokens; typical meetings stay 1 chunk.
CHUNK_CHARS = 7500

# maxItems/maxLength are enforced by Ollama's grammar: they stop the 1b model from
# looping on an array until num_predict runs out (seen on long transcripts).
MEETING_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 600},
        "decisions": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 200}},
        "action_items": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "maxLength": 60},
                    "task": {"type": "string", "maxLength": 200},
                },
                "required": ["owner", "task"],
            },
        },
        "open_questions": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 200}},
    },
    "required": ["summary", "decisions", "action_items", "open_questions"],
}
NUM_PREDICT = 700
SYSTEM_PROMPT = """You write meeting notes as JSON from a messy transcript.
Rules:
- summary: 1-2 sentences on the topic and the outcome. Do not just copy the title.
- decisions: short statements of what was FINALLY agreed. If a plan was changed later in the meeting, give ONLY the final version. Questions are never decisions.
- action_items: tasks someone must do after the meeting. owner = the person who said "I will ..." or who was asked by name ("X, can you ..."). If people only said "someone should ..." and nobody volunteered, owner = "Unassigned". One item per task, no duplicates.
- open_questions: questions still unanswered at the end.
- Use only facts from the transcript.

Example transcript:
Tom: let's order 10 cakes for Friday.
Amina: budget is tight.
Tom: ok change that, 6 cakes, final.
Amina: I'll call the bakery tomorrow.
Tom: someone should book the hall.
Amina: do we invite the board?
Example JSON:
{"summary": "Planned the Friday party and cut the cake order.", "decisions": ["Order 6 cakes for Friday"], "action_items": [{"owner": "Amina", "task": "Call the bakery tomorrow"}, {"owner": "Unassigned", "task": "Book the hall"}], "open_questions": ["Do we invite the board?"]}"""

# Words that only occur in the prompt example; seeing them in output means the model copied it.
_EXAMPLE_TOKENS = ("cake", "bakery", "amina", "book the hall", "invite the board")

_TS_LEAD = re.compile(
    r"^\s*(?:\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]|\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)|\d{1,2}:\d{2}(?::\d{2})?\s*(?:-|–|\|)?)\s*"
)
_FILLER = re.compile(r"\b(?:u+m+|u+h+|e+r+m+|hmm+|mm+-?hmm+|ah+)\b[,.]?\s*", re.I)
_STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b)+", re.I)
_SPEAKER = re.compile(r"^\s*(?:[-*\u2022]\s+)?(?:\*\*)?([A-Z][\w'.-]*(?: [A-Z][\w'.-]*){0,2}(?: \([^)]{1,30}\))?)(?:\*\*)?\s*:")


# Otter / Teams exports: "Ge Wambua  00:00:04" on its own line, utterance on the next line.
_TS_SPEAKER_LINE = re.compile(r"^\s*([A-Z][^\n:]{0,40}?)\s+\(?\d{1,2}:\d{2}(?::\d{2})?\)?\s*$")
_NOISE = re.compile(r"[\[(](?:inaudible|crosstalk|silence|laughs?|laughter|music|noise)[\])]\s*", re.I)


def clean_transcript(text: str) -> str:
    out = []
    pending_speaker = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _TS_SPEAKER_LINE.match(line)
        if m:
            pending_speaker = m.group(1).strip()
            continue
        if pending_speaker and line.strip():
            line = f"{pending_speaker}: {line.strip()}"
            pending_speaker = None
        line = _NOISE.sub("", line)
        line = _TS_LEAD.sub("", line)
        line = _FILLER.sub("", line)
        line = _STUTTER.sub(r"\1", line)
        line = re.sub(r"[ \t]{2,}", " ", line).rstrip()
        out.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return cleaned


def speaker_roster(text: str) -> list[str]:
    seen: list[str] = []
    for line in text.split("\n"):
        m = _SPEAKER.match(line)
        if m:
            name = m.group(1).strip()
            if name.lower() not in {"note", "notes", "action", "decision", "decisions", "agenda", "todo", "http", "https", "attendees", "date", "re", "fyi", "btw", "open", "next"} and name not in seen:
                seen.append(name)
    return seen[:15]


def _as_str(x) -> str:
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        return " ".join(str(v).strip() for v in x.values() if isinstance(v, (str, int, float)))
    return str(x).strip() if x is not None else ""


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\W+", " ", it.lower()).strip()
        if it and key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _fuzzy_dedupe(items: list, key=lambda x: x, threshold: float = 0.6) -> list:
    """Drop near-duplicates (word-set Jaccard >= threshold); 1b models repeat themselves."""
    kept: list = []
    for it in items:
        w = _words(key(it))
        if not any(w and (len(w & _words(key(k))) / len(w | _words(key(k)))) >= threshold for k in kept):
            kept.append(it)
    return kept


def _owner_in_text(owner: str, haystack: str) -> bool:
    if owner == UNASSIGNED:
        return True
    tokens = [t for t in re.split(r"[\s/,&()]+", owner.lower()) if len(t) >= 2]
    return bool(tokens) and any(t in haystack for t in tokens)


def make_validator(transcript: str, warnings: list[str], leak_tokens=None, require=("summary", "decisions", "action_items", "open_questions")):
    haystack = transcript.lower()
    leak_tokens = tuple(t.lower() for t in (_EXAMPLE_TOKENS if leak_tokens is None else leak_tokens))

    def validate(data):
        errs: list[str] = []
        if not isinstance(data, dict):
            return None, ["top level must be a JSON object"]
        for key in require:
            if key not in data:
                errs.append(f"missing key '{key}'")
        if errs:
            return None, errs
        data = {"summary": "", "decisions": [], "action_items": [], "open_questions": [], **data}
        summary = _as_str(data["summary"])
        if summary.startswith("{"):  # model nested JSON inside the summary string
            try:
                import json as _json
                summary = ". ".join(str(v) for v in _json.loads(summary).values())
            except Exception:  # noqa: BLE001
                pass
        if "summary" in require and len(summary) < 10:
            errs.append("summary is empty; write 1-3 sentences")
        lists = {}
        for key in ("decisions", "open_questions"):
            val = data[key]
            if isinstance(val, str):
                val = [val] if val.strip() else []
            if not isinstance(val, list):
                errs.append(f"'{key}' must be a list of strings")
                continue
            lists[key] = _dedupe([_as_str(v) for v in val if _as_str(v)])[:12]
        items = data["action_items"]
        if not isinstance(items, list):
            errs.append("'action_items' must be a list of {owner, task}")
            items = []
        actions = []
        for it in items:
            if isinstance(it, str):
                it = {"owner": UNASSIGNED, "task": it}
            if not isinstance(it, dict):
                continue
            task = _as_str(it.get("task") or it.get("action") or it.get("description"))
            owner = _as_str(it.get("owner") or it.get("assignee") or "") or UNASSIGNED
            if owner.lower() in {"none", "n/a", "unknown", "tbd", "nobody", "no one", "unassigned", "team", "everyone"}:
                owner = UNASSIGNED
            if not task:
                continue
            if not _owner_in_text(owner, haystack):
                warnings.append(f"owner {owner!r} not found in transcript -> {UNASSIGNED} (task: {task[:60]})")
                owner = UNASSIGNED
            actions.append({"owner": owner, "task": task})
        # dedupe actions by task text
        seen, uniq = set(), []
        for a in actions:
            k = re.sub(r"\W+", " ", a["task"].lower()).strip()
            if k not in seen:
                seen.add(k)
                uniq.append(a)
        def leaked(s: str) -> bool:
            s = s.lower()
            return any(t in s and t not in haystack for t in leak_tokens)

        if leaked(summary):
            errs.append("the summary copies the prompt example; summarise THIS transcript")
        if errs:
            return None, errs
        # Items copied from the prompt example are dropped deterministically (a 1b model
        # usually repeats the same copy on a repair turn, so asking again does not help).
        n_before = len(lists.get("decisions", [])) + len(lists.get("open_questions", [])) + len(uniq)
        decisions = [x for x in lists.get("decisions", []) if not leaked(x)]
        questions = [x for x in lists.get("open_questions", []) if not leaked(x)]
        uniq = [a for a in uniq if not leaked(a["task"] + " " + a["owner"])]
        if len(decisions) + len(questions) + len(uniq) < n_before:
            warnings.append(f"dropped {n_before - len(decisions) - len(questions) - len(uniq)} item(s) copied from the prompt example")
        # a "decision" phrased as a question is an open question
        moved = [d for d in decisions if d.rstrip().endswith("?")]
        decisions = [d for d in decisions if d not in moved]
        return {
            "summary": summary,
            "decisions": _fuzzy_dedupe(decisions)[:10],
            "action_items": _fuzzy_dedupe(uniq, key=lambda a: a["task"])[:12],
            "open_questions": _fuzzy_dedupe(questions + moved)[:10],
        }, []

    return validate


DECISIONS_SCHEMA = {
    "type": "object",
    "properties": {"decisions": MEETING_SCHEMA["properties"]["decisions"]},
    "required": ["decisions"],
}
ITEMS_SCHEMA = {
    "type": "object",
    "properties": {k: MEETING_SCHEMA["properties"][k] for k in ("summary", "action_items", "open_questions")},
    "required": ["summary", "action_items", "open_questions"],
}
DEFAULT_USER_TEMPLATE = 'Transcript:\n"""\n{notes}\n"""\nReturn the JSON.'


def _head(roster: list[str], part: tuple[int, int] | None) -> str:
    head = ""
    if roster:
        head += "People in this meeting (speaker labels): " + ", ".join(roster) + "\n"
    if part and part[1] > 1:
        head += f"This is part {part[0]} of {part[1]} of a long transcript.\n"
    return head


def _example_messages(examples, template: str) -> list[dict]:
    msgs: list[dict] = []
    for ex in examples or []:
        if isinstance(ex, dict) and "input" in ex and "output" in ex:
            msgs.append({"role": "user", "content": template.format(notes=ex["input"])})
            out = ex["output"]
            msgs.append({"role": "assistant", "content": out if isinstance(out, str) else json.dumps(out)})
    return msgs


_CUE = re.compile(r"\b(agreed|agree|decided|decision|final|approved|confirmed|locked)\b", re.I)


def decision_cues(text: str, limit: int = 12) -> list[str]:
    """Keyword scan for lines that likely state a decision (hint for the decisions pass).

    Short lines ("Yes, final. Three.") get the previous line prepended for context.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if " | " in ln:  # action-item table rows are not decisions
            continue
        if _CUE.search(ln) and not (ln.endswith("?") and ". " not in ln and ":" not in ln):
            s = ln if (len(ln) >= 60 or i == 0) else f"{lines[i - 1]} / {ln}"
            out.append(s[:300])
    return out[:limit]


def cue_statement(line: str) -> str:
    """Turn a keyword-scan line into a short decision statement (deterministic, no LLM)."""
    def strip(x: str) -> str:
        x = re.sub(r"~~[^~]+~~", "", x)  # struck-through (cancelled) text
        x = re.sub(r"^\s*[-*]?\s*(\*\*)?[A-Z][\w .'()-]{0,40}?(\*\*)?\s*:\s*", "", x)  # speaker label
        return x.replace("**", "").replace("*", "").strip()

    def sentences(x: str) -> list[str]:
        return [t.strip() for t in re.split(r"(?<=[.!?])\s+", x) if t.strip()]

    parts = [strip(p) for p in line.split(" / ")]
    cur, ctx = parts[-1], (parts[0] if len(parts) > 1 else "")
    m = re.search(r"\bdecision\s*:\s*(.+)", cur, re.I)
    if m:
        return sentences(m.group(1))[0].rstrip(".")
    sents = sentences(cur)
    idx = next((i for i, t in enumerate(sents) if _CUE.search(t)), None)
    if idx is None:
        return cur.rstrip(".")
    if len(sents[idx]) >= 25:
        return sents[idx].rstrip(".")
    near = [t for t in (sents[:idx][::-1] + sents[idx + 1:]) if len(t) >= 12 and not t.endswith("?")]
    if near:
        return near[0].rstrip(".")
    ctx_s = [t for t in sentences(ctx) if len(t) >= 12 and not t.endswith("?")]
    return (ctx_s[-1] if ctx_s else sents[idx]).rstrip(".")

def _extract_chunk(chunk: str, head: str, prompt: dict, model: str, notes: str, warnings: list[str]):
    """Run one chunk through the configured prompt strategy. Returns (output, [chat_json results])."""
    leak = prompt.get("leak_tokens")
    if prompt.get("strategy") == "decisions_first":
        pd, pi = prompt["passes"]["decisions"], prompt["passes"]["items"]
        td = pd.get("user_template") or DEFAULT_USER_TEMPLATE
        ti = pi.get("user_template") or DEFAULT_USER_TEMPLATE
        user_d = td.format(notes=head + chunk)
        if prompt.get("decision_cues") in (True, "hint"):  # "post" = union only, no hint in the prompt
            cues = decision_cues(chunk)
            if cues:
                user_d += ("\n\nLines that may contain decisions (keyword scan - keep only real decisions that were "
                           "not changed later, rewrite each as a short statement):\n" + "\n".join(f"- {c}" for c in cues))
        r1 = chat_json(pd["system"], user_d, schema=DECISIONS_SCHEMA,
                       validate=make_validator(notes, warnings, leak, require=("decisions",)),
                       model=model, num_predict=350, extra_messages=_example_messages(pd.get("examples"), td))
        decisions = r1["output"]["decisions"]
        if prompt.get("decision_cues"):
            # Hybrid: small models often miss explicit "agreed"/"Decision:" lines (or return questions),
            # so union the model's decisions with the deterministic keyword-scan statements.
            scan = [cue_statement(c) for c in decision_cues(chunk)]
            merged = _fuzzy_dedupe(decisions + scan, threshold=0.5)[:10]
            added = len(merged) - len(_fuzzy_dedupe(decisions, threshold=0.5)[:10])
            if added > 0:
                warnings.append(f"added {added} keyword-scan decision(s) the model missed")
            decisions = merged
        user_i = ti.format(notes=head + chunk + "\nDecisions already found: " + ("; ".join(decisions) or "(none)"))
        r2 = chat_json(pi["system"], user_i, schema=ITEMS_SCHEMA,
                       validate=make_validator(notes, warnings, leak, require=("summary", "action_items", "open_questions")),
                       model=model, num_predict=NUM_PREDICT, extra_messages=_example_messages(pi.get("examples"), ti))
        o = r2["output"]
        return {"summary": o["summary"], "decisions": decisions, "action_items": o["action_items"],
                "open_questions": o["open_questions"]}, [r1, r2]
    tmpl = prompt.get("user_template") or DEFAULT_USER_TEMPLATE
    r = chat_json(prompt["system"], tmpl.format(notes=head + chunk), schema=MEETING_SCHEMA,
                  validate=make_validator(notes, warnings, leak), model=model, num_predict=NUM_PREDICT,
                  extra_messages=_example_messages(prompt.get("examples"), tmpl))
    return r["output"], [r]


def extract_meeting_notes(notes: str, model: str | None = None, check: bool = True,
                          prompt: str | dict | None = None) -> dict:
    """Return {output, usage, source, model, meta}. Raises LocalLLMError on failure.

    model/prompt default to the single config source (marketplace_sdk.local_llm_config):
    AGENTHUB_LOCAL_MODEL / AGENTHUB_MEETING_NOTES_PROMPT, else local_llm_defaults.json.
    """
    if not isinstance(notes, str) or not notes.strip():
        raise LocalLLMError("empty_input", "no meeting text provided")
    model = model or default_model()
    prompt_data = prompt if isinstance(prompt, dict) else load_prompt(prompt)
    if check:
        res = check_ollama(model=model)
        if not res.ok:
            raise LocalLLMError(res.code, res.message, {"check": res.to_dict()})

    cleaned = clean_transcript(notes)
    roster = speaker_roster(cleaned)
    chunks = chunk_text(cleaned, max_chars=CHUNK_CHARS)
    warnings: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    attempts: list[int] = []
    raw_outputs: list[str] = []
    latency = 0
    parts = []

    def account(results):
        nonlocal latency
        for r in results:
            attempts.append(r["attempts"])
            raw_outputs.extend(r["raw_outputs"])
            latency += r["latency_ms"]
            for k in usage:
                usage[k] += r["usage"][k]

    for i, chunk in enumerate(chunks, 1):
        out, results = _extract_chunk(chunk, _head(roster, (i, len(chunks))), prompt_data, model, notes, warnings)
        parts.append(out)
        account(results)

    if len(parts) == 1:
        output = parts[0]
    else:
        merged_actions = [a for p in parts for a in p["action_items"]]
        summary_schema = {"type": "object", "properties": {"summary": {"type": "string", "maxLength": 600}},
                          "required": ["summary"]}

        def v_summary(d):
            s = _as_str(d.get("summary")) if isinstance(d, dict) else ""
            return ({"summary": s}, []) if len(s) >= 10 else (None, ["summary is empty"])

        r = chat_json(
            "Write one 2-sentence plain-text summary of a meeting from partial notes. JSON only.",
            "Partial summaries:\n" + "\n".join(f"- {p['summary']}" for p in parts)
            + "\nDecisions:\n" + "\n".join(f"- {d}" for p in parts for d in p["decisions"][:5]),
            schema=summary_schema, validate=v_summary, model=model, num_predict=300,
        )
        account([r])
        output = {
            "summary": r["output"]["summary"],
            "decisions": _fuzzy_dedupe([d for p in parts for d in p["decisions"]])[:12],
            "action_items": _fuzzy_dedupe(merged_actions, key=lambda a: a["task"])[:15],
            "open_questions": _fuzzy_dedupe([q for p in parts for q in p["open_questions"]])[:12],
        }

    return {
        "output": output,
        "usage": usage,
        "source": "ollama",
        "model": model,
        "meta": {
            "prompt": prompt_data.get("name"),
            "strategy": prompt_data.get("strategy"),
            "chunks": len(chunks),
            "attempts": attempts,
            "latency_ms": latency,
            "roster": roster,
            "warnings": warnings,
            "raw_outputs": raw_outputs,
        },
    }
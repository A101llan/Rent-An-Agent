"""Local-Ollama (llama3.2:1b) implementations for text-in/structured-out demo agents.

* resume-screening-agent  -> screen_resume(text_or_dict)
* customer-support-agent  -> support_reply(text, context)

Pattern (same as meeting-notes / invoice agents): JSON-schema constrained
output, temperature 0, validation + one repair retry via
marketplace_sdk.ollama_local, then DETERMINISTIC post-processing for anything
a 1b model is bad at (scoring, recommendations, escalation rules).
Raise LocalLLMError on failure; the caller decides whether a canned demo reply
is acceptable (cloud demo) or not (local runtime: AGENTHUB_LOCAL_STRICT=1).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from marketplace_sdk.ollama_local import LocalLLMError, chat_json, check_ollama, default_model  # type: ignore
except ImportError:  # dev tree / sidecar: use the in-repo SDK
    _sdk = Path(__file__).resolve().parents[2] / "packages" / "agent-sdk" / "src"
    if _sdk.is_dir():
        sys.path.insert(0, str(_sdk))
    from marketplace_sdk.ollama_local import LocalLLMError, chat_json, check_ollama, default_model  # type: ignore  # noqa: E402


def _require(model: str) -> None:
    res = check_ollama(model=model)
    if not res.ok:
        raise LocalLLMError(res.code, res.message, {"check": res.to_dict()})


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", s.lower())


# --------------------------------------------------------------------------- resume

_JD_HEAD = re.compile(r"^\s*#*\s*(job description|jd|role|position|requirements|must[- ]haves?)\b", re.I | re.M)
_RESUME_HEAD = re.compile(r"^\s*#*\s*(resume|cv|curriculum vitae|candidate)\b", re.I | re.M)
_REQ_SECTION = re.compile(r"^\s*#*\s*\**\s*(requirements|must[- ]haves?|what you need|you have|qualifications)\b.*$", re.I | re.M)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.+)$")


def split_resume_jd(inp) -> tuple[str, str]:
    """Accept {resume, job_description} or one text holding both (e.g. files joined by '---')."""
    if isinstance(inp, dict):
        return str(inp.get("resume") or inp.get("cv") or ""), str(inp.get("job_description") or inp.get("jd") or "")
    text = str(inp)
    parts = [p for p in re.split(r"\n\s*-{3,}\s*\n", text) if p.strip()]
    if len(parts) >= 2:
        jd = [p for p in parts if _JD_HEAD.search(p) and not _RESUME_HEAD.search(p[:200])]
        if jd:
            rest = [p for p in parts if p is not jd[0]]
            return "\n\n".join(rest), jd[0]
    m = _JD_HEAD.search(text)
    r = _RESUME_HEAD.search(text)
    if m and r:
        if m.start() < r.start():
            return text[r.start():], text[m.start():r.start()]
        return text[r.start():m.start()], text[m.start():]
    return text, ""


def jd_requirements(jd: str, limit: int = 8) -> list[str]:
    m = _REQ_SECTION.search(jd)
    lines = jd[m.end():].split("\n") if m else jd.split("\n")
    reqs: list[str] = []
    for line in lines:
        b = _BULLET.match(line)
        if b:
            reqs.append(b.group(1).strip().strip("*"))
        elif m and reqs and re.match(r"^\s*#|^\s*\*\*", line):
            break  # next section
    return reqs[:limit]


def _resume_schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "candidate_name": {"type": "string", "maxLength": 80},
            "years_experience": {"type": "number"},
            "requirements": {
                "type": "array", "minItems": n, "maxItems": n,
                "items": {"type": "object", "properties": {
                    "id": {"type": "integer"}, "met": {"type": "boolean"},
                    "evidence": {"type": "string", "maxLength": 200}},
                    "required": ["id", "met", "evidence"]},
            },
            "strengths": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 120}},
        },
        "required": ["candidate_name", "years_experience", "requirements", "strengths"],
    }


RESUME_PROMPT = """You check a candidate's resume against numbered job requirements.
For EACH requirement id, set met=true ONLY if the resume clearly shows it, and copy a short exact quote from the resume as evidence. If the resume does not show it, met=false and evidence="".
Years: count only the professional experience relevant to the requirement. "learning" or "basic" does not meet a requirement.
candidate_name: the candidate's name from the resume. years_experience: total professional years in the resume.
strengths: up to 4 short phrases taken from the resume."""


def _evidence_ok(ev: str, resume: str) -> bool:
    w = [x for x in _words(ev) if len(x) > 2]
    if not w:
        return False
    rw = set(_words(resume))
    return sum(1 for x in w if x in rw) / len(w) >= 0.7


def screen_resume(inp, model: str | None = None) -> dict:
    model = model or default_model()
    resume, jd = split_resume_jd(inp)
    if len(resume.strip()) < 50:
        raise LocalLLMError("empty_input", "no resume text found")
    reqs = jd_requirements(jd)
    if not reqs:
        raise LocalLLMError("missing_job_description",
                            "no job description requirements found; pass {resume, job_description} or a JD with a bulleted Requirements list")
    _require(model)
    warnings: list[str] = []
    name_hint = next((ln.strip(" #*") for ln in resume.strip().split("\n") if ln.strip()), "")[:80]

    def validate(d):
        if not isinstance(d, dict):
            return None, ["top level must be an object"]
        rows = d.get("requirements")
        if not isinstance(rows, list):
            return None, ["requirements must be a list"]
        by_id = {}
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("id"), int) and 1 <= r["id"] <= len(reqs):
                by_id.setdefault(r["id"], r)
        missing = [i for i in range(1, len(reqs) + 1) if i not in by_id]
        if len(missing) > len(reqs) // 2:
            return None, [f"give one entry for every requirement id 1..{len(reqs)}; missing {missing}"]
        out_rows = []
        for i, req in enumerate(reqs, 1):
            r = by_id.get(i, {"met": False, "evidence": ""})
            met = bool(r.get("met"))
            ev = str(r.get("evidence") or "").strip()
            if met and not _evidence_ok(ev, resume):
                warnings.append(f"req {i}: evidence {ev[:60]!r} not found in resume -> met=false")
                met = False
            out_rows.append({"requirement": req, "met": met, "evidence": ev if met else ""})
        name = str(d.get("candidate_name") or "").strip()
        if not name or not all(t in resume.lower() for t in _words(name)[:2]):
            name = name_hint
        try:
            years = float(d.get("years_experience") or 0)
        except (TypeError, ValueError):
            years = 0.0
        strengths = [str(s).strip() for s in (d.get("strengths") or []) if str(s).strip()]
        strengths = [s for s in strengths if _evidence_ok(s, resume) or any(w in resume.lower() for w in _words(s) if len(w) > 3)]
        return {"candidate_name": name, "years_experience": years, "requirements": out_rows, "strengths": strengths[:4]}, []

    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(reqs, 1))
    res = chat_json(RESUME_PROMPT, f"Requirements:\n{numbered}\n\nResume:\n\"\"\"\n{resume.strip()[:7000]}\n\"\"\"",
                    schema=_resume_schema(len(reqs)), validate=validate, model=model, num_predict=700)
    o = res["output"]
    met = sum(1 for r in o["requirements"] if r["met"])
    score = round(100 * met / len(reqs))
    rec = ("Proceed to interview" if score >= 75 else "Phone screen - partial match" if score >= 50 else "Do not proceed")
    output = {
        "candidate_name": o["candidate_name"],
        "score": score,
        "recommendation": rec,
        "strengths": o["strengths"] or [f"Meets: {r['requirement']}" for r in o["requirements"] if r["met"]][:4],
        "weaknesses": [f"Not shown: {r['requirement']}" for r in o["requirements"] if not r["met"]],
        "requirements": o["requirements"],
        "years_experience": o["years_experience"],
    }
    return {"output": output, "usage": res["usage"], "source": "ollama", "model": model,
            "meta": {"attempts": [res["attempts"]], "chunks": 1, "latency_ms": res["latency_ms"],
                     "warnings": warnings, "raw_outputs": res["raw_outputs"],
                     "scoring": "score = % of JD requirements met with verified resume quote (deterministic)"}}


# --------------------------------------------------------------------------- support

SUPPORT_CATEGORIES = ["billing", "technical", "account", "complaint", "shipping", "general"]
SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": SUPPORT_CATEGORIES},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "angry"]},
        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
        "escalate": {"type": "boolean"},
        "escalation_reason": {"type": "string", "maxLength": 200},
        "reply": {"type": "string", "maxLength": 1200},
    },
    "required": ["category", "sentiment", "urgency", "escalate", "escalation_reason", "reply"],
}

SUPPORT_PROMPT = """You are a customer support agent for {product}. Tone: {tone}.
Read the customer's message and return JSON:
- category: billing (charges, payments, refunds, M-Pesa), technical (errors, bugs, setup), account (login, password, profile), complaint (formal complaint, legal threat, data/privacy), shipping, general.
- sentiment and urgency of the customer.
- escalate: true if a human must handle it (legal threats, privacy/data issues, fraud, money taken wrongly, very angry customer).
- reply: a short, polite reply to send the customer (3-6 sentences). Acknowledge the exact problem, say what happens next, ask for any missing detail (e.g. M-Pesa transaction code). Do NOT promise refunds or give ticket numbers, prices or dates that are not in the message."""

# Hard escalation rules applied after the model (a 1b model misses these too often).
_ESCALATE_RX = re.compile(
    r"\b(lawyer|advocate|legal action|court|sue|suing|data protection|odpc|breach|leak(ed)?|fraud|stolen|"
    r"unauthori[sz]ed|chargeback|police|double[- ]charged|charged twice|deducted twice)\b", re.I)
_FAKE_REF = re.compile(r"\b(?:SUP|TKT|TICKET|REF|CASE)[-#: ]?\d{3,}\b|#\d{4,}", re.I)
_PROMISE = re.compile(r"\b(we will|we'll|i will|i'll)\s+(refund|reverse|credit)\b|\bhas been refunded\b", re.I)


def support_reply(text: str, context: dict | None = None, model: str | None = None) -> dict:
    model = model or default_model()
    if not isinstance(text, str) or len(text.strip()) < 5:
        raise LocalLLMError("empty_input", "no customer message")
    ctx = context or {}
    product = str(ctx.get("product_name") or "AgentHub, an AI agent rental marketplace")[:100]
    tone = str(ctx.get("tone") or "friendly and professional")[:60]
    _require(model)
    warnings: list[str] = []
    lower_in = text.lower()

    def validate(d):
        errs = []
        if not isinstance(d, dict):
            return None, ["top level must be an object"]
        reply = str(d.get("reply") or "").strip()
        if len(reply) < 40:
            errs.append("reply is too short; write 3-6 sentences to the customer")
        for ref in _FAKE_REF.findall(reply):
            if ref.lower() not in lower_in:
                errs.append(f"reply invents a reference number {ref!r}; remove it")
        if _PROMISE.search(reply):
            errs.append("reply promises a refund/reversal; say the team will review instead")
        if d.get("category") not in SUPPORT_CATEGORIES:
            errs.append("category must be one of " + ", ".join(SUPPORT_CATEGORIES))
        if errs:
            return None, errs
        return {
            "category": d["category"],
            "sentiment": d.get("sentiment") or "neutral",
            "urgency": d.get("urgency") or "medium",
            "escalate": bool(d.get("escalate")),
            "escalation_reason": str(d.get("escalation_reason") or "").strip(),
            "reply": reply,
        }, []

    res = chat_json(SUPPORT_PROMPT.format(product=product, tone=tone),
                    f"Customer message:\n\"\"\"\n{text.strip()[:6000]}\n\"\"\"",
                    schema=SUPPORT_SCHEMA, validate=validate, model=model, num_predict=600)
    o = dict(res["output"])
    hit = _ESCALATE_RX.search(text)
    if hit and not o["escalate"]:
        warnings.append(f"rule override: escalate=true (matched {hit.group(0)!r})")
        o["escalate"] = True
        o["escalation_reason"] = o["escalation_reason"] or f"Message mentions '{hit.group(0)}'"
    if o["escalate"] and o["urgency"] == "low":
        o["urgency"] = "medium"
    output = {"response": o["reply"], "category": o["category"], "sentiment": o["sentiment"],
              "urgency": o["urgency"], "escalate": o["escalate"], "escalation_reason": o["escalation_reason"]}
    return {"output": output, "usage": res["usage"], "source": "ollama", "model": model,
            "meta": {"attempts": [res["attempts"]], "chunks": 1, "latency_ms": res["latency_ms"],
                     "warnings": warnings, "raw_outputs": res["raw_outputs"]}}
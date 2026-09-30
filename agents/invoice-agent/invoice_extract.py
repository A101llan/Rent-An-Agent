"""Invoice field extraction on a local Ollama model (llama3.2:1b) + deterministic checks.

The 1b model ONLY copies fields (schema-constrained JSON, temperature 0,
validation + one repair retry). All arithmetic / anomaly detection is done in
Python, because a 1b model cannot be trusted to add numbers.

Input: invoice TEXT (txt / md / docx text). Scanned PDFs need OCR first (not supported).
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

try:
    from marketplace_sdk.ollama_local import LocalLLMError, chat_json, check_ollama, default_model  # type: ignore
except ImportError:  # dev tree / sidecar: use the in-repo SDK
    _sdk = Path(__file__).resolve().parents[2] / "packages" / "agent-sdk" / "src"
    if _sdk.is_dir():
        sys.path.insert(0, str(_sdk))
    from marketplace_sdk.ollama_local import LocalLLMError, chat_json, check_ollama, default_model  # type: ignore  # noqa: E402

MAX_CHARS = 9000
STANDARD_VAT = 0.16  # Kenya standard VAT rate

_NUM = {"type": ["number", "string"]}
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier": {"type": "string", "maxLength": 120},
        "invoice_number": {"type": "string", "maxLength": 60},
        "invoice_date": {"type": "string", "maxLength": 40},
        "due_date": {"type": "string", "maxLength": 40},
        "currency": {"type": "string", "maxLength": 8},
        "line_items": {
            "type": "array",
            "maxItems": 25,
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "maxLength": 160},
                    "quantity": _NUM,
                    "unit_price": _NUM,
                    "amount": _NUM,
                },
                "required": ["description", "quantity", "unit_price", "amount"],
            },
        },
        "subtotal": _NUM,
        "tax": _NUM,
        "total": _NUM,
    },
    "required": ["supplier", "invoice_number", "invoice_date", "due_date", "currency",
                 "line_items", "subtotal", "tax", "total"],
}

SYSTEM_PROMPT = """You copy fields from an invoice into JSON. Copy values exactly as printed; do not calculate anything.
- supplier: the company that ISSUED the invoice (the seller at the top), NOT the customer under "Bill to".
- invoice_number: as printed (e.g. INV-0042).
- invoice_date, due_date: as printed. If there is no due date, use "".
- currency: 3-letter code, e.g. KES or USD.
- line_items: every product/service row with description, quantity, unit_price, amount as printed.
- subtotal, tax (the VAT amount, not the rate), total (the final amount due): as printed. Use 0 if missing.
Numbers: plain numbers without commas or currency, e.g. 12500.00."""


def parse_number(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace("\u00a0", " ")
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = re.sub(r"[^0-9.,]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.250,50
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,250.50
            s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[1]) == 2:
        s = s.replace(",", ".")  # 1250,50
    else:
        s = s.replace(",", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(v) -> date | None:
    """Kenyan invoices are day-first (05/10/2026 = 5 Oct). None when unsure."""
    if not isinstance(v, str) or not v.strip():
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", v.strip().lower()).replace(",", " ")
    s = re.sub(r"(?<=\d)[-/.](?=[a-z])|(?<=[a-z])[-/.](?=\d)", " ", s)
    s = re.sub(r"\s+", " ", s)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", s)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        try:
            return date(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2}) ([a-z]{3})[a-z]*\.? (\d{4})", s)
    if m and m.group(2) in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r"\b([a-z]{3})[a-z]*\.? (\d{1,2}) (\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
    return None


def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s)


def _printed(n: float, text_digits: str) -> bool:
    cands = {_digits(f"{n:.2f}"), _digits(f"{n:.0f}")}
    return any(c and c in text_digits for c in cands)


def make_validator(text: str):
    low = text.lower()
    squashed = re.sub(r"\s", "", low)
    text_digits = _digits(text)

    def validate(d):
        errs: list[str] = []
        if not isinstance(d, dict):
            return None, ["top level must be an object"]
        supplier = str(d.get("supplier") or "").strip()
        inv_no = str(d.get("invoice_number") or "").strip()
        if not supplier:
            errs.append("supplier is empty")
        elif not any(w in low for w in re.findall(r"[a-z0-9]{3,}", supplier.lower())):
            errs.append(f"supplier {supplier!r} does not appear in the invoice text")
        if not inv_no:
            errs.append("invoice_number is empty")
        elif re.sub(r"\s", "", inv_no.lower()) not in squashed:
            errs.append(f"invoice_number {inv_no!r} is not printed in the invoice; copy it exactly")
        items = []
        for it in d.get("line_items") or []:
            if not isinstance(it, dict):
                continue
            desc = str(it.get("description") or "").strip()
            if not desc:
                continue
            items.append({
                "description": desc,
                "quantity": parse_number(it.get("quantity")),
                "unit_price": parse_number(it.get("unit_price")),
                "amount": parse_number(it.get("amount")),
            })
        total = parse_number(d.get("total"))
        if total is None or total <= 0:
            errs.append("total must be a positive number copied from the invoice")
        elif not _printed(total, text_digits):
            errs.append(f"total {total} is not printed in the invoice; copy the printed total")
        if errs:
            return None, errs
        cur = re.sub(r"[^A-Z]", "", str(d.get("currency") or "").upper())[:3]
        if cur in {"KSH", "KSHS", "KS"}:
            cur = "KES"
        if not cur:
            cur = "KES" if ("kes" in low or "ksh" in low) else ("USD" if "$" in text or "usd" in low else "")
        return {
            "supplier": supplier,
            "invoice_number": inv_no,
            "invoice_date": str(d.get("invoice_date") or "").strip(),
            "due_date": str(d.get("due_date") or "").strip(),
            "currency": cur,
            "line_items": items,
            "subtotal": parse_number(d.get("subtotal")),
            "tax": parse_number(d.get("tax")),
            "total": total,
        }, []

    return validate


def find_anomalies(f: dict) -> list[str]:
    """Deterministic checks on the extracted fields (no LLM)."""
    out: list[str] = []
    tol = 1.0
    items = f["line_items"]
    for it in items:
        q, u, a = it["quantity"], it["unit_price"], it["amount"]
        if None not in (q, u, a) and abs(q * u - a) > tol:
            out.append(f"Line '{it['description'][:50]}': {q:g} x {u:,.2f} = {q*u:,.2f} but amount shows {a:,.2f}")
    seen: dict = {}
    for it in items:
        k = re.sub(r"\W+", " ", it["description"].lower()).strip()
        if k in seen and it["amount"] == seen[k]:
            out.append(f"Possible duplicate line: '{it['description'][:50]}'")
        seen[k] = it["amount"]
    amounts = [it["amount"] for it in items if it["amount"] is not None]
    sub, tax, total = f["subtotal"], f["tax"], f["total"]
    if amounts and sub and abs(sum(amounts) - sub) > tol:
        out.append(f"Line items sum to {sum(amounts):,.2f} but subtotal shows {sub:,.2f}")
    if sub and tax is not None and total and abs(sub + tax - total) > tol:
        out.append(f"Subtotal {sub:,.2f} + tax {tax:,.2f} = {sub+tax:,.2f} but total shows {total:,.2f}")
    if sub and tax:
        rate = tax / sub
        if abs(rate - STANDARD_VAT) > 0.005:
            out.append(f"Tax is {rate:.1%} of subtotal (Kenya standard VAT is 16%)")
    inv_d, due_d = parse_date(f["invoice_date"]), parse_date(f["due_date"])
    if inv_d and due_d and due_d < inv_d:
        out.append(f"Due date {due_d.isoformat()} is before invoice date {inv_d.isoformat()}")
    if not f["due_date"]:
        out.append("No due date on invoice")
    return out


def _fmt(cur: str, n: float | None) -> str:
    return "" if n is None else f"{cur} {n:,.2f}".strip()


def _iso(s: str) -> str:
    d = parse_date(s)
    return d.isoformat() if d else s


def extract_invoice(text: str, model: str | None = None, check: bool = True) -> dict:
    """Return {output, usage, source, model, meta}. Raises LocalLLMError on failure."""
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise LocalLLMError("empty_input", "no invoice text provided (scanned PDFs need OCR first)")
    if len(text) > MAX_CHARS:
        raise LocalLLMError("input_too_long", f"invoice text is {len(text)} chars; local limit is {MAX_CHARS}")
    model = model or default_model()
    if check:
        res = check_ollama(model=model)
        if not res.ok:
            raise LocalLLMError(res.code, res.message, {"check": res.to_dict()})
    r = chat_json(SYSTEM_PROMPT, f"Invoice:\n\"\"\"\n{text.strip()}\n\"\"\"\nReturn the JSON.",
                  schema=INVOICE_SCHEMA, validate=make_validator(text), model=model, num_predict=900)
    f = r["output"]
    output = {
        # keys kept compatible with the previous demo output
        "supplier": f["supplier"],
        "invoice_number": f["invoice_number"],
        "amount": _fmt(f["currency"], f["total"]),
        "tax": _fmt(f["currency"], f["tax"]),
        "due_date": _iso(f["due_date"]),
        "anomalies": find_anomalies(f),
        # structured extras
        "invoice_date": _iso(f["invoice_date"]),
        "currency": f["currency"],
        "subtotal": f["subtotal"],
        "tax_amount": f["tax"],
        "total": f["total"],
        "line_items": f["line_items"],
    }
    return {"output": output, "usage": r["usage"], "source": "ollama", "model": model,
            "meta": {"attempts": [r["attempts"]], "chunks": 1, "latency_ms": r["latency_ms"],
                     "warnings": [], "raw_outputs": r["raw_outputs"]}}
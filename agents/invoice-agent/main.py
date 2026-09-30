"""Invoice Analyzer Agent — implements /invoke for container and local runtimes.

Local path: field extraction on Ollama llama3.2:1b (127.0.0.1:11434 only) via
``invoice_extract`` + deterministic arithmetic/VAT/date anomaly checks.
On failure returns status="failed" with error.code (not_running, model_missing,
wrong_host, invalid_output, empty_input, input_too_long). The old canned demo
output is only returned when INVOICE_ALLOW_CANNED=1 (source="canned").
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from invoice_extract import LocalLLMError, check_ollama, extract_invoice  # sibling module

CANNED_INVOICE_OUTPUT = {
    "supplier": "Acme Supplies Ltd",
    "invoice_number": "INV-2026-0847",
    "amount": "$4,250.00",
    "tax": "$637.50",
    "due_date": "2026-09-15",
    "anomalies": ["Line item quantity exceeds PO by 15%"],
}

app = FastAPI(title="Invoice Analyzer Agent")


class InvokeRequest(BaseModel):
    input: str | dict
    context: dict = {}


def _input_text(input_data: str | dict) -> str:
    if isinstance(input_data, str):
        return input_data
    for key in ("text", "invoice", "message", "content"):
        if isinstance(input_data.get(key), str):
            return input_data[key]
    return str(input_data)


def invoice_response(text: str) -> dict:
    try:
        r = extract_invoice(text)
        return {"status": "completed", "output": r["output"], "usage": r["usage"], "source": "ollama",
                "model": r["model"], "meta": {k: v for k, v in r["meta"].items() if k != "raw_outputs"}}
    except LocalLLMError as exc:
        err = {"code": exc.code, "message": exc.message}
        usage = exc.details.get("usage") or {"input_tokens": 0, "output_tokens": 0}
    except Exception as exc:  # noqa: BLE001
        err = {"code": "internal_error", "message": str(exc)[:300]}
        usage = {"input_tokens": 0, "output_tokens": 0}
    if os.getenv("INVOICE_ALLOW_CANNED", "0").lower() in {"1", "true", "yes"}:
        return {"status": "completed", "output": dict(CANNED_INVOICE_OUTPUT),
                "usage": {"input_tokens": 120, "output_tokens": 85}, "source": "canned", "error": err}
    return {"status": "failed", "error": err, "usage": usage, "source": "ollama"}


@app.post("/invoke")
async def invoke(body: InvokeRequest):
    return invoice_response(_input_text(body.input))


@app.get("/health")
async def health():
    return {"status": "ok", "ollama": check_ollama().to_dict()}
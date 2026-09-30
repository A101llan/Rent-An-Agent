"""Agent invoke handlers for demo-agent container."""

import json
import os
import re

import httpx

CANNED_MEETING_OUTPUT = {
    "summary": "Team aligned on Q4 launch timeline and ownership of follow-ups.",
    "decisions": [
        "Ship beta by Oct 15",
        "Use weekly standup for launch blockers only",
    ],
    "action_items": [
        {"owner": "Alex", "task": "Draft launch checklist and share by Friday"},
        {"owner": "Jordan", "task": "Fix onboarding email bug before beta"},
        {"owner": "Sam", "task": "Confirm design freeze with stakeholders"},
    ],
    "open_questions": [
        "Do we need a soft launch for existing customers?",
        "Who owns post-launch metrics dashboard?",
    ],
}

CANNED_MEETING_USAGE = {"input_tokens": 90, "output_tokens": 120}


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "llama3.2:1b")


def _meeting_extraction_prompt(notes: str) -> tuple[str, str]:
    system = (
        "You extract structured meeting notes. "
        "Respond with ONLY valid JSON (no markdown fences, no commentary) matching this schema:\n"
        '{"summary": string, "decisions": [string], '
        '"action_items": [{"owner": string, "task": string}], '
        '"open_questions": [string]}\n'
        "If a field is unknown use an empty string or empty list."
    )
    user = f"Extract meeting notes from the following text:\n\n{notes}"
    return system, user


def _parse_meeting_json(raw: str) -> dict | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    for key in ("summary", "decisions", "action_items", "open_questions"):
        if key not in data:
            return None
    if not isinstance(data["summary"], str):
        return None
    if not isinstance(data["decisions"], list) or not all(isinstance(x, str) for x in data["decisions"]):
        return None
    if not isinstance(data["open_questions"], list) or not all(isinstance(x, str) for x in data["open_questions"]):
        return None
    if not isinstance(data["action_items"], list):
        return None
    for item in data["action_items"]:
        if not isinstance(item, dict):
            return None
        if "owner" not in item or "task" not in item:
            return None
        if not isinstance(item["owner"], str) or not isinstance(item["task"], str):
            return None
    return {
        "summary": data["summary"],
        "decisions": data["decisions"],
        "action_items": [{"owner": i["owner"], "task": i["task"]} for i in data["action_items"]],
        "open_questions": data["open_questions"],
    }


def extract_meeting_notes_via_ollama(notes: str) -> dict | None:
    """Call local Ollama for structured meeting extraction. None on any failure."""
    try:
        system, user = _meeting_extraction_prompt(notes)
        url = f"{_ollama_base_url()}/api/chat"
        payload = {
            "model": _ollama_model(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            content = (data.get("message") or {}).get("content", "")
            parsed = _parse_meeting_json(content)
            if not parsed:
                return None
            usage = {
                "input_tokens": data.get("prompt_eval_count") or max(1, len(notes.split())),
                "output_tokens": data.get("eval_count") or max(1, len(content.split())),
            }
            return {"output": parsed, "usage": usage}
    except Exception:
        return None


def meeting_notes_response(notes: str) -> dict:
    """Prefer Ollama extraction; fall back to canned meeting notes JSON."""
    result = extract_meeting_notes_via_ollama(notes)
    if result:
        return {
            "status": "completed",
            "output": result["output"],
            "usage": result["usage"],
        }
    return {
        "status": "completed",
        "output": dict(CANNED_MEETING_OUTPUT),
        "usage": dict(CANNED_MEETING_USAGE),
    }



ASSETS = [
    {"id": "LT-001", "type": "Laptop", "name": "Dell Latitude 5540", "assigned_to": "John M.", "maintenance_due": "2026-08-20", "status": "due"},
    {"id": "LT-007", "type": "Laptop", "name": "MacBook Pro 14", "assigned_to": "Sarah K.", "maintenance_due": "2026-08-18", "status": "due"},
    {"id": "LT-012", "type": "Laptop", "name": "ThinkPad X1", "assigned_to": "Mike R.", "maintenance_due": "2026-10-01", "status": "ok"},
    {"id": "VEH-002", "type": "Vehicle", "name": "Toyota Hilux", "assigned_to": "Field Team", "maintenance_due": "2026-07-30", "insurance_expiry": "2026-07-01"},
]

HIGH_RISK_ACTIONS = {
    "send email": ("SEND_EMAIL", "Send Email", "Agent wants to send an email on your behalf."),
    "delete record": ("DELETE_RECORD", "Delete Record", "Agent wants to delete a record."),
    "execute payment": ("EXECUTE_PAYMENT", "Execute Payment", "Agent wants to process a payment."),
    "purchase order": ("CREATE_PURCHASE_ORDER", "Create Purchase Order", "Agent wants to create a purchase order."),
}


def invoke_agent(agent_name: str, payload: dict) -> dict:
    input_data = payload.get("input", "")
    text = input_data if isinstance(input_data, str) else str(input_data.get("message", input_data))
    lower = text.lower()
    name = agent_name.lower()

    # High-risk actions trigger approval workflow
    for keyword, (action, title, desc) in HIGH_RISK_ACTIONS.items():
        if keyword in lower:
            return {
                "status": "waiting_for_approval",
                "action": action,
                "approval": {
                    "title": title,
                    "description": desc,
                    "details": {"keyword": keyword, "input_preview": text[:200]},
                },
                "usage": {"input_tokens": 20, "output_tokens": 0},
            }

    if "invoice" in name or "invoice" in lower:
        return {
            "status": "completed",
            "output": {
                "supplier": "Acme Supplies Ltd",
                "invoice_number": "INV-2026-0847",
                "amount": "$4,250.00",
                "tax": "$637.50",
                "due_date": "2026-09-15",
                "anomalies": ["Line item quantity exceeds PO by 15%"],
            },
            "usage": {"input_tokens": 120, "output_tokens": 85},
        }

    if "asset" in name or "maintenance" in lower or "laptop" in lower:
        assets = [a for a in ASSETS if a["type"] == "Laptop" and a.get("maintenance_due")]
        return {
            "status": "completed",
            "output": {"assets": assets, "recommendation": f"{len(assets)} laptops require maintenance."},
            "usage": {"input_tokens": 95, "output_tokens": 110},
        }

    if "research" in name or "fintech" in lower:
        return {
            "status": "completed",
            "output": {
                "summary": "Kenyan fintech market growing at 22% CAGR",
                "competitors": ["M-Pesa", "Tala", "Branch"],
                "recommendations": ["Focus on B2B invoice financing"],
            },
            "usage": {"input_tokens": 80, "output_tokens": 150},
        }

    if "resume" in name:
        return {
            "status": "completed",
            "output": {"score": 78, "strengths": ["Python", "FastAPI"], "recommendation": "Proceed to interview"},
            "usage": {"input_tokens": 200, "output_tokens": 60},
        }

    if "meeting" in name or "notes" in name or "meeting" in lower or "action item" in lower:
        return meeting_notes_response(text)

    if "support" in name:
        return {
            "status": "completed",
            "output": {"response": "Thank you for contacting us. Your request SUP-2026-4421 has been logged."},
            "usage": {"input_tokens": 50, "output_tokens": 40},
        }

    return {"status": "completed", "output": f"Processed: {text[:300]}", "usage": {"input_tokens": 30, "output_tokens": 20}}

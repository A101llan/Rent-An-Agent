"""Asset management demo agent with structured business data."""

ASSETS = [
    {"id": "LT-001", "type": "Laptop", "name": "Dell Latitude 5540", "assigned_to": "John M.", "maintenance_due": "2026-08-20", "purchase_date": "2024-03-15", "value_pct": 65, "insurance_expiry": "2026-12-01"},
    {"id": "LT-007", "type": "Laptop", "name": "MacBook Pro 14", "assigned_to": "Sarah K.", "maintenance_due": "2026-08-18", "purchase_date": "2023-11-01", "value_pct": 45, "insurance_expiry": "2026-06-15"},
    {"id": "LT-012", "type": "Laptop", "name": "ThinkPad X1", "assigned_to": "Mike R.", "maintenance_due": "2026-10-01", "purchase_date": "2025-01-10", "value_pct": 85, "insurance_expiry": "2027-01-10"},
    {"id": "DT-003", "type": "Desktop", "name": "HP EliteDesk", "assigned_to": "Finance Dept", "maintenance_due": "2026-09-01", "purchase_date": "2022-06-01", "value_pct": 30, "insurance_expiry": None},
    {"id": "MON-015", "type": "Monitor", "name": "Dell UltraSharp 27", "assigned_to": "John M.", "maintenance_due": None, "purchase_date": "2024-01-20", "value_pct": 70, "insurance_expiry": None},
    {"id": "VEH-002", "type": "Vehicle", "name": "Toyota Hilux", "assigned_to": "Field Team", "maintenance_due": "2026-07-30", "purchase_date": "2021-04-01", "value_pct": 55, "insurance_expiry": "2026-07-01"},
    {"id": "PRT-008", "type": "Printer", "name": "HP LaserJet Pro", "assigned_to": "Office", "maintenance_due": "2026-08-25", "purchase_date": "2023-08-01", "value_pct": 50, "insurance_expiry": None},
    {"id": "NET-004", "type": "Network Equipment", "name": "Cisco Switch 48-port", "assigned_to": "IT", "maintenance_due": "2026-11-01", "purchase_date": "2022-01-15", "value_pct": 40, "insurance_expiry": None},
]

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Asset Management Agent")


class InvokeRequest(BaseModel):
    input: str | dict
    context: dict = {}


@app.post("/invoke")
async def invoke(body: InvokeRequest):
    text = (body.input if isinstance(body.input, str) else str(body.input)).lower()

    if "john" in text:
        assets = [a for a in ASSETS if "john" in a["assigned_to"].lower()]
        return {"status": "completed", "output": {"assets": assets}, "usage": {"input_tokens": 40, "output_tokens": 80}}

    if "maintenance" in text or "laptop" in text:
        assets = [a for a in ASSETS if a["type"] == "Laptop" and a["maintenance_due"]]
        return {"status": "completed", "output": {"assets": assets, "recommendation": f"{len(assets)} laptops tracked for maintenance"}, "usage": {"input_tokens": 50, "output_tokens": 100}}

    if "insurance" in text or "vehicle" in text:
        assets = [a for a in ASSETS if a["type"] == "Vehicle" or (a.get("insurance_expiry") and "expir" in text)]
        expired = [a for a in ASSETS if a.get("insurance_expiry") and a["insurance_expiry"] < "2026-08-11"]
        return {"status": "completed", "output": {"assets": assets, "expired_insurance": expired}, "usage": {"input_tokens": 45, "output_tokens": 90}}

    if "quarter" in text or "purchased" in text:
        assets = [a for a in ASSETS if a["purchase_date"] >= "2026-01-01"]
        return {"status": "completed", "output": {"assets": assets, "count": len(assets)}, "usage": {"input_tokens": 35, "output_tokens": 70}}

    if "depreciat" in text or "20%" in text:
        assets = [a for a in ASSETS if a["value_pct"] < 20]
        return {"status": "completed", "output": {"assets": assets, "below_threshold": len(assets)}, "usage": {"input_tokens": 40, "output_tokens": 60}}

    return {"status": "completed", "output": {"assets": ASSETS, "total": len(ASSETS)}, "usage": {"input_tokens": 30, "output_tokens": 50}}


@app.get("/health")
async def health():
    return {"status": "ok"}

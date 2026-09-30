"""Unified demo agent container — routes by AGENT_SLUG env var."""

import os

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="AgentHub Demo Agent")

AGENT_SLUG = os.getenv("AGENT_SLUG", "invoice-analyzer")


class InvokeRequest(BaseModel):
    input: str | dict
    context: dict = {}


# Inline handlers (mirror runtime-manager/app/agents/handlers.py)
def _handle(slug: str, payload: dict) -> dict:
    from handlers import invoke_agent
    return invoke_agent(slug, payload)


@app.post("/invoke")
async def invoke(body: InvokeRequest):
    return _handle(AGENT_SLUG, {"input": body.input, "context": body.context})


@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_SLUG}

# Agent SDK

Python SDK for building AgentHub marketplace agents.

## Quick Start

```python
from marketplace_sdk import Agent, ExecutionContext

class MyAgent(Agent):
    async def run(self, request: dict, context: ExecutionContext) -> dict:
        if not context.has_permission("files.read"):
            return {"status": "error", "message": "Permission denied"}
        return {"status": "completed", "result": "..."}
```

## Packaging

1. Implement your agent extending `Agent`
2. Create a `manifest.json` (see `agents/invoice-agent/manifest.json`)
3. Build Docker image with immutable digest
4. Publish via developer dashboard

See [docs/AGENT_SDK.md](../../docs/AGENT_SDK.md) for full documentation.

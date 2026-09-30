# AgentHub SDK

Guide for external developers building marketplace agents.

## Base Class

```python
from marketplace_sdk import Agent, ExecutionContext

class InvoiceAgent(Agent):
    async def run(self, request: dict, context: ExecutionContext) -> dict:
        return {
            "status": "completed",
            "result": {...},
        }
```

## Execution Context

- `session_id` — current rental session
- `permissions` — granted capabilities
- `has_permission(name)` — check before sensitive operations

## Container Contract

Agents must expose:

```
POST /invoke
```

Request:
```json
{"input": "...", "context": {}}
```

Response:
```json
{"status": "completed", "output": "...", "usage": {"input_tokens": 100}}
```

## Manifest

See `agents/invoice-agent/manifest.json` for the standard format.

## Security

- Run as non-root
- Never embed secrets in the image
- Request permissions explicitly in manifest
- Use session-scoped credentials from the platform

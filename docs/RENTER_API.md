# Renter API Guide

How to integrate AgentHub agents into **your own system** — ERP, portal, or internal tools — without using the AgentHub workspace.

## Recommended: embed widget (no dev experience)

After hiring an agent, copy the **embed snippet** and API key from the hire confirmation screen.

```html
<!-- AgentHub Agent Widget -->
<script src="http://localhost:3000/embed.js"
  data-api-key="ahk_live_..."
  data-agenthub-url="http://localhost:3000"
  data-agenthub-api="http://localhost:8000"
  async></script>
```

Paste before `</body>` in your app. A chat bubble appears at the bottom-right of **your** system.

### First-time onboarding

When a user opens the widget, the agent asks a few short questions (company, systems, goals) to learn context. Answers are stored for the rental session and passed to every execution.

### Embed API (used by the widget)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/embed/bootstrap` | `Authorization: Bearer {api_key}` |
| POST | `/api/v1/embed/onboarding` | same |
| POST | `/api/v1/embed/chat` | same |

Preview: open the **demo page** link from the hire screen (`/embed/demo?key=...`).

---

## Programmatic integration (developers)

### Quick start (one call)

```http
POST /api/v1/rentals/hire
Authorization: Bearer {access_token}
Idempotency-Key: hire-invoice-001
Content-Type: application/json

{
  "agent_slug": "invoice-analyzer",
  "pricing_plan_id": "{plan_uuid}",
  "duration_minutes": 30
}
```

Response includes:

- `embed` — API key + HTML snippet for your system
- `session_token` — scoped token for direct API calls
- `session.id` — session UUID

**Store `embed.api_key` immediately.** It is not returned again.

### Session-scoped authentication

```http
X-Session-Token: {session_token}
```

Or for the embed widget:

```http
Authorization: Bearer ahk_live_...
```

### Execute from your backend

```http
POST /api/v1/sessions/{session_id}/execute
X-Session-Token: {session_token}
Content-Type: application/json

{
  "input": "Analyze invoice #INV-4421",
  "context": { "source": "erp", "document_ref": "..." }
}
```

## Typical ERP flow

1. Finance lead hires **Invoice Analyzer** on AgentHub.
2. IT pastes the embed snippet into the AP portal.
3. Widget opens → agent asks 3–4 context questions.
4. Staff chat with the agent inside their existing tool.
5. Session expires → widget returns `410`; rental ends.

## Examples

- Python: `scripts/examples/rent-and-execute.py`
- Interactive docs: http://localhost:8000/docs

# Local runtime API contract

HTTP contract between **apps/api** (cloud) and **apps/local-runtime** (Windows sidecar).
Both sides implement this document; the sidecar helpers live in
`apps/local-runtime/app/api_contract.py`.

> **Auth note:** Sidecar pairing uses the hire-time `session_token` as
> `X-Session-Token`. That token is over-privileged for a long-term device credential;
> a narrower claim code / lease cert is planned (see TODO in `api_contract.py`).

## Error envelope

All error responses use a single top-level object:

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session not found",
    "request_id": "…"
  }
}
```

| HTTP | Typical `code` | When |
|------|----------------|------|
| 401 | `UNAUTHORIZED`, `INVALID_SESSION_TOKEN` | Missing auth, bad JWT, or wrong session token |
| 403 | `FORBIDDEN` | Authenticated user does not own the session |
| 404 | `SESSION_NOT_FOUND` | Unknown `session_id` (same for JWT and `X-Session-Token`) |
| 409 | `SESSION_NOT_LOCAL` | Session exists but is not a local-runtime rental |
| 410 | `SESSION_EXPIRED` | Session past `expires_at` or terminated |
| 422 | `VALIDATION_ERROR` | Request body failed schema validation (usage only) |

Validation errors may include an optional `details` array (Pydantic error list).

## Hire (web / dev scripts)

`POST /api/v1/rentals/hire` returns (among other fields):

```json
{
  "session_token": "…",
  "runtime_provider": "local",
  "session": {
    "id": "…",
    "runtime_provider": "local",
    "session_token": "…"
  },
  "local": {
    "session_id": "…",
    "claim_endpoint": "…/api/v1/sessions/{id}/local/claim",
    "usage_endpoint": "…/api/v1/sessions/{id}/usage",
    "auth_header": "X-Session-Token"
  }
}
```

The sidecar binds with `session.id` + `session_token`; claim codes are not used in the MVP.

## Claim

`POST /api/v1/sessions/{session_id}/local/claim`

- **Auth:** `X-Session-Token: <session_token>` (preferred) or owner `Authorization: Bearer …`
- **Body:** empty JSON object `{}` (optional)

**200 response:**

```json
{
  "session_id": "uuid",
  "expires_at": "2026-09-30T12:00:00Z",
  "manifest": { "runtime": { "type": "local", … }, … },
  "agent_slug": "meeting-notes-agent-local",
  "agent_version": "0.1.0",
  "runtime_provider": "local"
}
```

Sidecar behaviour: store binding on 200; **any non-200 clears the binding** (fail closed).
API unreachable → 503 unless `LOCAL_RUNTIME_OFFLINE_STUB=1` (labeled dev stub only).

## Usage

`POST /api/v1/sessions/{session_id}/usage`

- **Auth:** same as claim
- **Body** (extra fields rejected):

```json
{
  "metric_type": "requests",
  "quantity": 1,
  "unit": "count",
  "execution_id": null
}
```

**201 response:**

```json
{
  "id": "uuid",
  "session_id": "uuid",
  "execution_id": null,
  "metric_type": "requests",
  "quantity": 1.0,
  "unit": "count",
  "recorded_at": "2026-09-30T12:00:00Z"
}
```

Sidecar posts `requests`/1/`count` plus token counts after each successful job.
Non-2xx → logged to `usage-failed.jsonl`; API unreachable → queued in `usage-pending.jsonl`.

## Execute (guard)

`POST /api/v1/sessions/{session_id}/execute` on a local session returns **400**
`RUNTIME_LOCAL` — cloud execution is intentionally blocked; the sidecar never calls this.

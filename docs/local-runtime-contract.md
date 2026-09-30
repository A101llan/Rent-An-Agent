# Local Runtime API Contract

The local sidecar uses the API to claim a rented local agent and report metering. Base path: `/api/v1`.

## Authentication

Send `X-Session-Token: <session_token>` (the token returned by hire) or an owner `Authorization: Bearer <JWT>` header. Token authentication is preferred for a sidecar. All errors use the existing API error envelope and clients key on `detail.error.code` (not only HTTP status):

```json
{"detail":{"error":{"code":"INVALID_SESSION_TOKEN","message":"Invalid session token","request_id":"..."}}}
```

## Endpoints

### Claim ? `POST /sessions/{id}/local/claim`

The body is empty. A successful claim returns `200`:

```json
{"session_id":"...","expires_at":"...","manifest":{},"agent_slug":"...","agent_version":"...","runtime_provider":"local"}
```

Claim never extends `expires_at`; the cloud expiry job owns expiry. The first successful claim changes the runtime status to `running`.

### Usage ? `POST /sessions/{id}/usage`

Request body:

```json
{"metric_type":"documents_processed","quantity":2,"unit":"count","execution_id":"..."}
```

`execution_id` is optional. `quantity` must be greater than zero; unknown fields and other invalid bodies are rejected. A successful report returns `201`, including the record id, session id, metric type, quantity, unit, optional execution id, and the recorded timestamp (`recorded_at`).

### Execute guard ? `POST /sessions/{id}/execute`

Local sessions cannot execute in the cloud. The endpoint returns `400` with code `RUNTIME_LOCAL`.

## Errors and retry policy

| Status | Code | Meaning | Retryable? |
|---:|---|---|---|
| 401 | `INVALID_SESSION_TOKEN` | Missing/wrong token, including an unknown id on the token path | No |
| 401 | existing auth code | No JWT and no session token | No |
| 404 | `SESSION_NOT_FOUND` | Unknown session or owner JWT for another user's session | No |
| 409 | `SESSION_NOT_LOCAL` | Session does not use the local runtime | No |
| 410 | `SESSION_EXPIRED` | Session expired or ended | No |
| 422 | `VALIDATION_ERROR` | Invalid request body, including `quantity <= 0` | No |
| 5xx | existing server error code | Temporary server failure | Yes |

Only network errors and 5xx responses are retryable. Only those failures may be queued locally for usage; every 4xx is terminal. Claim fails closed on any non-200 response.

## Runtime lifecycle

For a local hire, the response includes `runtime_provider: "local"` and the session runtime starts as `provisioning`. The sidecar claims the session; the first successful claim sets it to `running`. Cloud expiry or session termination ends the session and subsequent local-sidecar calls return `SESSION_EXPIRED`.

Clients must ignore unknown response fields so additive API fields remain compatible.



"""Shared HTTP contract helpers for AgentHub local-runtime ↔ apps/api.

Canonical error envelope (all local-runtime endpoints):

    {"error": {"code": str, "message": str, "request_id": str | null, ...}}

AppError responses are normalized by apps/api's global exception handler. Validation
errors (422) use the same top-level ``error`` object with code ``VALIDATION_ERROR``.

TODO(auth): ``session_token`` grants full session-scoped API access today; a narrower
device credential (claim code / lease cert) is planned but out of scope here.
"""

from __future__ import annotations

from typing import Any

# Sidecar-internal codes mapped from HTTP status when claim fails.
CLAIM_HTTP_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "session_not_found",
    409: "not_local_session",
    410: "session_expired",
    422: "validation_error",
}


def parse_api_error(body: Any) -> dict[str, Any] | None:
    """Extract ``{"code", "message", ...}`` from an API error response body."""
    if not isinstance(body, dict):
        return None
    if isinstance(body.get("error"), dict):
        return body["error"]
    detail = body.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        return detail["error"]
    return None


def claim_error_code(http_status: int | None, body: Any) -> str:
    """Map a failed claim HTTP response to a stable sidecar error code."""
    parsed = parse_api_error(body)
    if parsed and parsed.get("code"):
        return str(parsed["code"]).lower()
    if http_status is not None:
        return CLAIM_HTTP_STATUS_CODES.get(http_status, "claim_failed")
    return "claim_failed"


def normalize_claim_success(body: Any) -> dict[str, Any] | None:
    """Validate a 200 claim response; return normalized fields or None if invalid."""
    if not isinstance(body, dict):
        return None
    session_id = body.get("session_id")
    if not session_id:
        return None
    return {
        "session_id": str(session_id),
        "expires_at": body.get("expires_at"),
        "manifest": body.get("manifest") if isinstance(body.get("manifest"), dict) else {},
        "agent_slug": body.get("agent_slug"),
        "agent_version": body.get("agent_version"),
        "runtime_provider": body.get("runtime_provider"),
    }


def normalize_usage_success(body: Any) -> dict[str, Any] | None:
    """Validate a 201 usage response; return normalized fields or None if invalid."""
    if not isinstance(body, dict):
        return None
    record_id = body.get("id")
    session_id = body.get("session_id")
    metric_type = body.get("metric_type")
    if not record_id or not session_id or not metric_type:
        return None
    return {
        "id": str(record_id),
        "session_id": str(session_id),
        "execution_id": body.get("execution_id"),
        "metric_type": str(metric_type),
        "quantity": body.get("quantity"),
        "unit": body.get("unit"),
        "recorded_at": body.get("recorded_at"),
    }

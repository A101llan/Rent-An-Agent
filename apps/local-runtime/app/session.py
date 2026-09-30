"""Cloud session claim + usage reporting for the local runtime.

Contract: docs/LOCAL_RUNTIME_API.md (helpers in api_contract.py).

Rules enforced here:
  * FAIL CLOSED on any non-200 claim response (no extraction allowed).
  * Offline stub bind ONLY when the API is unreachable (refused/timeout) AND
    LOCAL_RUNTIME_OFFLINE_STUB=1 (config.OFFLINE_STUB). Clearly labeled mode.
  * Usage: API unreachable -> append to local pending queue (usage-pending.jsonl)
    for later sync; non-2xx HTTP -> logged failure (usage-failed.jsonl), never
    reported as success.
  * Never calls runtime-manager.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from . import config
from .api_contract import (
    claim_error_code,
    normalize_claim_success,
    normalize_usage_success,
    parse_api_error,
)

logger = logging.getLogger("local-runtime.session")

MODE_CLAIMED = "claimed"
MODE_OFFLINE_STUB = "offline_stub"
ACTIVE_MODES = {MODE_CLAIMED, MODE_OFFLINE_STUB}

_bound: dict[str, Any] = {}
_state_lock = threading.RLock()
_queue_lock = threading.Lock()


# ---------------------------------------------------------------- helpers

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_expires_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _api_url(template: str, session_id: str) -> str:
    return config.AGENTHUB_API_BASE + template.format(session_id=session_id)


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return {kind: ok|http_error|unreachable, status, body, error}."""
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Session-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    def _decode(raw: bytes) -> Any:
        text = raw.decode("utf-8", errors="replace") if raw else ""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[:500]

    try:
        with urllib.request.urlopen(req, timeout=config.API_TIMEOUT_SECONDS) as resp:
            return {"kind": "ok", "status": resp.status, "body": _decode(resp.read()), "error": None}
    except urllib.error.HTTPError as exc:  # must precede URLError
        try:
            body = _decode(exc.read())
        except Exception:
            body = None
        return {"kind": "http_error", "status": exc.code, "body": body, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"kind": "unreachable", "status": None, "body": None, "error": str(reason)}


def _claim_route_present() -> bool | None:
    """Diagnostic only: is the claim route in the live OpenAPI schema?"""
    res = _http_json("GET", config.AGENTHUB_API_BASE + "/openapi.json")
    if res["kind"] != "ok" or not isinstance(res["body"], dict):
        return None
    paths = res["body"].get("paths") or {}
    return config.CLAIM_PATH_TEMPLATE in paths or any(p.endswith("/local/claim") for p in paths)


# ---------------------------------------------------------------- state

def _serializable(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    if isinstance(payload.get("expires_at"), datetime):
        payload["expires_at"] = payload["expires_at"].isoformat()
    return payload


def _persist() -> None:
    try:
        config.SESSION_STORE_PATH.write_text(
            json.dumps(_serializable(_bound), indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("failed to persist session: %s", exc)


def _load() -> None:
    path = config.SESSION_STORE_PATH
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    # Legacy/unlabeled stub bindings (pre fail-closed) are NOT honoured.
    if data.get("bound") and data.get("mode") in ACTIVE_MODES:
        data["expires_at"] = _parse_expires_at(data.get("expires_at"))
        _bound.update(data)
    else:
        logger.info("ignoring stored session without claimed/offline_stub mode")


_load()


def reload_from_disk() -> None:
    with _state_lock:
        _bound.clear()
        _load()


def _clear(reason: dict[str, Any]) -> None:
    """Fail closed: drop any previous binding and record why."""
    with _state_lock:
        _bound.clear()
        _bound.update({"bound": False, "mode": None, "last_error": reason, "at": _now_iso()})
        _persist()


def get_bound() -> dict[str, Any]:
    with _state_lock:
        return dict(_bound)


def public_summary() -> dict[str, Any]:
    """Binding info safe to write to disk/logs (no token)."""
    with _state_lock:
        exp = _bound.get("expires_at")
        return {
            "bound": bool(_bound.get("bound")),
            "mode": _bound.get("mode"),
            "session_id": _bound.get("session_id"),
            "expires_at": exp.isoformat() if isinstance(exp, datetime) else exp,
            "claimed_at": _bound.get("claimed_at"),
            "api_base": _bound.get("api_base"),
            "offline_stub_warning": _bound.get("offline_stub_warning"),
            "last_error": _bound.get("last_error"),
        }


def is_expired() -> bool:
    expires = _bound.get("expires_at")
    if not isinstance(expires, datetime):
        return False
    return datetime.now(timezone.utc) >= expires


def require_active() -> dict[str, Any] | None:
    """None if extraction may run; else an error dict (fail closed)."""
    with _state_lock:
        if not _bound.get("bound") or _bound.get("mode") not in ACTIVE_MODES:
            return {
                "error": "session_not_bound",
                "detail": "claim a session first (POST /session/claim); runs are refused without a claimed session",
                "last_error": _bound.get("last_error"),
                "status_code": 403,
            }
        if is_expired():
            return {
                "error": "session_expired",
                "detail": "bound session past expires_at",
                "status_code": 410,
            }
    return None


def _store_bound(
    *,
    token: str,
    sid: str,
    mode: str,
    expires_at: datetime | None,
    manifest: dict[str, Any] | None,
    remote: dict[str, Any] | None,
    warning: str | None = None,
) -> dict[str, Any]:
    with _state_lock:
        _bound.clear()
        _bound.update(
            {
                "bound": True,
                "mode": mode,
                "session_token": token,
                "session_id": sid,
                "expires_at": expires_at,
                "manifest": manifest if isinstance(manifest, dict) else {},
                "validated": mode == MODE_CLAIMED,
                "claimed": mode == MODE_CLAIMED,
                "claimed_at": _now_iso(),
                "api_base": config.AGENTHUB_API_BASE,
                "remote": remote if isinstance(remote, dict) else {},
                "offline_stub_warning": warning,
            }
        )
        _persist()
        return {
            "bound": True,
            "mode": mode,
            "session_id": sid,
            "validated": mode == MODE_CLAIMED,
            "claimed": mode == MODE_CLAIMED,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "manifest": _bound["manifest"],
            **({"warning": warning} if warning else {}),
        }


# ---------------------------------------------------------------- claim

def claim_session(session_token: str, session_id: str) -> dict[str, Any]:
    """POST .../local/claim. Fail closed on any non-200 response."""
    token = (session_token or "").strip()
    sid = (session_id or "").strip()
    if not token:
        return {"bound": False, "error": "session_token_required", "status_code": 400}
    if not sid:
        return {"bound": False, "error": "session_id_required", "status_code": 400}

    url = _api_url(config.CLAIM_PATH_TEMPLATE, sid)
    res = _http_json("POST", url, token=token, payload={})

    if res["kind"] == "ok" and res["status"] == 200:
        claim = normalize_claim_success(res["body"])
        if not claim:
            reason = {
                "error": "invalid_claim_response",
                "http_status": 200,
                "detail": res["body"],
                "url": url,
            }
            logger.warning("claim failed closed: invalid 200 body")
            _clear(reason)
            return {"bound": False, "fail_closed": True, "status_code": 502, **reason}
        claimed_sid = claim["session_id"]
        expires_at = _parse_expires_at(claim.get("expires_at"))
        logger.info("local claim OK session_id=%s expires_at=%s", claimed_sid, expires_at)
        result = _store_bound(
            token=token,
            sid=claimed_sid,
            mode=MODE_CLAIMED,
            expires_at=expires_at,
            manifest=claim["manifest"],
            remote=res["body"] if isinstance(res["body"], dict) else {},
        )
        if expires_at and datetime.now(timezone.utc) >= expires_at:
            _clear({"error": "session_expired", "http_status": 200, "detail": "expires_at already past"})
            return {"bound": False, "error": "session_expired", "fail_closed": True, "status_code": 410}
        return result

    if res["kind"] == "unreachable":
        if config.OFFLINE_STUB:
            warning = (
                f"OFFLINE STUB: AgentHub API unreachable at {config.AGENTHUB_API_BASE} "
                f"({res['error']}); session NOT validated by cloud. Dev use only; "
                "usage rows will be queued locally."
            )
            logger.warning(warning)
            return _store_bound(
                token=token, sid=sid, mode=MODE_OFFLINE_STUB,
                expires_at=None, manifest={}, remote={}, warning=warning,
            )
        reason = {
            "error": "api_unreachable",
            "detail": res["error"],
            "api_base": config.AGENTHUB_API_BASE,
            "hint": "start apps/api, or set LOCAL_RUNTIME_OFFLINE_STUB=1 for a labeled dev stub",
        }
        logger.warning("claim failed closed: API unreachable (%s)", res["error"])
        _clear(reason)
        return {"bound": False, "fail_closed": True, "status_code": 503, **reason}

    # Any HTTP response other than 200 -> fail closed.
    status = res["status"]
    api_error = parse_api_error(res["body"])
    code = claim_error_code(status, res["body"])
    reason: dict[str, Any] = {
        "error": code,
        "http_status": status,
        "detail": res["body"],
        "url": url,
    }
    if api_error:
        reason["api_error"] = api_error
    if status == 404:
        present = _claim_route_present()
        reason["claim_route_present_in_openapi"] = present
        if present is False:
            reason["hint"] = "claim route not deployed on this API yet (Local Rent Architect)"
    logger.warning("claim failed closed: HTTP %s (%s)", status, code)
    _clear(reason)
    known_statuses = {400, 401, 403, 404, 409, 410, 422}
    return {
        "bound": False,
        "fail_closed": True,
        "status_code": status if status in known_statuses else 502,
        **reason,
    }


def bind_session(session_token: str, session_id: str | None = None) -> dict[str, Any]:
    """Back-compat alias for claim; session_id is now required."""
    if not (session_id or "").strip():
        return {
            "bound": False,
            "error": "session_id_required",
            "detail": "bind requires session_id (claim is POST /api/v1/sessions/{id}/local/claim)",
            "status_code": 400,
        }
    return claim_session(session_token, session_id or "")


# ---------------------------------------------------------------- usage

def build_usage_payload(
    metric_type: str,
    quantity: float | int,
    unit: str,
    execution_id: Any = None,
) -> dict[str, Any]:
    """Usage request body: {metric_type, quantity(>0), unit, execution_id?}."""
    return {
        "metric_type": metric_type,
        "quantity": quantity,
        "unit": unit,
        "execution_id": execution_id,
    }


def _append_jsonl(path, row: dict[str, Any]) -> None:
    with _queue_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def _read_jsonl(path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_jsonl(path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def report_usage_metric(
    metric_type: str,
    quantity: float | int,
    unit: str,
    execution_id: Any = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """POST one usage metric. Outcome: sent | queued | failed | skipped."""
    base = {"metric_type": metric_type, "quantity": quantity, "unit": unit}
    if not isinstance(quantity, (int, float)) or quantity <= 0:
        return {**base, "outcome": "skipped", "reason": "quantity must be > 0"}
    with _state_lock:
        sid = _bound.get("session_id")
        token = _bound.get("session_token")
        mode = _bound.get("mode")
    if not _bound.get("bound") or not sid or not token:
        return {**base, "outcome": "skipped", "reason": "no bound session"}

    payload = build_usage_payload(metric_type, quantity, unit, execution_id)
    url = _api_url(config.USAGE_PATH_TEMPLATE, str(sid))
    res = _http_json("POST", url, token=str(token), payload=payload)

    if res["kind"] == "ok":
        cloud_row = normalize_usage_success(res["body"]) or res["body"]
        logger.info("usage SENT metric_type=%s status=%s", metric_type, res["status"])
        return {**base, "outcome": "sent", "http_status": res["status"], "cloud_row": cloud_row}

    if res["kind"] == "unreachable":
        row = {
            "status": "pending_sync",
            "queued_at": _now_iso(),
            "session_id": sid,
            "bind_mode": mode,
            "job_id": job_id,
            "payload": payload,
            "reason": f"api_unreachable: {res['error']}",
            "attempts": 0,
        }
        _append_jsonl(config.USAGE_QUEUE_PATH, row)
        logger.warning(
            "usage QUEUED locally (API unreachable) metric_type=%s -> %s",
            metric_type, config.USAGE_QUEUE_PATH,
        )
        return {**base, "outcome": "queued", "queue_path": str(config.USAGE_QUEUE_PATH), "reason": row["reason"]}

    api_error = parse_api_error(res["body"])
    row = {
        "status": "failed",
        "failed_at": _now_iso(),
        "session_id": sid,
        "bind_mode": mode,
        "job_id": job_id,
        "payload": payload,
        "url": url,
        "http_status": res["status"],
        "detail": res["body"],
        "api_error": api_error,
    }
    _append_jsonl(config.USAGE_FAILED_PATH, row)
    logger.error(
        "usage FAILED HTTP %s metric_type=%s (logged to %s)",
        res["status"], metric_type, config.USAGE_FAILED_PATH,
    )
    return {
        **base,
        "outcome": "failed",
        "http_status": res["status"],
        "detail": res["body"],
        "failed_log": str(config.USAGE_FAILED_PATH),
    }


def report_job_usage(usage: dict[str, Any] | None, job_id: str | None = None) -> list[dict[str, Any]]:
    """After a successful job: requests=1 + input/output tokens when > 0."""
    results = [report_usage_metric("requests", 1, "count", None, job_id)]
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value > 0:
                results.append(report_usage_metric(key, value, "tokens", None, job_id))
    return results


def report_usage(usage: dict[str, Any]) -> list[dict[str, Any]]:
    """Back-compat alias."""
    return report_job_usage(usage if isinstance(usage, dict) else {})


def pending_usage() -> list[dict[str, Any]]:
    return _read_jsonl(config.USAGE_QUEUE_PATH)


def sync_pending_usage(token_override: str | None = None) -> dict[str, Any]:
    """Retry queued rows. 2xx -> removed; unreachable/HTTP error -> kept with last_error."""
    token_override = token_override or os.getenv("AGENTHUB_SESSION_TOKEN") or None
    with _queue_lock:
        rows = _read_jsonl(config.USAGE_QUEUE_PATH)
    if not rows:
        return {"synced": 0, "remaining": 0, "results": []}

    with _state_lock:
        bound_sid = _bound.get("session_id")
        bound_token = _bound.get("session_token")

    remaining: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    synced = 0
    for row in rows:
        sid = row.get("session_id")
        token = bound_token if (bound_sid and sid == bound_sid) else token_override
        if not sid or not token:
            row["last_error"] = "no token for session (bind it or set AGENTHUB_SESSION_TOKEN)"
            remaining.append(row)
            results.append({"session_id": sid, "metric_type": (row.get("payload") or {}).get("metric_type"), "outcome": "kept", "reason": row["last_error"]})
            continue
        res = _http_json("POST", _api_url(config.USAGE_PATH_TEMPLATE, str(sid)), token=str(token), payload=row.get("payload") or {})
        row["attempts"] = int(row.get("attempts") or 0) + 1
        row["last_attempt_at"] = _now_iso()
        metric = (row.get("payload") or {}).get("metric_type")
        if res["kind"] == "ok":
            synced += 1
            results.append({"session_id": sid, "metric_type": metric, "outcome": "sent", "http_status": res["status"], "cloud_row": res["body"]})
            continue
        row["last_error"] = {"kind": res["kind"], "http_status": res["status"], "detail": res["body"] or res["error"]}
        remaining.append(row)
        results.append({"session_id": sid, "metric_type": metric, "outcome": "kept", "last_error": row["last_error"]})

    with _queue_lock:
        # Rows appended while we were syncing are preserved.
        current = _read_jsonl(config.USAGE_QUEUE_PATH)
        extra = current[len(rows):]
        _write_jsonl(config.USAGE_QUEUE_PATH, remaining + extra)
    return {"synced": synced, "remaining": len(remaining) + len(extra), "results": results}

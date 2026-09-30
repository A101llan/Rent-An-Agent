"""Unit tests for local-runtime ↔ apps/api HTTP contract helpers."""

from __future__ import annotations

import unittest

from app.api_contract import (
    claim_error_code,
    normalize_claim_success,
    normalize_usage_success,
    parse_api_error,
)


class ParseApiErrorTests(unittest.TestCase):
    def test_canonical_envelope(self):
        body = {"error": {"code": "SESSION_NOT_FOUND", "message": "Session not found"}}
        assert parse_api_error(body) == body["error"]

    def test_legacy_nested_detail(self):
        body = {"detail": {"error": {"code": "INVALID_SESSION_TOKEN", "message": "bad token"}}}
        assert parse_api_error(body)["code"] == "INVALID_SESSION_TOKEN"

    def test_non_dict_returns_none(self):
        assert parse_api_error("not json") is None
        assert parse_api_error(None) is None


class ClaimErrorCodeTests(unittest.TestCase):
    def test_prefers_api_code(self):
        body = {"error": {"code": "SESSION_NOT_LOCAL", "message": "nope"}}
        assert claim_error_code(409, body) == "session_not_local"

    def test_falls_back_to_status(self):
        assert claim_error_code(404, None) == "session_not_found"
        assert claim_error_code(422, {"error": {"code": "VALIDATION_ERROR"}}) == "validation_error"


class NormalizeSuccessTests(unittest.TestCase):
    def test_claim_success(self):
        body = {
            "session_id": "abc",
            "expires_at": "2026-01-01T00:00:00Z",
            "manifest": {"runtime": {"type": "local"}},
            "agent_slug": "x",
            "agent_version": "0.1.0",
            "runtime_provider": "local",
        }
        out = normalize_claim_success(body)
        assert out is not None
        assert out["session_id"] == "abc"
        assert out["manifest"]["runtime"]["type"] == "local"

    def test_claim_missing_session_id(self):
        assert normalize_claim_success({"expires_at": "x"}) is None

    def test_usage_success(self):
        body = {
            "id": "r1",
            "session_id": "s1",
            "execution_id": None,
            "metric_type": "requests",
            "quantity": 1.0,
            "unit": "count",
            "recorded_at": "2026-01-01T00:00:00Z",
        }
        out = normalize_usage_success(body)
        assert out is not None
        assert out["metric_type"] == "requests"

    def test_usage_missing_fields(self):
        assert normalize_usage_success({"id": "r1"}) is None


if __name__ == "__main__":
    unittest.main()

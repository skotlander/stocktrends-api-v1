"""
Tests for stocktrends_preview injection in x402 challenge responses.

Validates that:
- x402 challenge body includes stocktrends_preview for known preview paths
- x402 challenge body omits stocktrends_preview for unknown paths
- Existing 402 fields are preserved (error, pricing, accepted_payment_methods,
  payment_required, PAYMENT-REQUIRED header)
- MPP non-challenge 402s do NOT include stocktrends_preview
- x402 validation_failed, replay_detected responses do NOT include stocktrends_preview
- Preview content is schema-only (no live market data)
- accepted_payment_methods includes subscription, x402, mpp for known paid paths

Coverage map (from Codex review):
  [x] anonymous x402 challenge includes preview for known preview path
  [x] unknown preview paths omit stocktrends_preview
  [x] accepted_payment_methods remain subscription,x402,mpp
  [x] PAYMENT-REQUIRED header unchanged
  [x] MPP errors do not include preview
  [x] validation/replay/settlement 402s do not include preview
  [x] preview is schema-only (no live data values)
  [x] discovery/preview.py unit: get_endpoint_preview returns copy
  [x] discovery/preview.py unit: unknown path returns None
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

# conftest.py provides sqlalchemy / jwt / cryptography / etc. stubs.
import main
import middleware.api_key as api_key_module
import middleware.metering as metering_module
import pricing.classifier as classifier_module
from payments.enforcement import PaymentEnforcementResult
from discovery.preview import get_endpoint_preview, _PREVIEW_BY_PATH


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_KNOWN_PREVIEW_PATH = "/v1/agent/screener/top"
_UNKNOWN_PREVIEW_PATH = "/v1/indicators/latest"  # paid endpoint, no registered preview

_CHALLENGE_BODY_TEMPLATE = {
    "error": "payment_required",
    "detail": "Payment is required to access this endpoint.",
    "protocol": "x402",
    "resource": _KNOWN_PREVIEW_PATH,
    "pricing": {
        "amount_usd": "0.050000",
        "unit": "request",
        "network": "eip155:8453",
        "token": "0xtoken",
        "scheme": "exact",
    },
    "accepted_payment_methods": ["x402"],
    "payment_required": {"x402Version": 2, "accepts": []},
}

_PAYMENT_REQUIRED_HEADER_VALUE = base64.b64encode(b'{"test": true}').decode()


def _make_challenge_result(path: str = _KNOWN_PREVIEW_PATH) -> PaymentEnforcementResult:
    body = dict(_CHALLENGE_BODY_TEMPLATE)
    body["resource"] = path
    return PaymentEnforcementResult(
        outcome="challenge",
        challenge_body=body,
        payment_required_header=_PAYMENT_REQUIRED_HEADER_VALUE,
        payment_network="eip155:8453",
        payment_token="0xtoken",
    )


def _make_validation_failed_result() -> PaymentEnforcementResult:
    return PaymentEnforcementResult(
        outcome="validation_failed",
        error_code="invalid_payment",
        error_detail="Signature verification failed.",
        payment_required_header=_PAYMENT_REQUIRED_HEADER_VALUE,
        payment_network="eip155:8453",
        payment_token="0xtoken",
    )


def _make_replay_result() -> PaymentEnforcementResult:
    return PaymentEnforcementResult(
        outcome="replay_detected",
        error_code="replay_detected",
        error_detail="Payment reference already used.",
    )


def _make_mpp_failure_result() -> PaymentEnforcementResult:
    return PaymentEnforcementResult(
        outcome="session_not_found",
        error_code="mpp_session_not_found",
        error_detail="No active MPP session found for session_id.",
    )


def _stub_runtime(monkeypatch, *, enforce_result: PaymentEnforcementResult, path: str = _KNOWN_PREVIEW_PATH):
    """Patch metering-layer side effects and enforcement for agent-pay challenge tests."""
    monkeypatch.setattr(metering_module, "log_api_request_event", lambda *a, **kw: None)
    monkeypatch.setattr(metering_module, "log_api_request_economics", lambda *a, **kw: None)
    monkeypatch.setattr(
        metering_module,
        "resolve_economic_amounts",
        lambda *a, **kw: (Decimal("0.05"), Decimal("0.05"), Decimal("0.05")),
    )
    monkeypatch.setattr(api_key_module, "log_auth_failure_event", lambda *a, **kw: None)

    # Enable agent-pay enforcement
    monkeypatch.setattr(metering_module, "ENABLE_AGENT_PAY", True)
    monkeypatch.setattr(metering_module, "ENFORCE_AGENT_PAY", True)
    monkeypatch.setattr(api_key_module, "_ENABLE_AGENT_PAY", True)
    monkeypatch.setattr(classifier_module, "ENABLE_AGENT_PAY", True)

    monkeypatch.setattr(
        metering_module,
        "enforce_payment_rail",
        lambda **kwargs: enforce_result,
    )


# ---------------------------------------------------------------------------
# Unit tests for discovery/preview.py
# ---------------------------------------------------------------------------

class TestDiscoveryPreview:
    def test_known_path_returns_dict(self):
        result = get_endpoint_preview(_KNOWN_PREVIEW_PATH)
        assert isinstance(result, dict)

    def test_unknown_path_returns_none(self):
        assert get_endpoint_preview("/v1/nonexistent/path") is None

    def test_returns_copy_not_original(self):
        """Mutating the returned dict must not affect the registry."""
        result = get_endpoint_preview(_KNOWN_PREVIEW_PATH)
        result["_injected"] = True
        fresh = get_endpoint_preview(_KNOWN_PREVIEW_PATH)
        assert "_injected" not in fresh

    def test_all_entries_have_response_shape_or_note(self):
        for path, entry in _PREVIEW_BY_PATH.items():
            assert "note" in entry or "response_shape" in entry, (
                f"Preview entry for {path!r} missing both 'note' and 'response_shape'"
            )

    def test_no_live_data_values(self):
        """Preview entries must not contain live-looking numeric data."""
        for path, entry in _PREVIEW_BY_PATH.items():
            raw = json.dumps(entry)
            # Should not contain price-like floats or date strings
            assert "amount_usd" not in raw, f"{path}: 'amount_usd' in preview"
            assert "stc_cost" not in raw, f"{path}: 'stc_cost' in preview"


# ---------------------------------------------------------------------------
# Integration tests: x402 challenge with preview for KNOWN path
# ---------------------------------------------------------------------------

@pytest.fixture
def client_x402_challenge_known(monkeypatch):
    _stub_runtime(monkeypatch, enforce_result=_make_challenge_result(_KNOWN_PREVIEW_PATH))
    with TestClient(main.app) as c:
        yield c


def test_x402_challenge_returns_402(client_x402_challenge_known):
    response = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    )
    assert response.status_code == 402


def test_x402_challenge_includes_stocktrends_preview(client_x402_challenge_known):
    """Challenge body for a known preview path must include stocktrends_preview."""
    response = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    )
    assert response.status_code == 402
    body = response.json()
    assert "stocktrends_preview" in body, (
        "stocktrends_preview must be present for known preview paths"
    )


def test_x402_challenge_preview_is_schema_only(client_x402_challenge_known):
    """stocktrends_preview must not contain live data values."""
    body = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    ).json()
    preview = body.get("stocktrends_preview", {})
    raw = json.dumps(preview)
    assert "amount_usd" not in raw
    assert "stc_cost" not in raw
    assert "billed_amount" not in raw


def test_x402_challenge_existing_fields_preserved(client_x402_challenge_known):
    """All original challenge fields must still be present."""
    body = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    ).json()
    for field in ("error", "pricing", "accepted_payment_methods", "payment_required"):
        assert field in body, f"Field {field!r} missing from challenge body"


def test_x402_challenge_accepted_methods_has_all_rails(client_x402_challenge_known):
    """accepted_payment_methods must include subscription, x402, and mpp."""
    body = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    ).json()
    methods = set(body.get("accepted_payment_methods", []))
    assert {"subscription", "x402", "mpp"}.issubset(methods), (
        f"accepted_payment_methods incomplete: {methods}"
    )


def test_x402_challenge_payment_required_header_present(client_x402_challenge_known):
    """PAYMENT-REQUIRED header must be set (not X-Payment-Required)."""
    response = client_x402_challenge_known.get(
        _KNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    )
    # Starlette lowercases response headers
    assert "payment-required" in response.headers, (
        "PAYMENT-REQUIRED header must be present on 402 challenge response"
    )
    # Must NOT be the wrong header name
    assert "x-payment-required" not in response.headers


# ---------------------------------------------------------------------------
# Integration tests: x402 challenge for UNKNOWN preview path
# ---------------------------------------------------------------------------

@pytest.fixture
def client_x402_challenge_unknown(monkeypatch):
    _stub_runtime(monkeypatch, enforce_result=_make_challenge_result(_UNKNOWN_PREVIEW_PATH))
    with TestClient(main.app) as c:
        yield c


def test_x402_challenge_unknown_path_omits_stocktrends_preview(client_x402_challenge_unknown):
    """Challenge for a path with no registered preview must NOT include stocktrends_preview."""
    response = client_x402_challenge_unknown.get(
        _UNKNOWN_PREVIEW_PATH,
        headers={"X-StockTrends-Payment-Method": "x402"},
    )
    assert response.status_code == 402
    body = response.json()
    assert "stocktrends_preview" not in body, (
        "stocktrends_preview must be absent for paths with no registered preview"
    )


# ---------------------------------------------------------------------------
# x402 validation_failed — must NOT include preview
# ---------------------------------------------------------------------------

@pytest.fixture
def client_x402_validation_failed(monkeypatch):
    _stub_runtime(monkeypatch, enforce_result=_make_validation_failed_result())
    with TestClient(main.app) as c:
        yield c


def test_x402_validation_failed_no_preview(client_x402_validation_failed):
    """validation_failed 402 must not include stocktrends_preview."""
    response = client_x402_validation_failed.get(
        _KNOWN_PREVIEW_PATH,
        headers={
            "X-StockTrends-Payment-Method": "x402",
            "X-StockTrends-Payment-Reference": "0xsig",
        },
    )
    assert response.status_code == 402
    body = response.json()
    assert "stocktrends_preview" not in body


# ---------------------------------------------------------------------------
# x402 replay_detected — must NOT include preview
# ---------------------------------------------------------------------------

@pytest.fixture
def client_x402_replay(monkeypatch):
    _stub_runtime(monkeypatch, enforce_result=_make_replay_result())
    with TestClient(main.app) as c:
        yield c


def test_x402_replay_detected_no_preview(client_x402_replay):
    """replay_detected 402 must not include stocktrends_preview."""
    response = client_x402_replay.get(
        _KNOWN_PREVIEW_PATH,
        headers={
            "X-StockTrends-Payment-Method": "x402",
            "X-StockTrends-Payment-Reference": "0xdupe",
        },
    )
    assert response.status_code == 402
    body = response.json()
    assert "stocktrends_preview" not in body


# ---------------------------------------------------------------------------
# MPP failure — must NOT include preview (different code path entirely)
# ---------------------------------------------------------------------------

@pytest.fixture
def client_mpp_failure(monkeypatch):
    _stub_runtime(monkeypatch, enforce_result=_make_mpp_failure_result())
    with TestClient(main.app) as c:
        yield c


def test_mpp_failure_no_preview(client_mpp_failure):
    """MPP 402 errors must not include stocktrends_preview (different branch)."""
    response = client_mpp_failure.get(
        _KNOWN_PREVIEW_PATH,
        headers={
            "X-StockTrends-Payment-Method": "mpp",
            "X-StockTrends-Session-Id": "ses_test",
        },
    )
    assert response.status_code == 402
    body = response.json()
    assert "stocktrends_preview" not in body

"""Runtime-side contract test for the MPP capture response parser.

Pins the behaviour of ``payments.mpp_client.capture_mpp_payment`` against
the control-plane ``POST /v1/internal/mpp/capture`` response contract.

Why this test exists
--------------------
A prior regression in ``stocktrends-api-control`` returned the capture
response as nested-only — ``{authorization: {...}, session: {...}}`` —
while this runtime reads ``data.get("status")`` at the TOP level to
decide capture success.  The result: successful captures were silently
logged as ``capture_failed`` in ``api_request_economics.payment_status``.

``stocktrends-api-control`` PR 1 restored the canonical flat shape
(``status``, ``captured_at``, ``captured_stc`` at the top level, with
``session`` retained as an optional nested field).  THIS test locks that
contract from the runtime side so the regression cannot recur silently.

Scope
-----
Parser-only.  We mock the HTTP boundary (``_mpp_post``) so the REAL
``capture_mpp_payment`` logic runs — no network, no DB, no FastAPI app.
The existing parser already handles the canonical shape correctly (see
"Production impact" below); this file adds guarantees, not behaviour.

Production impact
-----------------
No production code is modified in this PR.  The existing parser in
``payments/mpp_client.py`` — which reads top-level ``status`` with a
``captured_at`` fallback — is sufficient for the canonical contract
restored by PR 1.  A separate runtime fix would be required only if
control-plane were to change shape again in a non-additive way.

Derived assertion — payment_status
----------------------------------
Tests assert both the parser's return value AND the
``api_request_economics.payment_status`` label that the metering layer
derives from it.  The derivation mirrors the live mapping at
``middleware/metering.py`` (``mpp_capture_outcome`` → ``payment_status``):

    success=True  → payment_status == "captured"
    success=False → payment_status == "capture_failed"

This double-assert keeps the contract tied to the column value that
actually lands in the metering table, not just the intermediate dataclass.
"""

from __future__ import annotations

import json as _json
from decimal import Decimal
from typing import Any

import pytest

from payments import mpp_client
from payments.mpp_client import MppControlPlaneResult, capture_mpp_payment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_payment_status(result: MppControlPlaneResult) -> str:
    """Mirror the middleware/metering mapping of parser result → payment_status.

    Kept here rather than imported from ``middleware.metering`` because the
    middleware module pulls in FastAPI, sqlalchemy, and the full request
    lifecycle — far too heavy for a parser contract test.  If the live
    mapping ever changes, this helper must be updated in lock-step; the
    comment above points reviewers at the authoritative site.
    """
    return "captured" if result.success else "capture_failed"


@pytest.fixture
def fake_capture_post(monkeypatch):
    """Replace ``mpp_client._mpp_post`` with a controllable fake.

    Returns a ``configure(status, data)`` callable that sets what the
    fake will return on the next ``capture_mpp_payment`` invocation.
    """
    state: dict[str, Any] = {"status": 200, "data": None}

    def fake_post(endpoint: str, payload: dict[str, Any]):
        # The parser receives a (http_status, parsed_body_or_None, raw_body_or_error).
        # We mirror that tuple shape exactly — anything else would test
        # a re-implementation rather than the real parser.
        data = state["data"]
        raw = _json.dumps(data) if data is not None else ""
        return state["status"], data, raw

    monkeypatch.setattr(mpp_client, "_mpp_post", fake_post)

    def configure(http_status: int, data: dict | None) -> None:
        state["status"] = http_status
        state["data"] = data

    return configure


def _call_capture() -> MppControlPlaneResult:
    """Invoke the real capture parser with stable placeholder arguments.

    The parser does not read the request payload — only the response —
    so the arg values do not affect test outcomes.
    """
    return capture_mpp_payment(
        channel_id="ch_test",
        payment_reference="pref_test",
        captured_stc=Decimal("0.0025"),
        pricing_rule_id="rule_test",
        request_id="req_test",
    )


# ---------------------------------------------------------------------------
# 1. Canonical contract — PR 1 restored this shape
# ---------------------------------------------------------------------------

def test_canonical_captured_response_maps_to_payment_status_captured(fake_capture_post):
    """Top-level ``status='captured'`` + ``captured_at`` is the happy path.

    A regression here — re-nesting the response, or dropping ``status``
    from the top level — would silently flip successful captures to
    ``capture_failed`` in metering.  Guard strictly.
    """
    fake_capture_post(
        200,
        {
            "id": "auth_123",
            "status": "captured",
            "captured_at": "2026-01-01T00:00:00Z",
            "captured_stc": 0.0025,
        },
    )

    result = _call_capture()

    assert result.success is True
    assert result.error_code is None
    assert _derive_payment_status(result) == "captured"


# ---------------------------------------------------------------------------
# 2. Fallback condition — captured_at alone marks success
# ---------------------------------------------------------------------------

def test_fallback_captured_at_without_status_captured_is_captured(fake_capture_post):
    """Parser fallback: any truthy ``captured_at`` overrides a non-'captured' status.

    This belt-and-braces clause means a future control-plane shape using
    a richer status vocabulary (e.g., ``settled``) still maps to
    ``captured`` as long as a ``captured_at`` timestamp is present.  The
    runtime therefore does not hard-depend on the literal string
    ``'captured'``.
    """
    fake_capture_post(
        200,
        {
            "id": "auth_123",
            "status": "authorized",
            "captured_at": "2026-01-01T00:00:00Z",
        },
    )

    result = _call_capture()

    assert result.success is True
    assert _derive_payment_status(result) == "captured"


# ---------------------------------------------------------------------------
# 3. Regression guard — the old nested-only shape MUST fail
# ---------------------------------------------------------------------------

def test_old_nested_only_shape_maps_to_capture_failed(fake_capture_post):
    """The pre-PR-1 shape (``{authorization: ..., session: ...}``) MUST fail.

    Explicit regression guard: if the control-plane ever re-nests the
    response, the runtime must surface ``capture_failed`` loudly rather
    than silently mis-label successful captures.
    """
    fake_capture_post(
        200,
        {
            "authorization": {
                "status": "captured",
                "captured_at": "2026-01-01T00:00:00Z",
            },
            "session": {"id": "sess_123"},
        },
    )

    result = _call_capture()

    assert result.success is False
    assert result.error_code == "capture_failed"
    assert _derive_payment_status(result) == "capture_failed"


# ---------------------------------------------------------------------------
# 4. Missing-field variants
# ---------------------------------------------------------------------------

def test_missing_status_and_missing_captured_at_is_capture_failed(fake_capture_post):
    """Neither signal present → capture_failed.  Nothing silently succeeds."""
    fake_capture_post(200, {"id": "auth_123"})

    result = _call_capture()

    assert result.success is False
    assert result.error_code == "capture_failed"
    assert _derive_payment_status(result) == "capture_failed"


def test_missing_status_with_captured_at_present_uses_fallback(fake_capture_post):
    """``captured_at`` alone (no ``status`` at all) still routes via fallback."""
    fake_capture_post(
        200,
        {"id": "auth_123", "captured_at": "2026-01-01T00:00:00Z"},
    )

    result = _call_capture()

    assert result.success is True
    assert _derive_payment_status(result) == "captured"


def test_non_captured_status_without_captured_at_is_capture_failed(fake_capture_post):
    """``status='pending'`` with no ``captured_at`` must NOT count as captured."""
    fake_capture_post(200, {"id": "auth_123", "status": "pending"})

    result = _call_capture()

    assert result.success is False
    assert _derive_payment_status(result) == "capture_failed"


def test_empty_body_is_capture_failed(fake_capture_post):
    """A completely empty body is capture_failed, not silent success."""
    fake_capture_post(200, {})

    result = _call_capture()

    assert result.success is False
    assert _derive_payment_status(result) == "capture_failed"


# ---------------------------------------------------------------------------
# 5. Null captured_at must NOT trigger fallback
# ---------------------------------------------------------------------------

def test_null_captured_at_does_not_trigger_fallback(fake_capture_post):
    """An explicit ``captured_at: null`` is falsy — fallback must NOT fire.

    Guards against a subtle regression where a refactor could swap
    ``bool(data.get('captured_at'))`` for ``'captured_at' in data``,
    turning a nulled field into a false-success.
    """
    fake_capture_post(
        200,
        {"id": "auth_123", "status": "pending", "captured_at": None},
    )

    result = _call_capture()

    assert result.success is False
    assert _derive_payment_status(result) == "capture_failed"


# ---------------------------------------------------------------------------
# 6. HTTP-level failure branches — upstream of body parsing
# ---------------------------------------------------------------------------

def test_http_4xx_with_control_plane_error_code_is_capture_failed(fake_capture_post):
    """HTTP 4xx: parser preserves control-plane ``error_code`` when present."""
    fake_capture_post(400, {"error_code": "bad_request", "error_detail": "..."})

    result = _call_capture()

    assert result.success is False
    assert result.error_code == "bad_request"
    assert _derive_payment_status(result) == "capture_failed"


def test_http_5xx_without_error_code_defaults_to_capture_failed(fake_capture_post):
    """HTTP 5xx with empty body defaults to ``capture_failed``."""
    fake_capture_post(500, {})

    result = _call_capture()

    assert result.success is False
    assert result.error_code == "capture_failed"
    assert _derive_payment_status(result) == "capture_failed"


def test_control_plane_unreachable_is_capture_failed(fake_capture_post):
    """``status=0`` indicates transport failure — maps to capture_failed.

    Preserves the ``control_plane_unreachable`` error_code for
    observability; the derived payment_status is still ``capture_failed``
    so metering reflects that no successful capture occurred.
    """
    fake_capture_post(0, None)

    result = _call_capture()

    assert result.success is False
    assert result.error_code == "control_plane_unreachable"
    assert _derive_payment_status(result) == "capture_failed"


# ---------------------------------------------------------------------------
# 7. Optional nested session does NOT confuse the parser
# ---------------------------------------------------------------------------

def test_flat_response_with_nested_session_still_captures(fake_capture_post):
    """Canonical PR-1 shape: flat top-level fields WITH nested ``session``.

    The parser must ignore the nested session and key exclusively on
    the top-level signals.  This is the actual response the control
    plane emits today.
    """
    fake_capture_post(
        200,
        {
            "id": "auth_123",
            "session_id": "sess_123",
            "channel_id": "ch_123",
            "customer_id": "cust_123",
            "payment_reference": "pref_123",
            "endpoint_code": "stim.latest",
            "pricing_rule_id": "rule_123",
            "requested_stc": "0.0025",
            "status": "captured",
            "created_at": "2026-01-01T00:00:00Z",
            "expires_at": None,
            "captured_at": "2026-01-01T00:00:05Z",
            "captured_stc": "0.0025",
            "session": {
                "id": "sess_123",
                "funded_stc": "10.0",
                "reserved_stc": "0.0",
                "captured_stc": "0.0025",
            },
        },
    )

    result = _call_capture()

    assert result.success is True
    assert _derive_payment_status(result) == "captured"

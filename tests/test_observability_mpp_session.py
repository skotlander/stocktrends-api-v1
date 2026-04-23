"""
Tests for GET /v1/observability/mpp/sessions/{payment_channel_id}

DB / ORM dependencies are mocked at sys.modules level so these tests run
without a database connection or sqlalchemy installed — same pattern as
test_ai_tools.py.

Covers:
- 200 for a known payment_channel_id
- 404 for an unknown payment_channel_id
- correct aggregation of totals and status breakdown
- regression: channels with only x402 records return 404 (payment_rail='mpp' filter)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock DB / ORM dependencies before any project imports that need them.
# metering/logger.py uses sqlalchemy.exc.DBAPIError, so sqlalchemy.exc must
# also be in sys.modules.
# ---------------------------------------------------------------------------
_DB_MOCK = MagicMock()
_SQLALCHEMY_MOCK = MagicMock()
_SQLALCHEMY_EXC_MOCK = MagicMock()
_SQLALCHEMY_EXC_MOCK.DBAPIError = Exception  # real exception base so isinstance checks work

_STUB_MODULES = [
    ("sqlalchemy", _SQLALCHEMY_MOCK),
    ("sqlalchemy.orm", _SQLALCHEMY_MOCK),
    ("sqlalchemy.exc", _SQLALCHEMY_EXC_MOCK),
    ("db", _DB_MOCK),
    ("jwt", MagicMock()),
    ("cryptography", MagicMock()),
    ("cryptography.hazmat", MagicMock()),
    ("cryptography.hazmat.primitives", MagicMock()),
    ("cryptography.hazmat.primitives.asymmetric", MagicMock()),
    ("cryptography.hazmat.primitives.asymmetric.ed25519", MagicMock()),
    ("cryptography.hazmat.primitives.serialization", MagicMock()),
    ("mysql", MagicMock()),
    ("mysql.connector", MagicMock()),
    ("stripe", MagicMock()),
]
for _mod_name, _mod_mock in _STUB_MODULES:
    sys.modules.setdefault(_mod_name, _mod_mock)

# Now safe to import project modules
import main
import middleware.api_key as api_key_module
import middleware.metering as metering_module
import routers.observability as observability_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_runtime(monkeypatch):
    monkeypatch.setattr(metering_module, "log_api_request_event", lambda *a, **kw: None)
    monkeypatch.setattr(metering_module, "log_api_request_economics", lambda *a, **kw: None)
    monkeypatch.setattr(
        metering_module,
        "resolve_economic_amounts",
        lambda *a, **kw: (Decimal("0"), Decimal("0"), Decimal("0")),
    )
    monkeypatch.setattr(api_key_module, "log_auth_failure_event", lambda *a, **kw: None)


def _stub_auth(monkeypatch, customer_id: str = "cust-123"):
    def fake_authenticate(self, path: str, raw_key: str):
        return True, {
            "api_key_id": "test-key-id",
            "customer_id": customer_id,
            "subscription_id": "sub-1",
            "plan_code": "pro",
            "actor_type": "external_customer",
            "monthly_quota": 1000,
        }

    monkeypatch.setattr(api_key_module.ApiKeyMiddleware, "_authenticate_api_key", fake_authenticate)


def _make_result(rows: list[dict]):
    """Build a mock execute() result supporting both .first() and .all()."""
    result = MagicMock()
    mappings = MagicMock()
    mappings.first.return_value = rows[0] if rows else None
    mappings.all.return_value = rows
    result.mappings.return_value = mappings
    return result


def _make_engine(monkeypatch, execute_results: list):
    """
    Patch get_metering_engine so conn.execute() returns items from execute_results
    in order, one per call.
    """
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.side_effect = execute_results
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    engine.begin.return_value = cm
    monkeypatch.setattr(observability_module, "get_metering_engine", lambda: engine)
    return conn


# ---------------------------------------------------------------------------
# Shared fixtures / data
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 4, 22, 15, 30, 0, tzinfo=timezone.utc)

_SUMMARY = {
    "request_count": 3,
    "session_id": "sess-abc",
    "first_seen_at": _T0,
    "last_seen_at": _T1,
    "total_stc": Decimal("3.00"),
    "total_billed_usd": Decimal("3.00"),
}

_STATUS_ROWS = [
    {"payment_status": "captured", "request_count": 2},
    {"payment_status": "authorized", "request_count": 1},
]

_RECENT_ROWS = [
    {
        "request_id": "req-3",
        "payment_status": "captured",
        "payment_reference": "ref-c",
        "stc_cost": Decimal("1.00"),
        "billed_amount_usd": Decimal("1.00"),
        "pricing_rule_id": "rule-a",
        "created_at": _T1,
    },
    {
        "request_id": "req-2",
        "payment_status": "captured",
        "payment_reference": "ref-b",
        "stc_cost": Decimal("1.00"),
        "billed_amount_usd": Decimal("1.00"),
        "pricing_rule_id": "rule-a",
        "created_at": datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone.utc),
    },
    {
        "request_id": "req-1",
        "payment_status": "authorized",
        "payment_reference": "ref-a",
        "stc_cost": Decimal("1.00"),
        "billed_amount_usd": Decimal("1.00"),
        "pricing_rule_id": "rule-a",
        "created_at": _T0,
    },
]


@pytest.fixture
def client(monkeypatch):
    _stub_runtime(monkeypatch)
    with TestClient(main.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Test: 200 for known payment_channel_id
# ---------------------------------------------------------------------------

class TestGetMppSessionFound:
    def test_200_returns_expected_shape(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY]),
            _make_result(_STATUS_ROWS),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["payment_channel_id"] == "chan-xyz"
        assert body["session_id"] == "sess-abc"
        assert body["request_count"] == 3
        assert body["first_seen_at"] == _T0.isoformat()
        assert body["last_seen_at"] == _T1.isoformat()

    def test_200_includes_status_breakdown(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY]),
            _make_result(_STATUS_ROWS),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        breakdown = body["payment_status_breakdown"]
        assert len(breakdown) == 2
        assert breakdown[0] == {"payment_status": "captured", "request_count": 2}
        assert breakdown[1] == {"payment_status": "authorized", "request_count": 1}

    def test_200_includes_recent_requests(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY]),
            _make_result(_STATUS_ROWS),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        recent = body["recent_requests"]
        assert len(recent) == 3
        assert recent[0]["request_id"] == "req-3"
        assert recent[0]["payment_status"] == "captured"
        assert recent[0]["stc_cost"] == pytest.approx(1.0)

    def test_200_session_id_none_when_absent(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        summary_no_session = {**_SUMMARY, "session_id": None}
        _make_engine(monkeypatch, [
            _make_result([summary_no_session]),
            _make_result(_STATUS_ROWS),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        assert resp.json()["session_id"] is None


# ---------------------------------------------------------------------------
# Test: 404 for unknown payment_channel_id
# ---------------------------------------------------------------------------

class TestGetMppSessionNotFound:
    def test_404_when_count_zero(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        empty_summary = {
            "request_count": 0,
            "session_id": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "total_stc": None,
            "total_billed_usd": None,
        }
        _make_engine(monkeypatch, [_make_result([empty_summary])])

        resp = client.get(
            "/v1/observability/mpp/sessions/unknown-chan",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "MPP session not found"

    def test_404_when_summary_returns_none(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [_make_result([])])

        resp = client.get(
            "/v1/observability/mpp/sessions/unknown-chan",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 404

    def test_401_without_api_key(self, client):
        resp = client.get("/v1/observability/mpp/sessions/chan-xyz")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: correct aggregation behavior
# ---------------------------------------------------------------------------

class TestAggregation:
    def test_totals_are_surfaced_correctly(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        summary = {
            "request_count": 5,
            "session_id": "sess-agg",
            "first_seen_at": _T0,
            "last_seen_at": _T1,
            "total_stc": Decimal("12.50"),
            "total_billed_usd": Decimal("12.50"),
        }
        _make_engine(monkeypatch, [
            _make_result([summary]),
            _make_result([{"payment_status": "captured", "request_count": 5}]),
            _make_result([]),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-agg",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["request_count"] == 5
        assert body["total_stc"] == pytest.approx(12.50)
        assert body["total_billed_usd"] == pytest.approx(12.50)

    def test_null_totals_default_to_zero(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        summary = {
            "request_count": 2,
            "session_id": None,
            "first_seen_at": _T0,
            "last_seen_at": _T1,
            "total_stc": None,
            "total_billed_usd": None,
        }
        _make_engine(monkeypatch, [
            _make_result([summary]),
            _make_result([]),
            _make_result([]),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-null",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_stc"] == 0.0
        assert body["total_billed_usd"] == 0.0


# ---------------------------------------------------------------------------
# Regression: MPP flow is distinct from x402 flow
#
# A payment_channel_id that exists only under payment_rail='x402' must return
# 404 from this endpoint because the query filters AND payment_rail = 'mpp'.
# We simulate this by returning request_count=0 from the summary query —
# exactly what the DB produces when the filter matches no rows.
# ---------------------------------------------------------------------------

class TestMppDistinctFromX402:
    def test_channel_with_only_x402_records_returns_404(self, client, monkeypatch):
        """
        Simulates a channel that exists in api_request_economics under
        payment_rail='x402' but has no 'mpp' records.
        The endpoint's AND payment_rail = 'mpp' filter yields count=0 → 404.
        """
        _stub_auth(monkeypatch)
        x402_channel_summary = {
            "request_count": 0,
            "session_id": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "total_stc": None,
            "total_billed_usd": None,
        }
        _make_engine(monkeypatch, [_make_result([x402_channel_summary])])

        resp = client.get(
            "/v1/observability/mpp/sessions/x402-chan-001",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "MPP session not found"

    def test_mpp_response_contains_no_payment_rail_bleed(self, client, monkeypatch):
        """
        A successful response must not expose a payment_rail field at the top
        level — this endpoint is MPP-scoped by construction and the caller
        should not need to check rail identity in the response body.
        """
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY]),
            _make_result([{"payment_status": "captured", "request_count": 3}]),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/mpp-chan-001",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "payment_rail" not in body
        for entry in body["payment_status_breakdown"]:
            assert "payment_status" in entry
            assert "request_count" in entry

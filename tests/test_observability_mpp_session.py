"""
Tests for GET /v1/observability/mpp/sessions/{payment_channel_id}

DB / ORM dependencies are mocked at sys.modules level (see tests/conftest.py)
so these tests run without a database connection or sqlalchemy installed.

Coverage:
1. 200 for known payment_channel_id
2. 404 for unknown payment_channel_id
3. Correct aggregation: total_stc_requested vs total_stc_captured
4. Regression: x402 channels are invisible (payment_rail='mpp' filter)
5. Production MPP lane: customer_id is NULL in MPP rows — authenticated
   operator (customer_id set) can still look up the session without
   customer_id appearing in the query scope
6. Non-billable classification: /v1/observability/ paths never consume quota
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call

import pytest
from fastapi.testclient import TestClient

# conftest.py handles sqlalchemy / jwt / cryptography / etc. stubs.
import main
import middleware.api_key as api_key_module
import middleware.metering as metering_module
import routers.observability as observability_module
from pricing.classifier import NON_METERED_PREFIXES, classify_request


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


def _stub_auth(monkeypatch, customer_id: str = "cust-operator-123"):
    """Simulate a subscription API-key holder (operator) calling the endpoint."""
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
# Shared test data
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 4, 22, 15, 30, 0, tzinfo=timezone.utc)

# Typical session: 3 requests, 2 captured, 1 authorized (not captured)
_SUMMARY_MIXED = {
    "request_count": 3,
    "session_id": "sess-abc",
    "first_seen_at": _T0,
    "last_seen_at": _T1,
    # stc_cost for all 3 rows = 3.00
    "total_stc_requested": Decimal("3.00"),
    # only 2 captured rows → 2.00 STC actually deducted
    "total_stc_captured": Decimal("2.00"),
    "total_billed_usd_captured": Decimal("2.00"),
}

_STATUS_ROWS_MIXED = [
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
# 1. 200 for known payment_channel_id
# ---------------------------------------------------------------------------

class TestGetMppSessionFound:
    def test_200_returns_expected_shape(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
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
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        breakdown = resp.json()["payment_status_breakdown"]
        assert len(breakdown) == 2
        assert breakdown[0] == {"payment_status": "captured", "request_count": 2}
        assert breakdown[1] == {"payment_status": "authorized", "request_count": 1}

    def test_200_includes_recent_requests(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        recent = resp.json()["recent_requests"]
        assert len(recent) == 3
        assert recent[0]["request_id"] == "req-3"
        assert recent[0]["payment_status"] == "captured"
        assert recent[0]["stc_cost"] == pytest.approx(1.0)

    def test_200_session_id_none_when_absent(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        summary_no_session = {**_SUMMARY_MIXED, "session_id": None}
        _make_engine(monkeypatch, [
            _make_result([summary_no_session]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        assert resp.json()["session_id"] is None


# ---------------------------------------------------------------------------
# 2. 404 for unknown payment_channel_id
# ---------------------------------------------------------------------------

class TestGetMppSessionNotFound:
    def test_404_when_count_zero(self, client, monkeypatch):
        _stub_auth(monkeypatch)
        empty_summary = {
            "request_count": 0,
            "session_id": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "total_stc_requested": None,
            "total_stc_captured": None,
            "total_billed_usd_captured": None,
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
# 3. Correct aggregation: captured vs requested totals
# ---------------------------------------------------------------------------

class TestAggregationSemantics:
    def test_captured_totals_exclude_authorized_rows(self, client, monkeypatch):
        """
        A session with 3 requests (2 captured, 1 authorized-not-captured)
        must report total_stc_captured = 2.0, not 3.0.
        total_stc_requested = 3.0 (all rows, informational).
        """
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-mixed",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        assert resp.status_code == 200
        assert body["total_stc_requested"] == pytest.approx(3.0)
        assert body["total_stc_captured"] == pytest.approx(2.0)
        assert body["total_billed_usd_captured"] == pytest.approx(2.0)
        # Captured < requested because one authorized row is excluded
        assert body["total_stc_captured"] < body["total_stc_requested"]

    def test_fully_captured_session_totals_match(self, client, monkeypatch):
        """When every request was captured, requested == captured."""
        _stub_auth(monkeypatch)
        summary_all_captured = {
            "request_count": 2,
            "session_id": "sess-full",
            "first_seen_at": _T0,
            "last_seen_at": _T1,
            "total_stc_requested": Decimal("2.00"),
            "total_stc_captured": Decimal("2.00"),
            "total_billed_usd_captured": Decimal("2.00"),
        }
        _make_engine(monkeypatch, [
            _make_result([summary_all_captured]),
            _make_result([{"payment_status": "captured", "request_count": 2}]),
            _make_result([]),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-full",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        assert body["total_stc_requested"] == pytest.approx(2.0)
        assert body["total_stc_captured"] == pytest.approx(2.0)
        assert body["total_billed_usd_captured"] == pytest.approx(2.0)

    def test_all_authorized_session_has_zero_captured(self, client, monkeypatch):
        """A session where all requests were authorized-but-not-captured shows 0 captured."""
        _stub_auth(monkeypatch)
        summary_no_capture = {
            "request_count": 2,
            "session_id": "sess-auth",
            "first_seen_at": _T0,
            "last_seen_at": _T1,
            "total_stc_requested": Decimal("2.00"),
            "total_stc_captured": Decimal("0.00"),
            "total_billed_usd_captured": Decimal("0.00"),
        }
        _make_engine(monkeypatch, [
            _make_result([summary_no_capture]),
            _make_result([{"payment_status": "authorized", "request_count": 2}]),
            _make_result([]),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-auth-only",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        assert body["total_stc_requested"] == pytest.approx(2.0)
        assert body["total_stc_captured"] == pytest.approx(0.0)
        assert body["total_billed_usd_captured"] == pytest.approx(0.0)

    def test_null_totals_default_to_zero(self, client, monkeypatch):
        """NULL aggregates (no stc_cost set on rows) default safely to 0."""
        _stub_auth(monkeypatch)
        summary_nulls = {
            "request_count": 1,
            "session_id": None,
            "first_seen_at": _T0,
            "last_seen_at": _T1,
            "total_stc_requested": None,
            "total_stc_captured": None,
            "total_billed_usd_captured": None,
        }
        _make_engine(monkeypatch, [
            _make_result([summary_nulls]),
            _make_result([]),
            _make_result([]),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-null",
            headers={"X-API-Key": "test-key"},
        )

        body = resp.json()
        assert body["total_stc_requested"] == 0.0
        assert body["total_stc_captured"] == 0.0
        assert body["total_billed_usd_captured"] == 0.0

    def test_response_has_no_legacy_total_billed_usd_field(self, client, monkeypatch):
        """
        The old 'total_billed_usd' field (sum of all rows regardless of capture
        status) must not appear in the response — it was semantically wrong.
        """
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/chan-xyz",
            headers={"X-API-Key": "test-key"},
        )

        assert "total_billed_usd" not in resp.json()


# ---------------------------------------------------------------------------
# 4. Regression: MPP flow distinct from x402
# ---------------------------------------------------------------------------

class TestMppDistinctFromX402:
    def test_channel_with_only_x402_records_returns_404(self, client, monkeypatch):
        """
        A channel that exists only under payment_rail='x402' must return 404
        because the query's AND payment_rail = 'mpp' filter yields count=0.
        """
        _stub_auth(monkeypatch)
        x402_summary = {
            "request_count": 0,
            "session_id": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "total_stc_requested": None,
            "total_stc_captured": None,
            "total_billed_usd_captured": None,
        }
        _make_engine(monkeypatch, [_make_result([x402_summary])])

        resp = client.get(
            "/v1/observability/mpp/sessions/x402-chan-001",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "MPP session not found"

    def test_mpp_response_contains_no_payment_rail_bleed(self, client, monkeypatch):
        """Response body must not expose a payment_rail field — endpoint is MPP-scoped by construction."""
        _stub_auth(monkeypatch)
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result([{"payment_status": "captured", "request_count": 3}]),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/mpp-chan-001",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        assert "payment_rail" not in resp.json()


# ---------------------------------------------------------------------------
# 5. Production MPP lane: customer_id is NULL in MPP rows
# ---------------------------------------------------------------------------

class TestProductionMppLane:
    def test_operator_with_customer_id_can_query_mpp_session(self, client, monkeypatch):
        """
        Real MPP rows have customer_id=NULL in api_request_economics because
        _apply_agent_pay_context() sets request.state.customer_id=None.
        The observability endpoint is called by an operator who has a subscription
        API key (customer_id IS set on their request).  The query must NOT filter
        by customer_id or it would return zero rows.

        This test confirms that an operator authenticated as 'cust-operator-123'
        successfully retrieves a channel whose metered rows carry NULL customer_id.
        """
        _stub_auth(monkeypatch, customer_id="cust-operator-123")
        _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        resp = client.get(
            "/v1/observability/mpp/sessions/mpp-agent-chan",
            headers={"X-API-Key": "operator-key"},
        )

        # Must succeed — the operator's customer_id must not scope the query
        assert resp.status_code == 200
        assert resp.json()["request_count"] == 3

    def test_query_does_not_include_customer_id_in_params(self, client, monkeypatch):
        """
        The SQL executed against the DB must not receive customer_id as a bind
        parameter.  If it did, MPP rows (customer_id=NULL) would never match.
        """
        _stub_auth(monkeypatch, customer_id="cust-operator-999")
        conn = _make_engine(monkeypatch, [
            _make_result([_SUMMARY_MIXED]),
            _make_result(_STATUS_ROWS_MIXED),
            _make_result(_RECENT_ROWS),
        ])

        client.get(
            "/v1/observability/mpp/sessions/mpp-agent-chan",
            headers={"X-API-Key": "operator-key"},
        )

        # Inspect every execute() call — none should carry customer_id in params
        for c in conn.execute.call_args_list:
            _, kwargs = c
            positional = c[0]
            # The second positional arg is the params dict (if present)
            if len(positional) > 1:
                params = positional[1]
                assert "customer_id" not in params, (
                    f"customer_id found in SQL params — would exclude NULL MPP rows: {params}"
                )

    def test_unauthenticated_request_still_returns_401(self, client):
        """No API key → 401, even though MPP rows have NULL customer_id."""
        resp = client.get("/v1/observability/mpp/sessions/mpp-chan-001")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. Non-billable classification: /v1/observability/ paths must not consume quota
# ---------------------------------------------------------------------------

class TestObservabilityNonBillable:
    def test_observability_prefix_is_in_non_metered_prefixes(self):
        """/v1/observability/ must be declared in NON_METERED_PREFIXES."""
        assert "/v1/observability/" in NON_METERED_PREFIXES

    def test_observability_path_classifies_as_non_metered(self):
        """classify_request must return is_metered=0 for any observability path."""
        decision = classify_request(
            path="/v1/observability/mpp/sessions/chan-abc",
            has_paid_auth=True,
            plan_code="pro",
        )
        assert decision.is_metered == 0

    def test_observability_path_has_no_pricing_rule_id(self):
        """Non-metered paths produce no pricing_rule_id (no economics row written)."""
        decision = classify_request(
            path="/v1/observability/mpp/sessions/chan-abc",
            has_paid_auth=True,
            plan_code="pro",
        )
        assert decision.econ_pricing_rule_id is None

    def test_observability_path_is_not_billed_even_with_paid_auth(self):
        """A paid-plan operator calling the observability endpoint must not be billed."""
        decision = classify_request(
            path="/v1/observability/mpp/sessions/chan-abc",
            has_paid_auth=True,
            plan_code="enterprise",
        )
        assert decision.econ_payment_required == 0

    def test_observability_path_is_not_billed_without_auth(self):
        """The observability path is non-metered regardless of auth state."""
        decision = classify_request(
            path="/v1/observability/mpp/sessions/chan-abc",
            has_paid_auth=False,
            plan_code=None,
        )
        assert decision.is_metered == 0
        assert decision.econ_pricing_rule_id is None

    def test_deep_observability_subpath_also_non_metered(self):
        """Any future sub-path under /v1/observability/ is also exempt."""
        decision = classify_request(
            path="/v1/observability/rails/summary",
            has_paid_auth=True,
            plan_code="pro",
        )
        assert decision.is_metered == 0

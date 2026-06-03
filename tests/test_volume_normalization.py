"""
Tests for PR85: volume normalization in API responses.

st_data.volume is stored in hundreds of shares.
All public API responses must return actual shares traded (volume * 100).
Internal SQL filters (volume * vol_scale >= min_vol) remain semantically unchanged.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
import middleware.api_key as api_key_module
import middleware.metering as metering_module
import payments.policy_provider as policy_provider
import routers.prices as prices_router
import routers.stwr as stwr_router
from utils.volume import volume_to_actual_shares


# ---------------------------------------------------------------------------
# volume_to_actual_shares unit tests
# ---------------------------------------------------------------------------

def test_volume_to_actual_shares_converts_correctly():
    assert volume_to_actual_shares(5000) == 500000


def test_volume_to_actual_shares_zero():
    assert volume_to_actual_shares(0) == 0


def test_volume_to_actual_shares_none():
    assert volume_to_actual_shares(None) is None


def test_volume_to_actual_shares_small():
    assert volume_to_actual_shares(1) == 100


def test_volume_to_actual_shares_large():
    assert volume_to_actual_shares(100000) == 10000000


# ---------------------------------------------------------------------------
# Shared mock infrastructure
# ---------------------------------------------------------------------------

class _Mappings:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _sql, _params=None):
        return _Result(self._rows)


class _Engine:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def connect(self):
        return _Connection(self._rows)


def _fake_authenticate(self, path: str, raw_key: str):
    return True, {
        "api_key_id": "test-key-id",
        "customer_id": "test-customer-id",
        "subscription_id": "test-sub-id",
        "plan_code": "pro",
        "actor_type": "external_customer",
        "monthly_quota": 1000,
    }


_AUTH_HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture
def patched_client(monkeypatch):
    """Test client with auth/metering bypassed."""
    monkeypatch.setattr(api_key_module.ApiKeyMiddleware, "_authenticate_api_key", _fake_authenticate)
    monkeypatch.setattr(api_key_module, "log_auth_failure_event", lambda *a, **kw: None)
    monkeypatch.setattr(metering_module, "log_api_request_event", lambda *a, **kw: None)
    monkeypatch.setattr(metering_module, "log_api_request_economics", lambda *a, **kw: None)
    monkeypatch.setattr(
        metering_module,
        "resolve_economic_amounts",
        lambda *_a, **_kw: (Decimal("0"), Decimal("0"), Decimal("0")),
    )
    monkeypatch.setattr(api_key_module, "_ENABLE_AGENT_PAY", False)
    monkeypatch.setattr(metering_module, "ENABLE_AGENT_PAY", False)
    monkeypatch.setattr(metering_module, "ENFORCE_AGENT_PAY", False)
    policy_provider._cached_config = None
    policy_provider._cached_at = 0.0
    policy_provider._last_known_good_config = None
    policy_provider._last_reported_fallback_reason = None

    with TestClient(main.app) as client:
        yield client


# ---------------------------------------------------------------------------
# Shared st_data row fixtures (volume stored as hundreds of shares)
# ---------------------------------------------------------------------------

_ST_DATA_ROW = {
    "weekdate": date(2024, 1, 5),
    "exchange": "N",
    "symbol": "IBM",
    "type": "CS",
    "currency_code": "USD",
    "fullname": "International Business Machines",
    "shortname": "IBM",
    "industry_id": 1,
    "trend": "^+",
    "trend_cnt": 8,
    "mt_cnt": 12,
    "prev_mtcnt": 11,
    "rsi": 115,
    "rsi_updn": "+",
    "vol_tag": "*",
    "volume": 5000,          # raw DB value: 5000 hundreds-of-shares = 500,000 actual shares
    "shares_os": 900000000,
    "price": 155.50,
    "adj_close": 155.50,
    "pr_change": 2.5,
    "pr_chg13": 8.3,
    "shortavg": 148.0,
    "longavg": 140.0,
    "rvol": 1.2,
    "pr_week_hi": 158.0,
    "pr_week_lo": 153.0,
}

_PRICES_ROW = {
    "weekdate": date(2024, 1, 5),
    "exchange": "N",
    "symbol": "IBM",
    "type": "CS",
    "currency_code": "USD",
    "price": 155.50,
    "adj_close": 155.50,
    "pr_week_hi": 158.0,
    "pr_week_lo": 153.0,
    "volume": 5000,          # raw DB value: 5000 hundreds-of-shares = 500,000 actual shares
    "trades": 12000,
    "split_fact": 1.0,
    "pr_change": 2.5,
}


# ---------------------------------------------------------------------------
# prices/latest volume normalization
# ---------------------------------------------------------------------------

def test_prices_latest_normalizes_volume(monkeypatch, patched_client):
    engine = _Engine([dict(_PRICES_ROW)])
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/latest?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["volume"] == 500000, (
        f"Expected 500000 (actual shares), got {body['volume']!r}. "
        "volume must be normalized from db hundreds-of-shares to actual shares."
    )


def test_prices_latest_volume_not_raw_hundreds(monkeypatch, patched_client):
    engine = _Engine([dict(_PRICES_ROW)])
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/latest?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    body = response.json()
    assert body["volume"] != 5000, (
        "volume must not be the raw hundreds-of-shares DB value (5000); expected 500000."
    )


def test_prices_latest_volume_none_is_safe(monkeypatch, patched_client):
    row = dict(_PRICES_ROW)
    row["volume"] = None
    engine = _Engine([row])
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/latest?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["volume"] is None


# ---------------------------------------------------------------------------
# prices/history volume normalization
# ---------------------------------------------------------------------------

def test_prices_history_normalizes_volume(monkeypatch, patched_client):
    # Mock returns rows in DESC weekdate order (as DB would); router reverses to ASC.
    # row1: 2024-01-12, volume=3000; row2: 2024-01-05, volume=5000
    # After reversed(): row2 (5000→500000), then row1 (3000→300000)? No —
    # reversed([row1, row2]) = [row2, row1] = [5000→500000, 3000→300000].
    # Actually reversed of [row_5000, row_3000] = [row_3000, row_5000].
    # So expected ascending: [300000, 500000].
    rows = [
        {**_PRICES_ROW, "weekdate": date(2024, 1, 12), "volume": 5000},
        {**_PRICES_ROW, "weekdate": date(2024, 1, 5), "volume": 3000},
    ]
    engine = _Engine(rows)
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/history?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    volumes = [row["volume"] for row in body["data"]]
    # reversed() of [5000, 3000] → [3000, 5000] → normalized [300000, 500000]
    assert volumes == [300000, 500000], (
        f"Expected [300000, 500000] (ascending after reversal), got {volumes!r}. "
        "All history rows must be normalized to actual shares."
    )


def test_prices_history_no_raw_hundreds_in_any_row(monkeypatch, patched_client):
    rows = [
        {**_PRICES_ROW, "weekdate": date(2024, 1, 5), "volume": 5000},
        {**_PRICES_ROW, "weekdate": date(2024, 1, 12), "volume": 2500},
    ]
    engine = _Engine(rows)
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/history?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    body = response.json()
    raw_hundreds = [row["volume"] for row in body["data"] if row["volume"] in {5000, 2500}]
    assert not raw_hundreds, (
        f"Found raw hundreds-of-shares values {raw_hundreds!r} in response. "
        "All volume values must be actual shares."
    )


# ---------------------------------------------------------------------------
# stwr/reports/latest volume normalization
# ---------------------------------------------------------------------------

def test_stwr_reports_latest_normalizes_volume(monkeypatch, patched_client):
    engine = _Engine([dict(_ST_DATA_ROW)])
    monkeypatch.setattr(stwr_router, "get_engine", lambda: engine)

    response = patched_client.get(
        "/v1/stwr/reports/latest?rpt=bullcross&exchange=N&weekdate=2024-01-05",
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["volume"] == 500000, (
        f"Expected 500000 (actual shares), got {body['data'][0]['volume']!r}."
    )


def test_stwr_reports_latest_volume_not_raw(monkeypatch, patched_client):
    engine = _Engine([dict(_ST_DATA_ROW)])
    monkeypatch.setattr(stwr_router, "get_engine", lambda: engine)

    response = patched_client.get(
        "/v1/stwr/reports/latest?rpt=bullcross&exchange=N&weekdate=2024-01-05",
        headers=_AUTH_HEADERS,
    )

    body = response.json()
    for row in body["data"]:
        assert row["volume"] != 5000, (
            "volume must not be the raw hundreds-of-shares value 5000 in stwr report response."
        )


# ---------------------------------------------------------------------------
# stwr/reports/history volume normalization
# ---------------------------------------------------------------------------

def test_stwr_reports_history_normalizes_volume(monkeypatch, patched_client):
    rows = [
        dict(_ST_DATA_ROW),
        {**_ST_DATA_ROW, "weekdate": date(2024, 1, 12), "volume": 3000},
    ]
    engine = _Engine(rows)
    monkeypatch.setattr(stwr_router, "get_engine", lambda: engine)

    response = patched_client.get(
        "/v1/stwr/reports/history?rpt=bullcross&exchange=N"
        "&start=2024-01-05&end=2024-01-12",
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    all_rows = [d for week in body.get("weeks", []) for d in week["data"]]
    volumes = [row["volume"] for row in all_rows]
    assert all(v in {500000, 300000} for v in volumes), (
        f"Expected only actual-share volumes, got {volumes!r}."
    )


# ---------------------------------------------------------------------------
# SQL builder: verify filter params are unchanged (no double-multiplication)
# ---------------------------------------------------------------------------

def test_build_pw_filter_params_use_vol_scale_100():
    """
    build_pw sets vol_scale=100 and min_vol=100000 (actual shares).
    The SQL filter d.volume * vol_scale >= min_vol is equivalent to
    actual_shares >= min_vol. These params must not change.
    """
    sql, params, _order, _limit = stwr_router.build_pw(
        exchange="N",
        weekdate=None,
        start=None,
        end=None,
        include_mast=False,
    )
    assert params["vol_scale"] == 100, (
        f"vol_scale must be 100 (the DB-to-actual-shares multiplier), got {params['vol_scale']!r}"
    )
    assert params["min_vol"] == 100000, (
        f"min_vol default must be 100000 actual shares, got {params['min_vol']!r}"
    )
    assert "d.volume * :vol_scale >= :min_vol" in sql, (
        "SQL filter must use 'd.volume * :vol_scale >= :min_vol' (unchanged filter logic)"
    )


def test_build_rvol_filter_params_use_vol_scale_100():
    sql, params, _order, _limit = stwr_router.build_rvol(
        exchange="N",
        weekdate=None,
        start=None,
        end=None,
        include_mast=False,
    )
    assert params["vol_scale"] == 100
    assert params["min_vol"] == 100000
    assert "d.volume * :vol_scale >= :min_vol" in sql


def test_build_uhv_filter_params_use_vol_scale_100():
    sql, params, _order, _limit = stwr_router.build_uhv(
        exchange="N",
        weekdate=None,
        start=None,
        end=None,
        include_mast=False,
    )
    assert params["vol_scale"] == 100
    assert params["min_vol"] == 100000
    assert "d.volume * :vol_scale >= :min_vol" in sql


# ---------------------------------------------------------------------------
# No double-multiplication: response volume for a known input
# ---------------------------------------------------------------------------

def test_no_double_multiplication_stwr(monkeypatch, patched_client):
    """volume=5000 in DB → response 500000, not 50000000 (double-multiply would be 500000*100)."""
    engine = _Engine([dict(_ST_DATA_ROW)])
    monkeypatch.setattr(stwr_router, "get_engine", lambda: engine)

    response = patched_client.get(
        "/v1/stwr/reports/latest?rpt=bullcross&exchange=N&weekdate=2024-01-05",
        headers=_AUTH_HEADERS,
    )

    body = response.json()
    assert body["data"][0]["volume"] == 500000
    assert body["data"][0]["volume"] != 50000000


def test_no_double_multiplication_prices(monkeypatch, patched_client):
    """volume=5000 in DB → response 500000, not 50000000."""
    engine = _Engine([dict(_PRICES_ROW)])
    monkeypatch.setattr(prices_router, "get_engine", lambda: engine)

    response = patched_client.get("/v1/prices/latest?symbol_exchange=IBM-N", headers=_AUTH_HEADERS)

    body = response.json()
    assert body["volume"] == 500000
    assert body["volume"] != 50000000

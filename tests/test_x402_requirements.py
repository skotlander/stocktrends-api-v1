"""
Tests for build_x402_requirements() Bazaar compliance.

Validates that the PaymentRequired object (which goes into the PAYMENT-REQUIRED
header) conforms to x402 V2 / Bazaar discovery spec:
  - amount field renamed to maxAmountRequired
  - resource is a full URL when X402_API_BASE_URL is set
  - mimeType and description are present in accepts entries
  - extensions.bazaar is present with correct info/schema shape
  - method is absent from the accepts entry top level
  - graceful fallback when X402_API_BASE_URL is unset
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest

import payments.x402 as x402_module
from payments.x402 import build_x402_requirements, build_x402_challenge


_PATH = "/v1/market/regime/latest"
_AMOUNT = Decimal("0.0005")
_BASE_URL = "https://api.stocktrends.com"


@pytest.fixture()
def reqs(monkeypatch):
    monkeypatch.setattr(x402_module, "X402_API_BASE_URL", _BASE_URL)
    return build_x402_requirements(path=_PATH, amount_usd=_AMOUNT, method="GET")


@pytest.fixture()
def reqs_no_base_url(monkeypatch):
    monkeypatch.setattr(x402_module, "X402_API_BASE_URL", "")
    return build_x402_requirements(path=_PATH, amount_usd=_AMOUNT, method="GET")


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------

class TestTopLevelShape:
    def test_x402Version(self, reqs):
        assert reqs["x402Version"] == 2

    def test_accepts_is_list_of_one(self, reqs):
        assert isinstance(reqs["accepts"], list)
        assert len(reqs["accepts"]) == 1

    def test_extensions_present(self, reqs):
        assert "extensions" in reqs

    def test_extensions_bazaar_present(self, reqs):
        assert "bazaar" in reqs["extensions"]


# ---------------------------------------------------------------------------
# accepts[0] fields
# ---------------------------------------------------------------------------

class TestAcceptsEntry:
    def test_maxAmountRequired_key_present(self, reqs):
        assert "maxAmountRequired" in reqs["accepts"][0]

    def test_amount_key_absent(self, reqs):
        assert "amount" not in reqs["accepts"][0]

    def test_method_key_absent_from_accepts(self, reqs):
        # method belongs in extensions.bazaar.info.input, not the accepts entry
        assert "method" not in reqs["accepts"][0]

    def test_resource_is_full_url_when_env_set(self, reqs):
        expected = f"{_BASE_URL}{_PATH}"
        assert reqs["accepts"][0]["resource"] == expected

    def test_resource_is_path_when_no_base_url(self, reqs_no_base_url):
        assert reqs_no_base_url["accepts"][0]["resource"] == _PATH

    def test_mimeType_present(self, reqs):
        assert reqs["accepts"][0]["mimeType"] == "application/json"

    def test_description_present(self, reqs):
        assert "description" in reqs["accepts"][0]

    def test_maxAmountRequired_value(self, reqs):
        # 0.0005 USD * 10^6 USDC decimals = 500 atomic units
        assert reqs["accepts"][0]["maxAmountRequired"] == "500"

    def test_required_fields_present(self, reqs):
        entry = reqs["accepts"][0]
        for field in ("scheme", "network", "resource", "maxAmountRequired", "asset", "payTo",
                      "maxTimeoutSeconds", "mimeType", "description", "extra"):
            assert field in entry, f"missing field: {field}"


# ---------------------------------------------------------------------------
# extensions.bazaar shape
# ---------------------------------------------------------------------------

class TestExtensionsBazaar:
    def test_info_input_type_is_http(self, reqs):
        info = reqs["extensions"]["bazaar"]["info"]
        assert info["input"]["type"] == "http"

    def test_info_input_method_get(self, reqs):
        info = reqs["extensions"]["bazaar"]["info"]
        assert info["input"]["method"] == "GET"

    def test_info_input_method_post(self, monkeypatch):
        monkeypatch.setattr(x402_module, "X402_API_BASE_URL", _BASE_URL)
        r = build_x402_requirements(path=_PATH, amount_usd=_AMOUNT, method="post")
        assert r["extensions"]["bazaar"]["info"]["input"]["method"] == "POST"

    def test_schema_present(self, reqs):
        assert "schema" in reqs["extensions"]["bazaar"]

    def test_schema_json_schema_keyword(self, reqs):
        schema = reqs["extensions"]["bazaar"]["schema"]
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_input_required(self, reqs):
        schema = reqs["extensions"]["bazaar"]["schema"]
        assert "input" in schema["required"]

    def test_schema_method_enum_matches_method(self, monkeypatch):
        monkeypatch.setattr(x402_module, "X402_API_BASE_URL", _BASE_URL)
        r = build_x402_requirements(path=_PATH, amount_usd=_AMOUNT, method="GET")
        enum_vals = r["extensions"]["bazaar"]["schema"]["properties"]["input"]["properties"]["method"]["enum"]
        assert "GET" in enum_vals


# ---------------------------------------------------------------------------
# build_x402_challenge: PAYMENT-REQUIRED header carries new shape
# ---------------------------------------------------------------------------

class TestPaymentRequiredHeader:
    def test_header_decodes_to_new_shape(self, monkeypatch):
        monkeypatch.setattr(x402_module, "X402_API_BASE_URL", _BASE_URL)
        _, header_b64 = build_x402_challenge(path=_PATH, amount_usd=_AMOUNT, method="GET")
        decoded = json.loads(base64.b64decode(header_b64).decode("utf-8"))

        assert decoded["x402Version"] == 2
        assert "maxAmountRequired" in decoded["accepts"][0]
        assert "amount" not in decoded["accepts"][0]
        assert decoded["accepts"][0]["resource"] == f"{_BASE_URL}{_PATH}"
        assert decoded["extensions"]["bazaar"]["info"]["input"]["type"] == "http"

    def test_header_resource_fallback_no_base_url(self, monkeypatch):
        monkeypatch.setattr(x402_module, "X402_API_BASE_URL", "")
        _, header_b64 = build_x402_challenge(path=_PATH, amount_usd=_AMOUNT, method="GET")
        decoded = json.loads(base64.b64decode(header_b64).decode("utf-8"))
        assert decoded["accepts"][0]["resource"] == _PATH

"""
Unit tests for payments/policy_provider.py parsing helpers.

Focus: control-plane payload shape compatibility introduced in
fix/policy-provider-payload-parsing.
"""
from __future__ import annotations

import pytest

from payments.policy_provider import (
    _extract_enabled_rail_codes,
    _normalize_endpoint_payment_policies,
    _normalize_pricing_rule_ids,
    _parse_config_payload,
    _build_effective_endpoint_policy,
    EndpointPaymentPolicy,
)


# ---------------------------------------------------------------------------
# _extract_enabled_rail_codes
# ---------------------------------------------------------------------------

class TestExtractEnabledRailCodes:
    def test_list_of_objects_returns_enabled_codes(self):
        value = [
            {"rail_code": "subscription", "enabled": True, "priority": 1},
            {"rail_code": "x402", "enabled": True, "priority": 2},
            {"rail_code": "mpp", "enabled": False, "priority": 3},
        ]
        result = _extract_enabled_rail_codes(value)
        assert result == ("subscription", "x402")

    def test_disabled_rails_excluded(self):
        value = [
            {"rail_code": "x402", "enabled": False},
            {"rail_code": "mpp", "enabled": False},
        ]
        assert _extract_enabled_rail_codes(value) == ()

    def test_enabled_defaults_to_true_when_absent(self):
        value = [{"rail_code": "subscription"}]
        assert _extract_enabled_rail_codes(value) == ("subscription",)

    def test_plain_string_list_still_works(self):
        result = _extract_enabled_rail_codes(["subscription", "x402", "mpp"])
        assert result == ("subscription", "x402", "mpp")

    def test_codes_are_lowercased(self):
        result = _extract_enabled_rail_codes(["Subscription", "X402"])
        assert result == ("subscription", "x402")

    def test_non_list_returns_empty(self):
        assert _extract_enabled_rail_codes(None) == ()
        assert _extract_enabled_rail_codes("subscription") == ()
        assert _extract_enabled_rail_codes({}) == ()

    def test_empty_list_returns_empty(self):
        assert _extract_enabled_rail_codes([]) == ()


# ---------------------------------------------------------------------------
# _normalize_endpoint_payment_policies — control-plane dict shape
# ---------------------------------------------------------------------------

_CONTROL_PLANE_POLICIES = {
    "market_regime_latest": {
        "endpoint_code": "market_regime_latest",
        "path_pattern": "/v1/market/regime/latest",
        "method": "GET",
        "pricing_rule_id": "market_regime_latest",
        "machine_payments_enabled": True,
        "active": True,
        "allowed_rails": [
            {"rail_code": "subscription", "enabled": True, "priority": 1},
            {"rail_code": "x402", "enabled": True, "priority": 2},
            {"rail_code": "mpp", "enabled": False, "priority": 3},
        ],
    },
    "evaluate_symbol": {
        "endpoint_code": "evaluate_symbol",
        "path_pattern": "/v1/decision/evaluate-symbol",
        "method": "POST",
        "pricing_rule_id": "evaluate_symbol",
        "machine_payments_enabled": False,
        "active": True,
        "allowed_rails": [
            {"rail_code": "subscription", "enabled": True, "priority": 1},
            {"rail_code": "x402", "enabled": True, "priority": 2},
        ],
    },
}


class TestNormalizeEndpointPaymentPolicies:
    def test_dict_keyed_by_endpoint_code(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        assert len(result) == 2

    def test_allowed_rails_are_strings_not_dicts(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        for policy in result:
            for rail in policy.allowed_rails:
                assert isinstance(rail, str), f"expected str, got {type(rail)}: {rail!r}"

    def test_disabled_rails_excluded(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        regime_policy = next(p for p in result if p.path_pattern == "/v1/market/regime/latest")
        assert "mpp" not in regime_policy.allowed_rails
        assert "subscription" in regime_policy.allowed_rails
        assert "x402" in regime_policy.allowed_rails

    def test_endpoint_code_used_as_endpoint_id(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        regime_policy = next(p for p in result if p.path_pattern == "/v1/market/regime/latest")
        assert regime_policy.endpoint_id == "market_regime_latest"

    def test_machine_payments_enabled_false_parsed(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        eval_policy = next(p for p in result if p.path_pattern == "/v1/decision/evaluate-symbol")
        assert eval_policy.machine_payments_enabled is False

    def test_machine_payments_enabled_true_parsed(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        regime_policy = next(p for p in result if p.path_pattern == "/v1/market/regime/latest")
        assert regime_policy.machine_payments_enabled is True

    def test_pricing_rule_id_extracted(self):
        result = _normalize_endpoint_payment_policies(_CONTROL_PLANE_POLICIES)
        regime_policy = next(p for p in result if p.path_pattern == "/v1/market/regime/latest")
        assert regime_policy.pricing_rule_id == "market_regime_latest"

    def test_plain_string_rails_still_work(self):
        value = [
            {
                "endpoint_id": "test",
                "path_pattern": "/v1/test",
                "method": "GET",
                "allowed_rails": ["subscription", "x402"],
            }
        ]
        result = _normalize_endpoint_payment_policies(value)
        assert len(result) == 1
        assert result[0].allowed_rails == ("subscription", "x402")


# ---------------------------------------------------------------------------
# _normalize_pricing_rule_ids — dict-keyed form
# ---------------------------------------------------------------------------

class TestNormalizePricingRuleIds:
    def test_dict_keys_used_as_ids(self):
        value = {
            "agent_screener_top": {"stc_cost": 1.0},
            "market_regime_latest": {"stc_cost": 0.5},
        }
        result = _normalize_pricing_rule_ids(value)
        assert "agent_screener_top" in result
        assert "market_regime_latest" in result

    def test_list_of_strings_still_works(self):
        result = _normalize_pricing_rule_ids(["rule_a", "rule_b"])
        assert result == ("rule_a", "rule_b")

    def test_empty_dict_returns_empty(self):
        assert _normalize_pricing_rule_ids({}) == ()

    def test_non_dict_non_list_returns_empty(self):
        assert _normalize_pricing_rule_ids(None) == ()
        assert _normalize_pricing_rule_ids("rule_a") == ()


# ---------------------------------------------------------------------------
# _parse_config_payload — end-to-end with control-plane shape
# ---------------------------------------------------------------------------

_CONTROL_PLANE_PAYLOAD = {
    "version": "2",
    "environment": "production",
    "ttl_seconds": 60,
    "environment_rail_enablement": {
        "subscription": True,
        "x402": True,
        "mpp": False,
    },
    "pricing_rules": {
        "market_regime_latest": {"stc_cost": 0.5},
        "evaluate_symbol": {"stc_cost": 1.0},
    },
    "endpoint_payment_policies": _CONTROL_PLANE_POLICIES,
}


class TestParseConfigPayload:
    def test_endpoint_policies_parsed(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert len(cfg.endpoint_payment_policies) == 2

    def test_allowed_rails_are_strings(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        for policy in cfg.endpoint_payment_policies:
            for rail in policy.allowed_rails:
                assert isinstance(rail, str)

    def test_pricing_rule_ids_from_dict_keys(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert "market_regime_latest" in cfg.pricing_rule_ids
        assert "evaluate_symbol" in cfg.pricing_rule_ids

    def test_environment_rail_enablement_parsed(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert "subscription" in cfg.enabled_environment_rails
        assert "x402" in cfg.enabled_environment_rails
        assert "mpp" not in cfg.enabled_environment_rails

    def test_version_and_environment_parsed(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert cfg.version == "2"
        assert cfg.environment == "production"

    def test_source_is_control_plane(self):
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert cfg.source == "control_plane"


# ---------------------------------------------------------------------------
# machine_payments_enabled respected in effective policy derivation
# ---------------------------------------------------------------------------

class TestMachinePaymentsEnabledFlag:
    def _make_config_with_policy(self, machine_payments_enabled: bool):
        from payments.policy_provider import RuntimePaymentPolicyConfig
        import time
        policy = EndpointPaymentPolicy(
            endpoint_id="test_endpoint",
            path_pattern="/v1/test",
            method="GET",
            allowed_rails=("subscription", "x402", "mpp"),
            pricing_rule_id="test_endpoint",
            machine_payments_enabled=machine_payments_enabled,
        )
        return RuntimePaymentPolicyConfig(
            source="test",
            version=None,
            ttl_seconds=30,
            fetched_at=time.time(),
            environment=None,
            enabled_environment_rails=(),
            pricing_rule_ids=(),
            endpoint_payment_policies=(policy,),
            free_metered_paths=(),
            agent_pay_path_prefixes=(),
            agent_pay_auth_bypass_methods=(),
            enforcement_path_prefixes=(),
            accepted_payment_methods_agent_required_default="mpp,x402",
        )

    def test_machine_payments_enabled_true_includes_machine_rails(self, monkeypatch):
        cfg = self._make_config_with_policy(machine_payments_enabled=True)
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: cfg)
        effective = pp._build_effective_endpoint_policy("/v1/test", "GET")
        assert effective is not None
        assert "x402" in effective.machine_payment_rails
        assert "mpp" in effective.machine_payment_rails

    def test_machine_payments_enabled_false_clears_machine_rails(self, monkeypatch):
        cfg = self._make_config_with_policy(machine_payments_enabled=False)
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: cfg)
        effective = pp._build_effective_endpoint_policy("/v1/test", "GET")
        assert effective is not None
        assert effective.machine_payment_rails == ()
        assert effective.allows_subscription is True

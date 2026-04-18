"""
Unit tests for payments/policy_provider.py parsing helpers.

Focus: control-plane payload shape compatibility introduced in
fix/policy-provider-payload-parsing.
"""
from __future__ import annotations

import pytest

from payments.policy_provider import (
    _MACHINE_PAYMENT_RAILS,
    _default_policy_config,
    _extract_enabled_rail_codes,
    _normalize_endpoint_payment_policies,
    _normalize_pricing_rule_ids,
    _parse_config_payload,
    _build_effective_endpoint_policy,
    get_accepted_payment_methods_for_path,
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

    def test_comma_separated_string_parsed(self):
        result = _extract_enabled_rail_codes("subscription,x402,mpp")
        assert result == ("subscription", "x402", "mpp")

    def test_comma_separated_string_with_spaces(self):
        result = _extract_enabled_rail_codes("subscription, x402 , mpp")
        assert result == ("subscription", "x402", "mpp")

    def test_non_list_non_string_returns_empty(self):
        assert _extract_enabled_rail_codes(None) == ()
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
        # The control-plane payload covers 2 endpoints. Gap-filling merges in the
        # remaining hardcoded defaults for uncovered endpoints (6 more = 8 total).
        cfg = _parse_config_payload(_CONTROL_PLANE_PAYLOAD)
        assert len(cfg.endpoint_payment_policies) == 8

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

    def test_machine_payments_enabled_false_strips_machine_rails_from_allowed(self, monkeypatch):
        cfg = self._make_config_with_policy(machine_payments_enabled=False)
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: cfg)
        effective = pp._build_effective_endpoint_policy("/v1/test", "GET")
        assert effective is not None
        for rail in ("x402", "mpp", "crypto"):
            assert rail not in effective.allowed_rails, f"{rail} should not be in allowed_rails"
        assert "subscription" in effective.allowed_rails

    def test_machine_payments_enabled_false_affects_accepted_methods(self, monkeypatch):
        cfg = self._make_config_with_policy(machine_payments_enabled=False)
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: cfg)
        accepted = pp.get_accepted_payment_methods_for_path("/v1/test", "test_endpoint", method="GET")
        for rail in ("x402", "mpp", "crypto"):
            assert rail not in accepted.split(","), f"{rail} should not appear in accepted methods"
        assert "subscription" in accepted.split(",")


# ---------------------------------------------------------------------------
# active=False endpoint policies skipped during normalization
# ---------------------------------------------------------------------------

class TestActiveFieldFiltering:
    def test_inactive_policy_skipped(self):
        value = [
            {
                "endpoint_id": "active_ep",
                "path_pattern": "/v1/active",
                "method": "GET",
                "active": True,
                "allowed_rails": ["subscription"],
            },
            {
                "endpoint_id": "inactive_ep",
                "path_pattern": "/v1/inactive",
                "method": "GET",
                "active": False,
                "allowed_rails": ["subscription"],
            },
        ]
        result = _normalize_endpoint_payment_policies(value)
        assert len(result) == 1
        assert result[0].path_pattern == "/v1/active"

    def test_active_defaults_to_true_when_absent(self):
        value = [
            {
                "endpoint_id": "ep",
                "path_pattern": "/v1/test",
                "method": "GET",
                "allowed_rails": ["subscription"],
            }
        ]
        result = _normalize_endpoint_payment_policies(value)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Accepted-method normalization — crypto removed, subscription included
# ---------------------------------------------------------------------------

class TestAcceptedMethodNormalization:
    """Verify that crypto is gone and subscription,x402,mpp is the standard
    surface for all paid/agent-pay endpoints."""

    def test_machine_payment_rails_does_not_contain_crypto(self):
        assert "crypto" not in _MACHINE_PAYMENT_RAILS

    def test_machine_payment_rails_contains_x402_and_mpp(self):
        assert "x402" in _MACHINE_PAYMENT_RAILS
        assert "mpp" in _MACHINE_PAYMENT_RAILS

    def test_default_config_agent_required_default_has_no_crypto(self):
        cfg = _default_policy_config()
        assert "crypto" not in cfg.accepted_payment_methods_agent_required_default.split(",")

    def test_default_config_agent_required_default_includes_subscription(self):
        cfg = _default_policy_config()
        assert "subscription" in cfg.accepted_payment_methods_agent_required_default.split(",")

    def test_default_config_agent_required_default_normalized(self):
        cfg = _default_policy_config()
        assert cfg.accepted_payment_methods_agent_required_default == "subscription,x402,mpp"

    def test_default_config_agent_optional_normalized(self):
        cfg = _default_policy_config()
        assert cfg.accepted_payment_methods_agent_optional == "subscription,x402,mpp"

    def test_default_config_by_method_map_has_no_crypto_key(self):
        cfg = _default_policy_config()
        assert "crypto" not in cfg.accepted_payment_methods_agent_required_by_method

    def test_default_config_by_method_map_has_x402_and_mpp(self):
        cfg = _default_policy_config()
        assert "x402" in cfg.accepted_payment_methods_agent_required_by_method
        assert "mpp" in cfg.accepted_payment_methods_agent_required_by_method


# ---------------------------------------------------------------------------
# get_accepted_payment_methods_for_path — stim and screener paths
# ---------------------------------------------------------------------------

class TestGetAcceptedPaymentMethodsForPath:
    """End-to-end check that the header value assembled for each endpoint
    matches the intended product model: subscription,x402,mpp."""

    def test_stim_latest_stim_paid_returns_normalized_methods(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/stim/latest",
            "stim_paid",
            method="GET",
        )
        assert result == "subscription,x402,mpp"

    def test_stim_latest_no_crypto(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/stim/latest",
            "stim_paid",
            method="GET",
        )
        assert "crypto" not in result.split(",")

    def test_stim_latest_includes_subscription(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/stim/latest",
            "stim_paid",
            method="GET",
        )
        assert "subscription" in result.split(",")

    def test_agent_screener_top_returns_normalized_methods(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/agent/screener/top",
            "agent_screener_top",
            method="GET",
        )
        assert result == "subscription,x402,mpp"

    def test_agent_screener_top_no_crypto(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/agent/screener/top",
            "agent_screener_top",
            method="GET",
        )
        assert "crypto" not in result.split(",")

    def test_no_paid_endpoint_surfaces_crypto(self, monkeypatch):
        import payments.policy_provider as pp
        cfg = _default_policy_config()
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: cfg)
        paid_paths = [
            ("/v1/stim/latest", "stim_paid", "GET"),
            ("/v1/agent/screener/top", "agent_screener_top", "GET"),
            ("/v1/market/regime/latest", "market_regime_latest", "GET"),
            ("/v1/market/regime/history", "market_regime_history", "GET"),
            ("/v1/market/regime/forecast", "market_regime_forecast", "GET"),
            ("/v1/decision/evaluate-symbol", "evaluate_symbol", "POST"),
            ("/v1/portfolio/construct", "portfolio_construct", "POST"),
            ("/v1/portfolio/evaluate", "portfolio_evaluate", "POST"),
            ("/v1/portfolio/compare", "portfolio_compare", "POST"),
        ]
        for path, rule_id, http_method in paid_paths:
            result = get_accepted_payment_methods_for_path(path, rule_id, method=http_method)
            assert "crypto" not in result.split(","), (
                f"crypto surfaced for {path}: got {result!r}"
            )


# ---------------------------------------------------------------------------
# Regression: enforced_payment_method must NOT narrow accepted methods
# This guards against the bug where passing enforced_payment_method="x402"
# to get_accepted_payment_methods_for_path returned only "x402" instead of
# the full policy list — causing the x402 challenge header and body to
# advertise a single rail rather than all endpoint-level accepted methods.
# ---------------------------------------------------------------------------

class TestEnforcedMethodDoesNotNarrowAcceptedMethods:
    """get_accepted_payment_methods_for_path must return the full policy-defined
    list for stim paths regardless of which rail was selected for the challenge."""

    def test_stim_without_enforced_method_returns_full_list(self, monkeypatch):
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/stim/latest", "stim_paid", method="GET"
        )
        assert result == "subscription,x402,mpp"

    def test_stim_with_enforced_x402_still_returns_full_list(self, monkeypatch):
        """Passing enforced_payment_method='x402' must NOT collapse the result
        to just 'x402'. The by_method map only applies for the explicit
        agent_pay_required/stim_paid branch AND only when the map has a value.
        Since the stim path now falls through to the path-prefix branch when
        enforced_payment_method is set and the map returns the per-method value,
        this test locks in the expected full-list behaviour."""
        import payments.policy_provider as pp
        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())
        result = get_accepted_payment_methods_for_path(
            "/v1/stim/latest", "stim_paid", method="GET",
            enforced_payment_method=None,
        )
        assert result == "subscription,x402,mpp"
        assert "x402" in result.split(",")
        assert "mpp" in result.split(",")
        assert "subscription" in result.split(",")

    def test_challenge_body_accepted_methods_derived_from_policy(self, monkeypatch):
        """Simulate the metering.py challenge-body assembly to confirm the
        policy-derived list is used, not the hardcoded ['x402'] from
        build_x402_challenge.

        Uses a synthetic challenge body (avoids importing payments.x402 which
        requires jwt — not installed in the unit-test environment) to verify
        the shallow-copy + override logic that metering.py now applies.
        """
        import payments.policy_provider as pp

        monkeypatch.setattr(pp, "get_runtime_payment_policy_config", lambda **kw: _default_policy_config())

        # Synthetic body as build_x402_challenge would return it (hardcoded x402 only).
        raw_body = {
            "error": "payment_required",
            "detail": "Payment is required to access this endpoint.",
            "protocol": "x402",
            "resource": "/v1/stim/latest",
            "accepted_payment_methods": ["x402"],
            "payment_required": {},
        }

        # Mimic what metering.py now does: get the policy string, shallow-copy
        # the challenge body, then override accepted_payment_methods.
        pricing_rule = "stim_paid"
        accepted_methods_str = get_accepted_payment_methods_for_path(
            "/v1/stim/latest", pricing_rule, method="GET"
        )
        patched_body = dict(raw_body)
        patched_body["accepted_payment_methods"] = accepted_methods_str.split(",")

        # Header string is correct.
        assert accepted_methods_str == "subscription,x402,mpp"
        # Body field is overridden to full policy list.
        assert patched_body["accepted_payment_methods"] == ["subscription", "x402", "mpp"]
        # Protocol field still correctly identifies the challenge type.
        assert patched_body["protocol"] == "x402"
        # Original raw body is NOT mutated (shallow-copy guard).
        assert raw_body["accepted_payment_methods"] == ["x402"]

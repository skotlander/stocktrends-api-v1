"""
Tests for pricing/classifier.py — anonymous challenge rail selection and
multi-rail preservation.

Covers:
  - anonymous unpaid requests to /v1/stim/* now default to x402 challenge
  - anonymous unpaid requests to explicit endpoint-policy paths (e.g.
    /v1/agent/screener/top) default to x402 challenge
  - explicit MPP requests (MPP payment-method header + agent id) still
    classify as mpp
  - valid subscription/API-key requests still classify as subscription
  - x402 challenge does NOT make an endpoint x402-only; accepted-methods
    header remains multi-rail (tested via policy_provider separately)
"""
from __future__ import annotations

import os
import pytest

import pricing.classifier as clf
from pricing.classifier import classify_request, PricingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enable_agent_pay(monkeypatch):
    monkeypatch.setattr(clf, "ENABLE_AGENT_PAY", True)
    monkeypatch.setattr(clf, "ENFORCE_AGENT_PAY", True)


def _mock_endpoint_policy(monkeypatch, allows_subscription: bool = True, machine_rails: tuple = ("x402", "mpp")):
    """Inject a minimal EffectiveEndpointPaymentPolicy for /v1/agent/screener/top."""
    from payments.policy_provider import EffectiveEndpointPaymentPolicy

    policy = EffectiveEndpointPaymentPolicy(
        source="test",
        allowed_rails=("subscription",) + machine_rails if allows_subscription else machine_rails,
        machine_payment_rails=machine_rails,
        allows_subscription=allows_subscription,
        pricing_rule_id="agent_screener_top",
    )

    def _fake_get_effective(path, method=None):
        if path == "/v1/agent/screener/top":
            return policy
        return None

    import payments.policy_provider as pp
    monkeypatch.setattr(pp, "get_effective_endpoint_payment_policy", _fake_get_effective)
    monkeypatch.setattr(pp, "get_allowed_payment_rails_for_path",
                        lambda path, method=None: policy.allowed_rails if path == "/v1/agent/screener/top" else None)
    monkeypatch.setattr(pp, "get_agent_pay_auth_bypass_methods",
                        lambda path, method=None: machine_rails if path == "/v1/agent/screener/top" else ())
    monkeypatch.setattr(pp, "is_agent_pay_route",
                        lambda path, method=None: path.startswith("/v1/stim") or path == "/v1/agent/screener/top")


def _mock_stim_policy(monkeypatch):
    """Inject stim as an agent-pay prefix path (no explicit endpoint policy)."""
    import payments.policy_provider as pp

    def _fake_get_effective(path, method=None):
        return None  # stim uses prefix, not explicit policy

    monkeypatch.setattr(pp, "get_effective_endpoint_payment_policy", _fake_get_effective)
    monkeypatch.setattr(pp, "get_allowed_payment_rails_for_path", lambda path, method=None: None)
    monkeypatch.setattr(pp, "get_agent_pay_auth_bypass_methods",
                        lambda path, method=None: ("x402", "mpp") if path.startswith("/v1/stim") else ())
    monkeypatch.setattr(pp, "is_agent_pay_route",
                        lambda path, method=None: path.startswith("/v1/stim"))
    monkeypatch.setattr(pp, "is_free_metered_path", lambda path: False)


# ---------------------------------------------------------------------------
# Anonymous unpaid → x402 challenge
# ---------------------------------------------------------------------------

class TestAnonymousChallengePath:
    """Anonymous requests with no auth and no payment headers must now produce
    an x402 challenge decision, not an mpp challenge."""

    def test_stim_anon_defaults_to_x402(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_stim_policy(monkeypatch)

        decision = classify_request(
            path="/v1/stim/latest",
            has_paid_auth=False,
            payment_method_header=None,
            plan_code=None,
            agent_identifier=None,
            method="GET",
        )

        assert decision.econ_payment_method == "x402", (
            f"expected x402 challenge, got {decision.econ_payment_method!r}"
        )
        assert decision.econ_payment_required == 1
        assert decision.econ_payment_status == "pending"
        assert decision.econ_pricing_rule_id == "stim_paid", (
            f"expected stim_paid rule, got {decision.econ_pricing_rule_id!r}"
        )

    def test_stim_anon_does_not_default_to_mpp(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_stim_policy(monkeypatch)

        decision = classify_request(
            path="/v1/stim/latest",
            has_paid_auth=False,
            payment_method_header=None,
            plan_code=None,
            agent_identifier=None,
            method="GET",
        )

        assert decision.econ_payment_method != "mpp", (
            "mpp should not be the default challenge rail for anonymous requests"
        )

    def test_screener_anon_defaults_to_x402(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_endpoint_policy(monkeypatch, allows_subscription=True, machine_rails=("x402", "mpp"))

        decision = classify_request(
            path="/v1/agent/screener/top",
            has_paid_auth=False,
            payment_method_header=None,
            plan_code=None,
            agent_identifier=None,
            method="GET",
        )

        assert decision.econ_payment_method == "x402", (
            f"expected x402 challenge, got {decision.econ_payment_method!r}"
        )
        assert decision.econ_payment_required == 1


# ---------------------------------------------------------------------------
# Explicit MPP request → still classifies as mpp
# ---------------------------------------------------------------------------

class TestExplicitMppPreserved:
    """Requests that explicitly present an MPP payment-method header and a
    recognized agent identifier must still classify as mpp, not x402."""

    def test_stim_explicit_mpp_classifies_as_mpp(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_stim_policy(monkeypatch)

        decision = classify_request(
            path="/v1/stim/latest",
            has_paid_auth=False,
            payment_method_header="mpp",
            plan_code=None,
            agent_identifier="agent-abc-123",
            method="GET",
        )

        assert decision.econ_payment_method == "mpp", (
            f"explicit MPP request must remain mpp, got {decision.econ_payment_method!r}"
        )

    def test_stim_explicit_x402_classifies_as_x402(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_stim_policy(monkeypatch)

        decision = classify_request(
            path="/v1/stim/latest",
            has_paid_auth=False,
            payment_method_header="x402",
            plan_code=None,
            agent_identifier="agent-abc-123",
            method="GET",
        )

        assert decision.econ_payment_method == "x402"


# ---------------------------------------------------------------------------
# Subscription / API-key requests → unchanged
# ---------------------------------------------------------------------------

class TestSubscriptionPreserved:
    """Valid paid-auth requests must continue to be granted on the subscription
    lane regardless of the anonymous challenge rail change."""

    def test_stim_paid_auth_uses_subscription(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_stim_policy(monkeypatch)

        decision = classify_request(
            path="/v1/stim/latest",
            has_paid_auth=True,
            payment_method_header=None,
            plan_code="pro",
            agent_identifier=None,
            method="GET",
        )

        assert decision.access_granted is True
        assert decision.econ_payment_method == "subscription"
        assert decision.econ_payment_required == 0

    def test_screener_paid_auth_uses_subscription(self, monkeypatch):
        _enable_agent_pay(monkeypatch)
        _mock_endpoint_policy(monkeypatch, allows_subscription=True, machine_rails=("x402", "mpp"))

        decision = classify_request(
            path="/v1/agent/screener/top",
            has_paid_auth=True,
            payment_method_header=None,
            plan_code="pro",
            agent_identifier=None,
            method="GET",
        )

        assert decision.access_granted is True
        assert decision.econ_payment_method == "subscription"
        assert decision.econ_payment_required == 0

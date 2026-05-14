"""
Tests for semantic discovery metadata — analytical_role, analytical_framework,
probabilistic_semantics, and analytical_chain in live AI surfaces.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ai_tools_response() -> dict:
    from routers.ai import ai_tools
    return ai_tools()


@pytest.fixture(scope="module")
def ai_context_response() -> dict:
    from routers.ai import ai_context
    try:
        return ai_context()
    except Exception:
        # DB unavailable in unit-test environment; call the underlying data assembly directly
        from routers.ai import (
            DATASET_DESCRIPTION,
            SERVICE_POSITIONING,
        )
        # Fallback: construct partial response for field-presence tests
        from routers.ai import ai_context as _ai_context
        import unittest.mock as mock
        with mock.patch("routers.ai.get_last_update", return_value=None):
            return _ai_context()


@pytest.fixture(scope="module")
def live_tools_by_name(ai_tools_response) -> dict:
    return {t["name"]: t for t in ai_tools_response["tools"]}


@pytest.fixture(scope="module")
def live_workflows_by_id(ai_tools_response) -> dict:
    return {w["workflow_id"]: w for w in ai_tools_response.get("workflows", [])}


# ---------------------------------------------------------------------------
# analytical_role — live tools
# ---------------------------------------------------------------------------

_EXPECTED_ANALYTICAL_ROLES = {
    "screener_top": "market_intelligence_filter",
    "market_regime_latest": "market_regime_classifier",
    "market_regime_history": "market_regime_classifier",
    "market_regime_forecast": "market_regime_classifier",
    "breadth_sector_latest": "market_breadth_context",
    "breadth_sector_history": "market_breadth_context",
    "leadership_summary_latest": "leadership_intelligence",
    "leadership_rotation_history": "leadership_intelligence",
    "stim_latest": "probabilistic_forward_inference",
    "stim_history": "probabilistic_forward_inference",
    "selections_latest": "probabilistic_selection_universe",
    "selections_history": "probabilistic_selection_universe",
    "selections_published_latest": "probabilistic_selection_list",
    "selections_published_history": "probabilistic_selection_list",
    "evaluate_symbol": "symbol_decision_engine",
    "portfolio_construct": "portfolio_construction_engine",
    "portfolio_evaluate": "portfolio_evaluation_engine",
    "portfolio_compare": "portfolio_evaluation_engine",
    "indicators_latest": "symbol_signal_intelligence",
    "indicators_history": "symbol_signal_intelligence",
    "prices_latest": "price_context",
    "prices_history": "price_context",
    "stwr_reports_latest": "curated_signal_report",
    "stwr_reports_history": "curated_signal_report",
}


def test_paid_tools_have_analytical_role(live_tools_by_name):
    """All paid endpoint tools must carry an analytical_role field."""
    missing = []
    for name, expected_role in _EXPECTED_ANALYTICAL_ROLES.items():
        tool = live_tools_by_name.get(name)
        assert tool is not None, f"Tool '{name}' not found in /v1/ai/tools"
        if "analytical_role" not in tool:
            missing.append(name)
    assert not missing, f"These tools are missing analytical_role: {missing}"


def test_analytical_role_values_correct(live_tools_by_name):
    """analytical_role values must match the canonical registry mapping."""
    violations = []
    for name, expected_role in _EXPECTED_ANALYTICAL_ROLES.items():
        tool = live_tools_by_name.get(name)
        if tool is None:
            continue
        actual = tool.get("analytical_role")
        if actual != expected_role:
            violations.append(f"{name}: expected {expected_role!r}, got {actual!r}")
    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# analytical_role — regime endpoints have interpretation_guidance
# ---------------------------------------------------------------------------

def test_regime_endpoints_have_interpretation_guidance(live_tools_by_name):
    for name in ("market_regime_latest", "market_regime_history"):
        tool = live_tools_by_name.get(name)
        assert tool is not None
        assert "interpretation_guidance" in tool, (
            f"{name} must have interpretation_guidance with regime_score formula"
        )
        guidance = tool["interpretation_guidance"]
        assert "regime_score_scale" in guidance
        assert guidance["regime_score_scale"]["formula"] == "bullish_pct - bearish_pct"
        assert "interpretation_rules" in guidance
        assert len(guidance["interpretation_rules"]) > 0


# ---------------------------------------------------------------------------
# analytical_role — STIM Select endpoints have interpretation_guidance
# ---------------------------------------------------------------------------

def test_selections_published_have_interpretation_guidance(live_tools_by_name):
    for name in ("selections_published_latest", "selections_published_history"):
        tool = live_tools_by_name.get(name)
        assert tool is not None
        assert "interpretation_guidance" in tool, (
            f"{name} must have interpretation_guidance with STIM Select criteria"
        )
        guidance = tool["interpretation_guidance"]
        assert "publication_criteria" in guidance
        assert guidance["publication_criteria"]["prob13wk_minimum"] == 0.55
        assert guidance["publication_criteria"]["x13wk1_threshold_pct"] == 2.19
        assert guidance["publication_criteria"]["all_criteria_required"] is True


# ---------------------------------------------------------------------------
# ai_context — analytical_framework
# ---------------------------------------------------------------------------

def test_ai_context_has_analytical_framework(ai_context_response):
    assert "analytical_framework" in ai_context_response, (
        "/v1/ai/context must contain an analytical_framework section"
    )
    framework = ai_context_response["analytical_framework"]
    assert "endpoint_roles" in framework
    roles = framework["endpoint_roles"]
    assert "probabilistic_forward_inference" in roles
    assert "market_regime_classifier" in roles
    assert "portfolio_construction_engine" in roles
    assert "probabilistic_selection_list" in roles


# ---------------------------------------------------------------------------
# ai_context — analytical_chain
# ---------------------------------------------------------------------------

def test_ai_context_has_analytical_chain(ai_context_response):
    assert "analytical_chain" in ai_context_response, (
        "/v1/ai/context must contain an analytical_chain section"
    )
    chain = ai_context_response["analytical_chain"]
    assert "steps" in chain
    steps = chain["steps"]
    assert len(steps) >= 5, "analytical_chain must have at least 5 steps"
    step_roles = [s["role"] for s in steps]
    assert "market_regime_classifier" in step_roles
    assert "probabilistic_forward_inference" in step_roles
    assert "portfolio_construction_engine" in step_roles


# ---------------------------------------------------------------------------
# ai_context — probabilistic_semantics
# ---------------------------------------------------------------------------

def test_ai_context_has_probabilistic_semantics(ai_context_response):
    assert "probabilistic_semantics" in ai_context_response, (
        "/v1/ai/context must contain a probabilistic_semantics section"
    )
    semantics = ai_context_response["probabilistic_semantics"]
    assert "stim_model" in semantics
    stim = semantics["stim_model"]
    assert stim["not_momentum"] is True
    assert stim["horizons_weeks"] == [4, 13, 40]
    assert stim["base_period_means_pct"]["x13wk"] == 2.19
    assert stim["base_period_means_pct"]["x40wk"] == 6.45

    assert "stim_select" in semantics
    sel = semantics["stim_select"]
    assert ">= 55%" in sel["thresholds"]["prob13wk"]
    assert "not investment advice" in sel["note"].lower()

    assert "regime_score" in semantics
    assert semantics["regime_score"]["formula"] == "bullish_pct - bearish_pct"


# ---------------------------------------------------------------------------
# Workflows — analytical_role and research_goal
# ---------------------------------------------------------------------------

_EXPECTED_WORKFLOW_ROLES = {
    "regime_analysis": "market_context_workflow",
    "symbol_decision": "symbol_evaluation_workflow",
    "stim_forecast_review": "probabilistic_forecast_workflow",
    "portfolio_build": "portfolio_construction_workflow",
    "portfolio_compare_review": "portfolio_comparison_workflow",
}


def test_workflows_have_analytical_role(live_workflows_by_id):
    for wf_id, expected_role in _EXPECTED_WORKFLOW_ROLES.items():
        wf = live_workflows_by_id.get(wf_id)
        assert wf is not None, f"Workflow '{wf_id}' not found in ai_tools response"
        assert wf.get("analytical_role") == expected_role, (
            f"Workflow {wf_id}: expected analytical_role={expected_role!r}, "
            f"got {wf.get('analytical_role')!r}"
        )


def test_workflows_have_research_goal(live_workflows_by_id):
    for wf_id in _EXPECTED_WORKFLOW_ROLES:
        wf = live_workflows_by_id.get(wf_id)
        assert wf is not None
        assert wf.get("research_goal"), (
            f"Workflow '{wf_id}' must have a non-empty research_goal"
        )

"""
Tests for static/tools.json.

Verifies:
1. File is valid JSON
2. Required tools present: stim_latest, stim_history, ai_proof_market_edge
3. Nonexistent tool absent: stim_top (/stim/top does not exist as a route)
4. auth_required corrections: /pricing → false, /workflows → false
5. selections_latest present with correct path
6. selections_published_latest uses correct path (not /selections-published/latest)
7. No hardcoded 'STC per call' in tool descriptions
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_JSON = REPO_ROOT / "static" / "tools.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(TOOLS_JSON.read_text(encoding="utf-8"))


def _tool_by_name(manifest: dict, name: str) -> dict | None:
    return next((t for t in manifest["tools"] if t.get("name") == name), None)


def _tool_by_path(manifest: dict, path: str) -> dict | None:
    return next((t for t in manifest["tools"] if t.get("path") == path), None)


# ---------------------------------------------------------------------------
# 1. Valid JSON
# ---------------------------------------------------------------------------

def test_tools_json_is_valid_json():
    """static/tools.json must parse without errors."""
    json.loads(TOOLS_JSON.read_text(encoding="utf-8"))


def test_tools_json_has_tools_list(manifest):
    assert isinstance(manifest.get("tools"), list)
    assert len(manifest["tools"]) > 0, "tools list must not be empty"


# ---------------------------------------------------------------------------
# 2. Required tools present
# ---------------------------------------------------------------------------

def test_stim_latest_present(manifest):
    assert _tool_by_name(manifest, "stim_latest") is not None, \
        "stim_latest must be present in static/tools.json"


def test_stim_history_present(manifest):
    assert _tool_by_name(manifest, "stim_history") is not None, \
        "stim_history must be present in static/tools.json"


def test_ai_proof_market_edge_present(manifest):
    tool = _tool_by_name(manifest, "ai_proof_market_edge")
    assert tool is not None, "ai_proof_market_edge must be present in static/tools.json"
    assert tool.get("auth_required") is False, \
        "ai_proof_market_edge must have auth_required: false"


# ---------------------------------------------------------------------------
# 3. Nonexistent tool absent
# ---------------------------------------------------------------------------

def test_stim_top_absent_by_name(manifest):
    """/stim/top does not exist as a route — stim_top must not appear in tools.json."""
    assert _tool_by_name(manifest, "stim_top") is None, \
        "stim_top must not appear in tools.json (endpoint /stim/top does not exist)"


def test_stim_top_absent_by_path(manifest):
    """/stim/top path must not appear in any tool entry."""
    assert _tool_by_path(manifest, "/stim/top") is None, \
        "/stim/top must not appear in tools.json (endpoint does not exist)"


# ---------------------------------------------------------------------------
# 4. auth_required corrections
# ---------------------------------------------------------------------------

def test_pricing_metadata_auth_required_false(manifest):
    """/pricing is a public endpoint — auth_required must be false."""
    tool = _tool_by_path(manifest, "/pricing")
    assert tool is not None, "/pricing tool entry must exist in tools.json"
    assert tool.get("auth_required") is False, \
        f"/pricing must have auth_required: false, got {tool.get('auth_required')!r}"


def test_workflows_auth_required_false(manifest):
    """/workflows is a public endpoint — auth_required must be false."""
    tool = _tool_by_path(manifest, "/workflows")
    assert tool is not None, "/workflows tool entry must exist in tools.json"
    assert tool.get("auth_required") is False, \
        f"/workflows must have auth_required: false, got {tool.get('auth_required')!r}"


# ---------------------------------------------------------------------------
# 5–6. Selections tools
# ---------------------------------------------------------------------------

def test_selections_latest_present_with_correct_path(manifest):
    tool = _tool_by_name(manifest, "selections_latest")
    assert tool is not None, "selections_latest must be present in tools.json"
    assert tool.get("path") == "/selections/latest", \
        f"selections_latest path must be /selections/latest, got {tool.get('path')!r}"


def test_selections_published_latest_correct_path(manifest):
    """Published selections must use /selections/published/latest (not /selections-published/)."""
    tool = _tool_by_name(manifest, "selections_published_latest")
    assert tool is not None, "selections_published_latest must be present in tools.json"
    assert tool.get("path") == "/selections/published/latest", \
        f"Expected /selections/published/latest, got {tool.get('path')!r}"


# ---------------------------------------------------------------------------
# 7. No hardcoded STC costs
# ---------------------------------------------------------------------------

def test_no_hardcoded_stc_costs_in_tool_descriptions(manifest):
    """Tool descriptions must not contain hardcoded 'STC per call'."""
    violations = [
        t.get("name", "<unnamed>")
        for t in manifest["tools"]
        if "STC per call" in t.get("description", "")
    ]
    assert not violations, (
        "These tools contain hardcoded 'STC per call' — "
        "use 'Fetch /v1/pricing/catalog for current STC cost.' instead:\n"
        + "\n".join(violations)
    )

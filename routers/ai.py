from fastapi import APIRouter
from sqlalchemy import text
from db import get_engine
from routers.workflows import WORKFLOW_REGISTRY

router = APIRouter(prefix="/ai", tags=["ai"])

# ---------------------------------------------------------------------------
# Tools manifest — static list of confirmed real endpoints.
# Derived from actual router implementations and policy_provider.py.
# Costs are intentionally NOT hardcoded here; use /v1/pricing/catalog for
# authoritative live STC costs.
# ---------------------------------------------------------------------------

_TOOLS = [
    # ---- Discovery / public ------------------------------------------------
    {
        "name": "ai_context",
        "title": "AI Context",
        "description": (
            "Returns dataset overview, endpoint groups, access model, and agent usage guidance. "
            "Recommended starting point for any agent interacting with the Stock Trends API."
        ),
        "endpoint": "/v1/ai/context",
        "method": "GET",
        "category": "discovery",
        "auth_required": False,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": [],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Dataset metadata, endpoint groups, auth model, and agent usage guidance.",
    },
    {
        "name": "ai_tools",
        "title": "AI Tools Manifest",
        "description": (
            "Returns this MCP-compatible tools manifest. "
            "Lists all discoverable tools, workflows, pricing model, and auth expectations."
        ),
        "endpoint": "/v1/ai/tools",
        "method": "GET",
        "category": "discovery",
        "auth_required": False,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": [],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "MCP tools manifest: tools, workflows, pricing, auth.",
    },
    {
        "name": "pricing_metadata",
        "title": "Pricing Metadata",
        "description": (
            "Returns machine-readable pricing metadata including supported payment methods, "
            "endpoint families, and agent identity guidance."
        ),
        "endpoint": "/v1/pricing",
        "method": "GET",
        "category": "pricing",
        "auth_required": False,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": [],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Pricing metadata: payment methods, endpoint families, agent headers.",
    },
    {
        "name": "pricing_catalog",
        "title": "Live Pricing Catalog",
        "description": (
            "Returns all active STC pricing rules from the pricing engine. "
            "Agents should call this at startup to build a local cost map before issuing data requests."
        ),
        "endpoint": "/v1/pricing/catalog",
        "method": "GET",
        "category": "pricing",
        "auth_required": False,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": [],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Live pricing rules: rule_name, cost_per_request (STC), access_type.",
    },
    {
        "name": "workflow_registry",
        "title": "Workflow Registry",
        "description": (
            "Returns the static workflow registry with live per-step STC costs resolved from "
            "api_pricing_rules. Use this to understand available multi-step workflows and their costs."
        ),
        "endpoint": "/v1/workflows",
        "method": "GET",
        "category": "discovery",
        "auth_required": False,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": [],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Workflow definitions with live per-step STC costs.",
    },
    # ---- Pricing / cost planning -------------------------------------------
    {
        "name": "cost_estimate",
        "title": "Workflow Cost Estimate",
        "description": (
            "Returns a deterministic cost estimate for a named workflow. "
            "Costs resolved from live pricing rules. Requires a valid API key. Non-metered."
        ),
        "endpoint": "/v1/cost-estimate",
        "method": "GET",
        "category": "pricing",
        "auth_required": True,
        "metered": False,
        "pricing_rule_id": None,
        "supported_rails": ["subscription"],
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "Workflow ID. See GET /v1/workflows for available IDs.",
                },
                "quota_remaining": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Caller's current subscription quota remaining (optional).",
                },
                "rail_preference": {
                    "type": "string",
                    "enum": ["subscription", "x402", "auto"],
                    "description": "Rail preference for cost assignment (default: auto).",
                },
            },
            "required": ["workflow_id"],
        },
        "output_summary": "Estimated total STC cost and per-step rail assignment for the workflow.",
    },
    # ---- Decision ----------------------------------------------------------
    {
        "name": "evaluate_symbol",
        "title": "Symbol Decision Evaluation",
        "description": (
            "Evaluates a single symbol's trend context against the live market regime to produce "
            "a synthesized bias, confidence score, and decision_score (0–1). "
            "Fully deterministic — no ML."
        ),
        "endpoint": "/v1/decision/evaluate-symbol",
        "method": "POST",
        "category": "decision",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "evaluate_symbol",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_exchange": {
                    "type": "string",
                    "description": "Combined symbol and exchange, e.g. 'AAPL-Q'.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol, e.g. 'AAPL'. Requires exchange when used alone.",
                },
                "exchange": {
                    "type": "string",
                    "description": "Exchange code, e.g. 'Q' (Nasdaq), 'N' (NYSE).",
                },
            },
            "required": [],
            "oneOf": [
                {"required": ["symbol_exchange"]},
                {"required": ["symbol", "exchange"]},
            ],
        },
        "output_summary": (
            "bias, confidence, decision_score (0–1), alignment, symbol_context, regime_context, signal_notes."
        ),
    },
    # ---- Market regime -----------------------------------------------------
    {
        "name": "market_regime_latest",
        "title": "Current Market Regime",
        "description": "Retrieves the current market regime classification.",
        "endpoint": "/v1/market/regime/latest",
        "method": "GET",
        "category": "market",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "market_regime_latest",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Current regime label, score, and classification metadata.",
    },
    {
        "name": "market_regime_history",
        "title": "Market Regime History",
        "description": "Retrieves historical regime sequence for context.",
        "endpoint": "/v1/market/regime/history",
        "method": "GET",
        "category": "market",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "market_regime_history",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Weekly regime classification history.",
    },
    {
        "name": "market_regime_forecast",
        "title": "Market Regime Forecast",
        "description": "Retrieves probabilistic forward regime forecast.",
        "endpoint": "/v1/market/regime/forecast",
        "method": "GET",
        "category": "market",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "market_regime_forecast",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_summary": "Forward regime probabilities and directional confidence.",
    },
    # ---- Screener ----------------------------------------------------------
    {
        "name": "screener_top",
        "title": "Agent Screener Top",
        "description": "Returns top qualifying tickers based on Stock Trends criteria. Ranked and ready for portfolio construction.",
        "endpoint": "/v1/agent/screener/top",
        "method": "GET",
        "category": "screener",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "agent_screener_top",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "description": "See /v1/openapi.json for full query parameter schema.",
        },
        "output_summary": "Ranked list of qualifying tickers with trend and scoring metadata.",
    },
    # ---- Portfolio ---------------------------------------------------------
    {
        "name": "portfolio_construct",
        "title": "Portfolio Construct",
        "description": "Constructs a portfolio from screened candidates using Stock Trends weighting logic.",
        "endpoint": "/v1/portfolio/construct",
        "method": "POST",
        "category": "portfolio",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "portfolio_construct",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "description": "See /v1/openapi.json for full request body schema.",
        },
        "output_summary": "Constructed portfolio with symbol weights and selection rationale.",
    },
    {
        "name": "portfolio_evaluate",
        "title": "Portfolio Evaluate",
        "description": "Evaluates risk and return profile of an existing or constructed portfolio.",
        "endpoint": "/v1/portfolio/evaluate",
        "method": "POST",
        "category": "portfolio",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "portfolio_evaluate",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "description": "See /v1/openapi.json for full request body schema.",
        },
        "output_summary": "Portfolio risk and return metrics.",
    },
    {
        "name": "portfolio_compare",
        "title": "Portfolio Compare",
        "description": "Compares two portfolios to quantify differences in risk and return profile.",
        "endpoint": "/v1/portfolio/compare",
        "method": "POST",
        "category": "portfolio",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "portfolio_compare",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "description": "See /v1/openapi.json for full request body schema.",
        },
        "output_summary": "Side-by-side comparison of two portfolios.",
    },
    # ---- STIM --------------------------------------------------------------
    {
        "name": "stim_latest",
        "title": "STIM Latest",
        "description": (
            "Retrieves the latest ST-IM (Stock Trends Indicator Model) distribution for a symbol. "
            "Covers forward return distributions across 4, 13, and 40-week horizons."
        ),
        "endpoint": "/v1/stim/latest",
        "method": "GET",
        "category": "stim",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "stc_metered",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_exchange": {
                    "type": "string",
                    "description": "Symbol and exchange, e.g. 'IBM-N'.",
                },
            },
            "required": ["symbol_exchange"],
        },
        "output_summary": "ST-IM forward return distributions for 4, 13, and 40-week horizons.",
    },
    {
        "name": "stim_history",
        "title": "STIM History",
        "description": "Retrieves historical ST-IM distribution records for a symbol.",
        "endpoint": "/v1/stim/history",
        "method": "GET",
        "category": "stim",
        "auth_required": True,
        "metered": True,
        "pricing_rule_id": "stc_metered",
        "supported_rails": ["subscription", "x402", "mpp"],
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_exchange": {
                    "type": "string",
                    "description": "Symbol and exchange, e.g. 'IBM-N'.",
                },
            },
            "required": ["symbol_exchange"],
        },
        "output_summary": "Historical ST-IM distribution records.",
    },
]


def _build_workflow_summary(workflow: dict) -> dict:
    """Return a simplified MCP-friendly workflow entry from the registry."""
    return {
        "workflow_id": workflow["workflow_id"],
        "name": workflow["name"],
        "description": workflow["description"],
        "tags": workflow["tags"],
        "supported_rails": workflow["supported_rails"],
        "step_count": len(workflow["steps"]),
        "pricing_rule_ids": [step["pricing_rule_id"] for step in workflow["steps"]],
        "note": "Use GET /v1/workflows for live per-step STC costs.",
    }


def get_last_update():
    """
    Returns the most recent weekdate from st_data.
    Falls back to None if the query fails.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT MAX(weekdate) AS last_update FROM st_data"))
            row = result.fetchone()

        if row and row.last_update:
            return str(row.last_update)
    except Exception:
        return None

    return None


@router.get("/context")
def ai_context():
    last_update = get_last_update()

    return {
        "dataset": "Stock Trends Market Indicators",
        "provider": "Stock Trends Publications",
        "description": "Weekly structured market intelligence dataset covering North American equities and ETFs, including Stock Trends trend classification, momentum, relative strength, unusual volume, breadth, leadership, ST-IM forward return distributions, market regime analytics, and deterministic decision/portfolio workflows.",
        "update_frequency": "weekly",
        "last_update": last_update,
        "coverage": {
            "region": "North America",
            "asset_types": ["equities", "ETFs"],
            "forecast_horizons_weeks": [4, 13, 40]
        },
        "core_indicators": [
            "trend",
            "trend_cnt",
            "mt_cnt",
            "rsi",
            "rsi_updn",
            "vol_tag"
        ],
        "field_definitions": {
            "trend": "Primary Stock Trends trend classification for the instrument.",
            "trend_cnt": "Number of consecutive weeks the current trend classification has persisted.",
            "mt_cnt": "Number of weeks the instrument has remained in its current major trend category.",
            "rsi": "Relative strength measure versus the relevant market benchmark.",
            "rsi_updn": "Weekly direction of relative strength versus benchmark.",
            "vol_tag": "Unusual volume classification for the current week."
        },
        "trend_categories": {
            "^+": "bullish",
            "^-": "weak bullish",
            "v^": "bullish crossover",
            "v-": "bearish",
            "v+": "weak bearish",
            "^v": "bearish crossover"
        },
        "endpoint_groups": {
            "discovery": [
                "/v1/ai/context",
                "/v1/docs",
                "/v1/openapi.json"
            ],
            "pricing": [
                "/v1/pricing",
                "/v1/pricing/catalog",
                "/v1/workflows",
                "/v1/cost-estimate"
            ],
            "instruments": [
                "/v1/instruments/lookup",
                "/v1/instruments/resolve"
            ],
            "screening": [
                "/v1/agent/screener/top"
            ],
            "stim": [
                "/v1/stim/latest",
                "/v1/stim/history"
            ],
            "market": [
                "/v1/market/regime/latest",
                "/v1/market/regime/history",
                "/v1/market/regime/forecast"
            ],
            "decision": [
                "/v1/decision/evaluate-symbol"
            ],
            "portfolio": [
                "/v1/portfolio/construct",
                "/v1/portfolio/evaluate",
                "/v1/portfolio/compare"
            ],
            "breadth": [
                "/v1/breadth/sector/latest",
                "/v1/breadth/sector/history"
            ],
            "leadership": [
                "/v1/leadership/definitions",
                "/v1/leadership/summary/latest",
                "/v1/leadership/rotation/history"
            ],
            "selections": [
                "/v1/selections/latest",
                "/v1/selections/history",
                "/v1/selections/published/latest",
                "/v1/selections/published/history"
            ]
        },
        "access_model": {
            "public_discovery": [
                "/v1/ai/context",
                "/v1/docs",
                "/v1/openapi.json"
            ],
            "subscription_supported": True,
            "x402_agent_pay": "live",
            "mpp": "live"
        },
        "auth": {
            "subscription_scheme": "X-API-Key",
            "subscription_header": "X-API-Key: YOUR_API_KEY",
            "alternative_scheme": "Bearer",
            "alternative_header": "Authorization: Bearer YOUR_API_KEY",
            "agent_identity_headers": [
                "X-StockTrends-Agent-Id",
                "X-StockTrends-Agent-Type",
                "X-StockTrends-Agent-Vendor",
                "X-StockTrends-Agent-Version"
            ],
            "payment_headers": [
                "X-StockTrends-Payment-Method",
                "X-StockTrends-Payment-Network",
                "X-StockTrends-Payment-Token",
                "X-StockTrends-Payment-Reference",
                "X-StockTrends-Payment-Amount"
            ]
        },
        "pricing": {
            "catalog_endpoint": "/v1/pricing/catalog",
            "pricing_metadata_endpoint": "/v1/pricing",
            "workflow_registry_endpoint": "/v1/workflows",
            "cost_estimate_endpoint": "/v1/cost-estimate",
            "note": "Use the live pricing catalog and API response headers as the authoritative source of endpoint pricing and payment requirements."
        },
        "usage_guidance": [
            "Start with /v1/ai/context to understand the dataset and endpoint families.",
            "Use /v1/docs and /v1/openapi.json for exact request and response contracts.",
            "Use /v1/pricing/catalog to discover live pricing rules before calling premium endpoints.",
            "Use subscription access for persistent developer workflows and x402 for agent-native pay-per-request access.",
            "Start premium agent-pay workflows with /v1/agent/screener/top or /v1/stim/latest.",
            "Cache discovery and metadata responses where appropriate because the dataset updates weekly."
        ],
        "example_queries": [
            {
                "description": "Look up an instrument by symbol",
                "path": "/v1/instruments/lookup?symbol=AAPL"
            },
            {
                "description": "Get a premium ranked screener result set",
                "path": "/v1/agent/screener/top"
            },
            {
                "description": "Retrieve the latest ST-IM distribution for one symbol",
                "path": "/v1/stim/latest?symbol_exchange=IBM-N"
            },
            {
                "description": "Retrieve the current market regime classification",
                "path": "/v1/market/regime/latest"
            }
        ],
        "recommended_first_flows": {
            "human_developer": [
                "/v1/docs",
                "/v1/openapi.json",
                "/v1/pricing/catalog",
                "/v1/stim/latest?symbol_exchange=IBM-N"
            ],
            "agent": [
                "/v1/ai/context",
                "/v1/pricing/catalog",
                "/v1/agent/screener/top"
            ]
        },
        "docs": "https://api.stocktrends.com/v1/docs",
        "openapi": "https://api.stocktrends.com/v1/openapi.json",
        "llms_txt": "https://api.stocktrends.com/llms.txt",
        "ai_plugin": "https://api.stocktrends.com/.well-known/ai-plugin.json",
        "dataset_manifest": "https://api.stocktrends.com/ai-dataset.json",
        "tools_manifest": "https://api.stocktrends.com/tools.json",
        "license": "https://stocktrends.com/stock-trends-data-license",
        "terms": "https://stocktrends.com/terms-of-use",
        "support": {
            "email": "api@stocktrends.com"
        }
    }


# ---------------------------------------------------------------------------
# GET /v1/ai/tools — MCP/Bazaar-compatible tools manifest
# Public, non-metered, fully static (no DB calls).
# Exposes real endpoints only. Pricing costs are NOT hardcoded here;
# agents should call /v1/pricing/catalog for authoritative live STC costs.
# ---------------------------------------------------------------------------

@router.get(
    "/tools",
    summary="MCP tools manifest",
    description=(
        "Public, non-metered. Returns the Stock Trends API as an MCP/Bazaar-compatible "
        "tools manifest. Exposes confirmed real endpoints only. Costs reference the STC "
        "model; use /v1/pricing/catalog for authoritative live values. "
        "Workflows are exposed in a simplified format; use /v1/workflows for live per-step costs."
    ),
)
def ai_tools():
    workflows = [_build_workflow_summary(w) for w in WORKFLOW_REGISTRY]

    return {
        "provider": "stocktrends",
        "version": "v1",
        "tools": _TOOLS,
        "workflows": workflows,
        "pricing": {
            "unit": "STC",
            "unit_description": "Stock Trends Credits. 1 STC ≈ $1 USD (reference value, not a fixed peg).",
            "model": "All endpoints price in STC. Payment rails convert value to STC.",
            "catalog_endpoint": "/v1/pricing/catalog",
            "cost_estimate_endpoint": "/v1/cost-estimate",
            "note": (
                "STC costs are dynamic and resolved from api_pricing_rules. "
                "Do not hardcode costs — always fetch /v1/pricing/catalog at agent startup."
            ),
        },
        "auth": {
            "modes": [
                {
                    "mode": "subscription",
                    "description": "API key with active subscription. Provides monthly STC allocation.",
                    "headers": {
                        "primary": "X-API-Key: YOUR_API_KEY",
                        "alternative": "Authorization: Bearer YOUR_API_KEY",
                    },
                },
                {
                    "mode": "x402",
                    "description": "Per-request agent payment via HTTP 402 challenge/verify flow.",
                    "headers": {
                        "X-StockTrends-Payment-Method": "x402",
                        "X-StockTrends-Payment-Network": "base",
                        "X-StockTrends-Payment-Token": "USDC",
                        "X-StockTrends-Payment-Reference": "<reference>",
                        "X-StockTrends-Payment-Amount": "<amount>",
                    },
                },
                {
                    "mode": "mpp",
                    "description": "Session-based payments. STC consumed within an active payment session.",
                    "headers": {
                        "X-StockTrends-Payment-Method": "mpp",
                        "X-StockTrends-Session-Id": "<session_id>",
                    },
                },
            ],
            "agent_identity_headers": {
                "X-StockTrends-Agent-Id": "Stable external agent identifier (required for agent attribution).",
                "X-StockTrends-Agent-Type": "Agent category, e.g. 'editorial'.",
                "X-StockTrends-Agent-Vendor": "Vendor or platform operating the agent.",
                "X-StockTrends-Agent-Version": "Agent software version.",
                "X-StockTrends-Request-Purpose": "Optional statement of request purpose.",
                "X-StockTrends-Session-Id": "Optional session/workflow correlation ID.",
            },
        },
        "notes": [
            "All metered endpoints price in STC. Fetch /v1/pricing/catalog at agent startup.",
            "Use /v1/workflows for multi-step workflows with live per-step STC costs.",
            "Use /v1/cost-estimate to plan STC spend before executing a workflow.",
            "Start with /v1/ai/context for a full dataset and endpoint overview.",
            "See /v1/docs and /v1/openapi.json for exact request/response contracts.",
        ],
    }
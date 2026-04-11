from fastapi import APIRouter
from sqlalchemy import text
from db import get_engine

router = APIRouter(prefix="/ai", tags=["ai"])


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
            "mpp": "coming_soon"
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
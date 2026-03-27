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
        "description": "Weekly structured dataset covering North American equities and ETFs with Stock Trends trend classification, momentum, relative strength, unusual volume, breadth, selections, leadership, and probabilistic forward return analysis.",
        "update_frequency": "weekly",
        "last_update": last_update,
        "coverage": {
            "region": "North America",
            "asset_types": ["equities", "ETFs"],
            "forecast_horizons_weeks": [4, 13, 40]
        },
        "indicators": [
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
            "ai": [
                "/v1/ai/context"
            ],
            "instruments": [
                "/v1/instruments/lookup"
            ],
            "breadth": [
                "/v1/breadth/sector/latest"
            ],
            "stim": [
                "/v1/stim/top"
            ],
            "selections": [
                "/v1/selections/latest",
                "/v1/selections-published/latest"
            ],
            "leadership": [
                "/v1/leadership/summary/latest"
            ]
        },
        "auth": {
            "primary_scheme": "X-API-Key",
            "primary_header": "X-API-Key: YOUR_API_KEY",
            "alternative_scheme": "Bearer",
            "alternative_header": "Authorization: Bearer YOUR_API_KEY",
            "required_for_protected_endpoints": True
        },
        "pricing": {
            "public_endpoints": "available",
            "free_metered_endpoints": "usage tracked",
            "protected_endpoints": "subscription required",
            "pricing_url": "https://api.stocktrends.com/v1/pricing"
        },
        "usage_guidance": [
            "Start with /v1/ai/context to understand dataset structure and terminology.",
            "Use the OpenAPI specification for exact parameters and response shapes.",
            "Authentication is primarily via X-API-Key. Bearer token authentication is also supported as an alternative.",
            "Prefer structured API access over scraping website pages.",
            "Cache responses where appropriate because the dataset updates weekly."
        ],
        "example_queries": [
            {
                "description": "Look up an instrument by symbol",
                "path": "/v1/instruments/lookup?symbol=AAPL"
            },
            {
                "description": "Retrieve top STIM results",
                "path": "/v1/stim/top"
            },
            {
                "description": "Retrieve latest sector breadth",
                "path": "/v1/breadth/sector/latest"
            }
        ],
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
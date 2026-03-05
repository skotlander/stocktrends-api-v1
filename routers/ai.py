from fastapi import APIRouter
from datetime import date

router = APIRouter(prefix="/v1/ai", tags=["ai"])


@router.get("/context")
def ai_context():
    return {
        "dataset": "Stock Trends Market Indicators",
        "provider": "Stock Trends Publications",
        "update_frequency": "weekly",
        "last_update": str(date.today()),

        "indicators": [
            "trend",
            "trend_cnt",
            "mt_cnt",
            "rsi",
            "rsi_updn",
            "vol_tag"
        ],

        "trend_categories": [
            "^+ bullish",
            "^- weak bullish",
            "v^ bullish crossover",
            "v- bearish",
            "v+ weak bearish",
            "^v bearish crossover"
        ],

        "description": "Weekly dataset covering North American equities and ETFs with trend classification, momentum, and breadth indicators.",

        "example_queries": [
            "/v1/instruments/lookup?symbol=AAPL",
            "/v1/instruments/lookup?symbol=NVDA",
            "/v1/stim/top",
            "/v1/breadth/sectors"
        ],

        "docs": "https://api.stocktrends.com/docs",
        "openapi": "https://api.stocktrends.com/v1/openapi.json"
    }
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
        "update_frequency": "weekly",
        "last_update": last_update,
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
            "/v1/stim/top",
            "/v1/breadth/sector/latest"
        ],
        "docs": "https://api.stocktrends.com/v1/docs",
        "openapi": "https://api.stocktrends.com/v1/openapi.json"
    }
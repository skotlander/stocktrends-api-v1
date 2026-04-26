# discovery/preview.py
#
# Static, per-endpoint preview snippets surfaced in x402 challenge responses
# under the "stocktrends_preview" key.  Content is schema-level only — no
# live data, no STC costs, no real tickers.  All values are illustrative.
#
# Rules (enforced by tests):
#   - No imports from db, routers, payments, or pricing packages.
#   - Each call to get_endpoint_preview() returns a deep copy so callers
#     cannot mutate the registry (including nested lists/dicts).
#   - Returns None for unknown paths; callers must omit the key in that case.

import copy

_PREVIEW_BY_PATH: dict[str, dict] = {
    "/v1/agent/screener/top": {
        "response_shape": [
            "request_id", "screener", "weekdate", "filter_summary",
            "count", "total_matched",
            "results[].rank", "results[].symbol", "results[].exchange",
            "results[].symbol_exchange", "results[].trend", "results[].trend_cnt",
            "results[].mt_cnt", "results[].rsi", "results[].rsi_updn",
            "results[].vol_tag", "results[].weekdate",
        ],
        "note": (
            "Returns ranked instruments with trend, momentum (mt_cnt), RSI, and "
            "volume-tag fields per result row. "
            "See /v1/ai/proof/market-edge for a static structural example."
        ),
    },
    "/v1/stim/latest": {
        "response_shape": [
            "request_id", "symbol_exchange", "weekdate", "exchange", "symbol",
            "x4wk1", "x4wk2", "x4wk", "x4wksd",
            "x13wk1", "x13wk2", "x13wk", "x13wksd",
            "x40wk1", "x40wk2", "x40wk", "x40wksd",
            "latest_data_weekdate", "is_stale", "missing_reason", "missing_weekdate",
        ],
        "note": (
            "Returns Stock Trends Inference Model (ST-IM) outputs: forward return "
            "expectations and statistical distributions across 4-week, 13-week, "
            "and 40-week horizons for a given symbol/exchange."
        ),
    },
    "/v1/stim/history": {
        "response_shape": [
            "request_id", "symbol_exchange", "start", "end",
            "count", "data", "include_gaps", "gaps",
        ],
        "note": "Returns a historical series of ST-IM records for a given symbol/exchange.",
    },
    "/v1/decision/evaluate-symbol": {
        "response_shape": [
            "request_id", "symbol", "exchange", "weekdate",
            "bias", "confidence", "decision_score", "alignment",
            "symbol_context.trend", "symbol_context.trend_cnt", "symbol_context.mt_cnt",
            "symbol_context.rsi", "symbol_context.rsi_updn", "symbol_context.vol_tag",
            "symbol_context.symbol_bias",
            "regime_context.current_regime", "regime_context.regime_score",
            "regime_context.regime_confidence", "regime_context.forecast_regime",
            "regime_context.forecast_confidence", "regime_context.recent_direction",
            "regime_context.regime_consistency", "regime_context.weeks_analyzed",
            "signal_notes",
        ],
        "note": (
            "Returns a structured buy/hold/sell decision (bias) with confidence, "
            "per-symbol signal context, and market regime context."
        ),
    },
    "/v1/portfolio/construct": {
        "response_shape": [
            "request_id", "weekdate",
            "portfolio[].rank", "portfolio[].weight", "portfolio[].symbol",
            "portfolio[].exchange", "portfolio[].symbol_exchange",
            "portfolio[].trend", "portfolio[].trend_cnt", "portfolio[].mt_cnt",
            "portfolio[].rsi", "portfolio[].bias", "portfolio[].confidence",
            "portfolio[].decision_score",
            "count", "candidates_evaluated", "portfolio_score",
            "bias_requested", "bias_resolved",
            "regime_context.current_regime", "regime_context.regime_score",
            "regime_context.forecast_regime", "regime_context.forecast_confidence",
            "construction_notes",
        ],
        "note": (
            "Returns a constructed portfolio allocation with per-position weights, "
            "signal fields, and market regime context."
        ),
    },
}


def get_endpoint_preview(path: str) -> dict | None:
    """Return a deep copy of the preview for *path*, or None if none exists."""
    entry = _PREVIEW_BY_PATH.get(path)
    if entry is None:
        return None
    return copy.deepcopy(entry)

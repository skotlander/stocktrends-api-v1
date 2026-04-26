# discovery/preview.py
#
# Static, per-endpoint preview snippets surfaced in x402 challenge responses
# under the "stocktrends_preview" key.  Content is schema-level only — no
# live data, no STC costs, no real tickers.  All values are illustrative.
#
# Rules (enforced by tests):
#   - No imports from db, routers, payments, or pricing packages.
#   - Each call to get_endpoint_preview() returns a shallow copy so callers
#     cannot mutate the registry.
#   - Returns None for unknown paths; callers must omit the key in that case.

_PREVIEW_BY_PATH: dict[str, dict] = {
    "/v1/agent/screener/top": {
        "response_shape": [
            "symbol", "signal", "momentum_score", "rank",
            "sector", "as_of", "timeframe",
        ],
        "signal_labels": ["strong_uptrend", "uptrend", "neutral", "downtrend", "strong_downtrend"],
        "note": (
            "Returns ranked instruments with momentum scores and signal labels. "
            "See /v1/ai/proof/market-edge for a static structural example."
        ),
    },
    "/v1/stim/latest": {
        "response_shape": ["regime", "breadth_signal", "stim_score", "as_of", "direction"],
        "note": "Returns current market regime and STIM signal score.",
    },
    "/v1/stim/history": {
        "response_shape": ["date", "regime", "stim_score", "direction"],
        "note": "Returns historical STIM regime data series.",
    },
    "/v1/decision/evaluate-symbol": {
        "response_shape": [
            "symbol", "decision", "confidence", "signals",
            "momentum_score", "regime_context",
        ],
        "note": "Returns a structured buy/hold/sell decision with supporting signal context.",
    },
    "/v1/portfolio/construct": {
        "response_shape": [
            "positions", "total_weight", "regime_context",
            "construction_method", "as_of",
        ],
        "note": "Returns a constructed portfolio allocation from signal inputs.",
    },
    "/v1/market/pulse": {
        "response_shape": ["breadth", "regime", "momentum_index", "sector_leaders", "as_of"],
        "note": "Returns a broad market pulse summary across breadth and regime dimensions.",
    },
}


def get_endpoint_preview(path: str) -> dict | None:
    """Return a shallow copy of the preview for *path*, or None if none exists."""
    entry = _PREVIEW_BY_PATH.get(path)
    if entry is None:
        return None
    return dict(entry)

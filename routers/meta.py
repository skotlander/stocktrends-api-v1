# routers/meta.py

from __future__ import annotations

from fastapi import APIRouter, Request

from routers.signals import VALID_EXCHANGES

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/indicators")
def meta_indicators(request: Request):
    """
    Canonical definitions for Stock Trends fields used across endpoints.
    Intended for bots/agents so they don't need to scrape the website.
    """
    return {
        "request_id": getattr(request.state, "request_id", None),
        "exchanges": {
            "allowed": sorted(list(VALID_EXCHANGES)),
            "meaning": {
                "T": "Toronto Stock Exchange (TSX)",
                "N": "New York Stock Exchange (NYSE)",
                "Q": "NASDAQ",
                "A": "AMEX",
                "B": "Other/alternate US listing bucket (if used in your DB)",
                "I": "Index/indicator bucket (if used in your DB)",
            },
            "note": "Exact exchange meanings can be customized to your production mapping.",
        },
        "fields": {
            "trend": {
                "type": "enum",
                "allowed": ["^+", "^-", "v^", "v+", "v-", "^v", "--", "="],
                "meaning": {
                    "^+": "Bullish (strong bullish trend)",
                    "^-": "Weak Bullish (bullish but weakening; often precedes bearish crossover)",
                    "v^": "Bullish Crossover (13wk MA crosses above 40wk MA)",
                    "v+": "Weak Bearish (bearish but recovering; often precedes bullish crossover)",
                    "v-": "Bearish (strong bearish trend)",
                    "^v": "Bearish Crossover (13wk MA crosses below 40wk MA)",
                    "--": "No trend / not classified",
                    "=": "Neutral / unchanged (if used)",
                },
                "note": "Trend is derived from price vs 13wk and 40wk moving averages per Stock Trends methodology.",
            },
            "trend_cnt": {
                "type": "int",
                "meaning": "Number of consecutive weeks the instrument has had the current trend code.",
            },
            "mt_cnt": {
                "type": "int",
                "meaning": "Number of consecutive weeks in the current major trend category (Bullish bucket vs Bearish bucket).",
                "bullish_bucket": ["^+", "^-", "v^"],
                "bearish_bucket": ["v-", "v+", "^v"],
            },
            "prev_mtcnt": {
                "type": "int",
                "meaning": "Previous week's mt_cnt (primarily meaningful on crossover weeks when mt_cnt resets).",
            },
            "rsi": {
                "type": "int",
                "meaning": "13-week relative strength index vs benchmark (S&P 500) where >100 implies outperformance.",
            },
            "rsi_updn": {
                "type": "enum",
                "allowed": ["+", "-", "0", ""],
                "meaning": {
                    "+": "Outperformed benchmark this week",
                    "-": "Underperformed benchmark this week",
                    "0": "Roughly flat vs benchmark this week",
                    "": "Not available / missing",
                },
            },
            "vol_tag": {
                "type": "enum",
                "allowed": ["", "!", "!!", "*", "**", "~"],
                "meaning": {
                    "": "No volume tag / normal",
                    "!": "Unusually low volume (low)",
                    "!!": "Unusually low volume (very low) — treated as low",
                    "*": "Unusually high volume (high)",
                    "**": "Unusually high volume (very high) — treated as high",
                    "~": "Special/other tag (if used in your dataset)",
                },
                "equivalences": {
                    "low": ["!", "!!"],
                    "high": ["*", "**"],
                },
            },
            "fpr_chg4/13/40": {
                "type": "float",
                "meaning": "Forward price return (%) after subsequent 4/13/40-week periods (historical realized).",
                "note": "Used for evaluating ST-IM distributions; may be NULL where forward window not available.",
            },
        },
        "links": {
            "human_guides": [
                "https://stocktrends.com/learn/stock-trends-guides",
                "https://stocktrends.com/component/strategy/stdata_layout",
            ],
            "machine_guides": [
                "/v1/openapi.json",
                "/v1/meta/indicators",
            ],
        },
    }


@router.get("/stim")
def meta_stim(request: Request):
    """
    ST-IM distribution metadata and base period mean returns.
    """
    return {
        "request_id": getattr(request.state, "request_id", None),
        "base_period_mean_returns_pct": {
            "x4wk": 0.00,
            "x13wk": 2.19,
            "x40wk": 6.45,
        },
        "returnmeans_table": "st_returnmeans",
        "columns": {
            "x4wk1/x13wk1/x40wk1": "Lower confidence interval bound for mean return (%)",
            "x4wk2/x13wk2/x40wk2": "Upper confidence interval bound for mean return (%)",
            "x4wk/x13wk/x40wk": "Midpoint / mean estimate (%)",
            "x4wksd/x13wksd/x40wksd": "Std dev of assumed normal distribution (%)",
        },
        "missing_data_note": "If a symbol has no row for a weekdate in st_returnmeans, ST-IM could not estimate reliably due to insufficient samples.",
    }


@router.get("/stwr")
def meta_stwr(request: Request):
    """
    Report codes and what each report generally represents.
    """
    return {
        "request_id": getattr(request.state, "request_id", None),
        "endpoint_family": "/v1/stwr/reports/latest and /v1/stwr/reports/history",
        "reports": [
            {"code": "pw", "name": "Picks of the Week", "hint": "Bullish xover or weak bearish + RSI+/volume rules"},
            {"code": "select", "name": "ST-IM Select stocks of the Week", "hint": "Published select = st_select filtered by returnmeans CI rules"},
            {"code": "toptrend", "name": "Top Trending", "hint": "Bullish bucket + momentum filters"},
            {"code": "bullcross", "name": "Bullish Crossovers", "hint": "trend=v^"},
            {"code": "bearcross", "name": "Bearish Crossovers", "hint": "trend=^v"},
            # You can expand this list as you add report builders
        ],
        "note": "This is summary metadata; the authoritative logic lives in the report SQL builders.",
    }
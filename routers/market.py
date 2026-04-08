# routers/market.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from db import get_engine

router = APIRouter(prefix="/market", tags=["market"])

_BULLISH_TRENDS = {"^+", "^-", "v^"}
_BEARISH_TRENDS = {"v-", "v+", "^v"}


def _classify_regime(regime_score: float) -> str:
    if regime_score >= 0.10:
        return "bullish"
    if regime_score <= -0.10:
        return "bearish"
    return "mixed"


def _classify_confidence(regime_score: float) -> str:
    abs_score = abs(regime_score)
    if abs_score >= 0.30:
        return "high"
    if abs_score >= 0.10:
        return "moderate"
    return "low"


@router.get(
    "/regime/latest",
    summary="Current market regime classification",
    description=(
        "Returns a synthesized market regime based on the distribution of Stock Trends "
        "trend codes across all active signals in the latest available week. "
        "Bullish = {^+, ^-, v^}. Bearish = {v-, v+, ^v}. "
        "regime_score = bullish_pct - bearish_pct, range -1 to +1. "
        "Pricing rule: market_regime_latest (0.15 STC per call)."
    ),
)
def market_regime_latest(request: Request):
    engine = get_engine()

    with engine.connect() as conn:
        # Step 1: resolve latest weekdate
        row = conn.execute(
            text("SELECT MAX(weekdate) AS weekdate FROM st_data")
        ).mappings().first()
        weekdate = str(row["weekdate"]) if row and row["weekdate"] else None

        if not weekdate:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": getattr(request.state, "request_id", None),
                    "error": "no_signal_data",
                    "message": "No weekdate available in st_signals_latest.",
                },
            )

        # Step 2: aggregate trend distribution for that weekdate
        rows = conn.execute(
            text(
                """
                SELECT
                    trend,
                    COUNT(*)    AS cnt,
                    AVG(rsi)    AS avg_rsi,
                    AVG(mt_cnt) AS avg_mt_cnt
                FROM st_data
                WHERE weekdate = :weekdate
                  AND type = 'CS'
                GROUP BY trend
                """
            ),
            {"weekdate": weekdate},
        ).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail={
                "request_id": getattr(request.state, "request_id", None),
                "error": "no_signal_data",
                "message": "No signals found for the latest weekdate.",
            },
        )

    bullish_cnt = 0
    bearish_cnt = 0
    total_cnt = 0
    weighted_rsi = 0.0
    weighted_mt_cnt = 0.0

    for row in rows:
        cnt = int(row["cnt"] or 0)
        trend = row["trend"] or ""
        total_cnt += cnt
        if trend in _BULLISH_TRENDS:
            bullish_cnt += cnt
        elif trend in _BEARISH_TRENDS:
            bearish_cnt += cnt
        weighted_rsi += float(row["avg_rsi"] or 0) * cnt
        weighted_mt_cnt += float(row["avg_mt_cnt"] or 0) * cnt

    if total_cnt == 0:
        raise HTTPException(
            status_code=503,
            detail={
                "request_id": getattr(request.state, "request_id", None),
                "error": "no_signal_data",
                "message": "Signal count is zero for the latest weekdate.",
            },
        )

    bullish_pct = round(bullish_cnt / total_cnt, 4)
    bearish_pct = round(bearish_cnt / total_cnt, 4)
    regime_score = round(bullish_pct - bearish_pct, 4)
    avg_rsi = round(weighted_rsi / total_cnt, 2)
    avg_mt_cnt = round(weighted_mt_cnt / total_cnt, 2)

    return {
        "regime": _classify_regime(regime_score),
        "confidence": _classify_confidence(regime_score),
        "regime_score": regime_score,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "avg_rsi": avg_rsi,
        "avg_mt_cnt": avg_mt_cnt,
        "weekdate": weekdate,
        "signal_count": total_cnt,
    }

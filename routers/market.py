# routers/market.py

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
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


@router.get(
    "/regime/history",
    summary="Historical weekly market regime classification",
    description=(
        "Returns a list of weekly market regime snapshots computed from the distribution "
        "of Stock Trends trend codes for each week. "
        "Same classification logic as /regime/latest. "
        "Bullish = {^+, ^-, v^}. Bearish = {v-, v+, ^v}. "
        "Pricing rule: market_regime_history (0.25 STC per call)."
    ),
)
def market_regime_history(
    request: Request,
    limit: int = Query(
        default=12,
        ge=1,
        le=52,
        description="Number of weekly periods to return. Default 12, max 52.",
    ),
    start_date: date | None = Query(
        default=None,
        description="Optional earliest weekdate to include (YYYY-MM-DD).",
    ),
):
    engine = get_engine()

    with engine.connect() as conn:
        # Step 1: resolve weekdates within scope
        # Two explicit fixed queries — no dynamic SQL assembly
        if start_date is not None:
            weekdate_rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT weekdate
                    FROM st_data
                    WHERE type = 'CS'
                      AND weekdate >= :start_date
                    ORDER BY weekdate DESC
                    LIMIT :limit
                    """
                ),
                {"start_date": start_date, "limit": limit},
            ).mappings().all()
        else:
            weekdate_rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT weekdate
                    FROM st_data
                    WHERE type = 'CS'
                    ORDER BY weekdate DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()

        weekdates = [r["weekdate"] for r in weekdate_rows if r["weekdate"]]

        if not weekdates:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": getattr(request.state, "request_id", None),
                    "error": "no_signal_data",
                    "message": "No weekdates available in st_data.",
                },
            )

        # Step 2: aggregate trend distribution for all resolved weekdates
        # Placeholders built from DB-returned date objects — no user input in SQL
        week_binds = {f"w{i}": wd for i, wd in enumerate(weekdates)}
        placeholders = ", ".join(f":w{i}" for i in range(len(weekdates)))
        agg_rows = conn.execute(
            text(
                f"""
                SELECT
                    weekdate,
                    trend,
                    COUNT(*)    AS cnt,
                    AVG(rsi)    AS avg_rsi,
                    AVG(mt_cnt) AS avg_mt_cnt
                FROM st_data
                WHERE weekdate IN ({placeholders})
                  AND type = 'CS'
                GROUP BY weekdate, trend
                ORDER BY weekdate DESC, trend
                """
            ),
            week_binds,
        ).mappings().all()

    # Group by weekdate (date objects as keys) and compute regime per week
    week_groups: dict[date, list] = defaultdict(list)
    for row in agg_rows:
        week_groups[row["weekdate"]].append(row)

    history = []
    for wd in weekdates:
        group = week_groups.get(wd, [])
        if not group:
            continue

        bullish_cnt = 0
        bearish_cnt = 0
        total_cnt = 0
        weighted_rsi = 0.0
        weighted_mt_cnt = 0.0

        for row in group:
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
            continue

        bullish_pct = round(bullish_cnt / total_cnt, 4)
        bearish_pct = round(bearish_cnt / total_cnt, 4)
        regime_score = round(bullish_pct - bearish_pct, 4)

        history.append({
            "weekdate": str(wd),
            "regime": _classify_regime(regime_score),
            "confidence": _classify_confidence(regime_score),
            "regime_score": regime_score,
            "bullish_pct": bullish_pct,
            "bearish_pct": bearish_pct,
            "avg_rsi": round(weighted_rsi / total_cnt, 2),
            "avg_mt_cnt": round(weighted_mt_cnt / total_cnt, 2),
            "signal_count": total_cnt,
        })

    return {
        "history": history,
        "count": len(history),
        "limit": limit,
        "start_date": str(start_date) if start_date else None,
    }

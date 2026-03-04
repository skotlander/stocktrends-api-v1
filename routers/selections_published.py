# routers/selections_published.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from db import get_engine

from routers.signals import VALID_EXCHANGES

router = APIRouter(prefix="/selections/published", tags=["selections"])


def _norm_exchange(ex: str) -> str:
    ex = ex.strip().upper()
    if ex not in VALID_EXCHANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid exchange '{ex}'. Must be one of {sorted(VALID_EXCHANGES)}",
        )
    return ex


@router.get("/latest")
def published_selections_latest(
    request: Request,
    exchange: str | None = Query(default=None, description="Optional exchange filter: N,Q,A,B,T,I"),
    min_prob13wk: float = Query(default=0.55, ge=0.0, le=1.0, description="Minimum prob13wk threshold"),
    base4wk: float = Query(default=0.00, description="Base period mean return for 4-week"),
    base13wk: float = Query(default=2.19, description="Base period mean return for 13-week"),
    base40wk: float = Query(default=6.45, description="Base period mean return for 40-week"),
    limit: int = Query(default=2000, ge=1, le=20000, description="Safety limit"),
    include_data: bool = Query(default=False, description="Join st_data for context fields"),
    cs_only: bool = Query(default=True, description="When include_data=true, filter st_data to CS"),
):
    ex = _norm_exchange(exchange) if exchange else None
    engine = get_engine()

    sql_latest_week = text("SELECT MAX(weekdate) AS weekdate FROM st_select")

    try:
        with engine.connect() as conn:
            latest = conn.execute(sql_latest_week).mappings().first()
            latest_week = latest["weekdate"] if latest else None
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request.state.request_id, "error": "db_query_failed", "message": str(e)},
        )

    if not latest_week:
        raise HTTPException(
            status_code=404,
            detail={"request_id": request.state.request_id, "error": "no_selection_data"},
        )

    params: dict = {
        "weekdate": latest_week,
        "limit": limit,
        "min_prob13wk": float(min_prob13wk),
        "base4wk": float(base4wk),
        "base13wk": float(base13wk),
        "base40wk": float(base40wk),
    }

    where = """
        WHERE s.weekdate = :weekdate
          AND s.prob13wk >= :min_prob13wk
          AND m.x4wk1  > :base4wk
          AND m.x13wk1 > :base13wk
          AND m.x40wk1 > :base40wk
    """

    if ex:
        where += " AND s.exchange = :exchange"
        params["exchange"] = ex

    if not include_data:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk,
                m.x4wk1,  m.x4wk2,  m.x4wk,  m.x4wksd,
                m.x13wk1, m.x13wk2, m.x13wk, m.x13wksd,
                m.x40wk1, m.x40wk2, m.x40wk, m.x40wksd
            FROM st_select s
            INNER JOIN st_returnmeans m
              ON m.weekdate = s.weekdate
             AND m.exchange = s.exchange
             AND m.symbol = s.symbol
            {where}
            ORDER BY s.prob13wk DESC
            LIMIT :limit
        """)
    else:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk,
                m.x4wk1,  m.x4wk2,  m.x4wk,  m.x4wksd,
                m.x13wk1, m.x13wk2, m.x13wk, m.x13wksd,
                m.x40wk1, m.x40wk2, m.x40wk, m.x40wksd,
                d.type,
                d.currency_code,
                d.fullname,
                d.shortname,
                d.industry_id,
                d.trend,
                d.trend_cnt,
                d.mt_cnt,
                d.rsi,
                d.rsi_updn,
                d.vol_tag,
                d.price,
                d.adj_close,
                d.pr_change,
                d.pr_chg13
            FROM st_select s
            INNER JOIN st_returnmeans m
              ON m.weekdate = s.weekdate
             AND m.exchange = s.exchange
             AND m.symbol = s.symbol
            LEFT JOIN st_data d
              ON d.weekdate = s.weekdate
             AND d.exchange = s.exchange
             AND d.symbol = s.symbol
             AND (:cs_only = 0 OR d.type = 'CS')
            {where}
            ORDER BY s.prob13wk DESC
            LIMIT :limit
        """)
        params["cs_only"] = 1 if cs_only else 0

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request.state.request_id, "error": "db_query_failed", "message": str(e)},
        )

    data = [dict(r) for r in rows]
    for d in data:
        d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'

    return {
        "request_id": request.state.request_id,
        "weekdate": str(latest_week),
        "exchange": ex,
        "min_prob13wk": min_prob13wk,
        "base_means": {"4wk": base4wk, "13wk": base13wk, "40wk": base40wk},
        "include_data": include_data,
        "cs_only": (cs_only if include_data else None),
        "count": len(data),
        "data": data,
        "hint": "These are the 'published' select stocks after filtering candidates in st_select by ST-IM CI-lower-bound rules from st_returnmeans.",
    }


@router.get("/history")
def published_selections_history(
    request: Request,
    # Filters
    exchange: str | None = Query(default=None, description="Optional exchange filter: N,Q,A,B,T,I"),
    start: str | None = Query(default=None, description="Start date YYYY-MM-DD (inclusive)"),
    end: str | None = Query(default=None, description="End date YYYY-MM-DD (inclusive)"),
    min_prob13wk: float = Query(default=0.55, ge=0.0, le=1.0, description="Minimum prob13wk threshold"),
    base4wk: float = Query(default=0.00, description="Base period mean return for 4-week"),
    base13wk: float = Query(default=2.19, description="Base period mean return for 13-week"),
    base40wk: float = Query(default=6.45, description="Base period mean return for 40-week"),
    # Output controls
    limit: int = Query(default=20000, ge=1, le=200000, description="Safety limit across all weeks"),
    group_by_week: bool = Query(default=True, description="If true, return results grouped by weekdate"),
    include_data: bool = Query(default=False, description="Join st_data for context fields"),
    cs_only: bool = Query(default=True, description="When include_data=true, filter st_data to CS"),
):
    """
    Published Select Stocks of the Week over a date range, enforcing:
      - prob13wk >= min_prob13wk (default 0.55)
      - x4wk1 > base4wk, x13wk1 > base13wk, x40wk1 > base40wk

    Returns:
      - If group_by_week=true: { weeks: [{weekdate, count, data:[...]}, ...] }
      - If group_by_week=false: flat list sorted by weekdate desc then prob13wk desc
    """
    ex = _norm_exchange(exchange) if exchange else None
    engine = get_engine()

    params: dict = {
        "limit": limit,
        "min_prob13wk": float(min_prob13wk),
        "base4wk": float(base4wk),
        "base13wk": float(base13wk),
        "base40wk": float(base40wk),
    }

    where = """
        WHERE 1=1
          AND s.prob13wk >= :min_prob13wk
          AND m.x4wk1  > :base4wk
          AND m.x13wk1 > :base13wk
          AND m.x40wk1 > :base40wk
    """

    if ex:
        where += " AND s.exchange = :exchange"
        params["exchange"] = ex

    if start:
        where += " AND s.weekdate >= :start"
        params["start"] = start

    if end:
        where += " AND s.weekdate <= :end"
        params["end"] = end

    if not include_data:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk,
                m.x4wk1,  m.x4wk2,  m.x4wk,  m.x4wksd,
                m.x13wk1, m.x13wk2, m.x13wk, m.x13wksd,
                m.x40wk1, m.x40wk2, m.x40wk, m.x40wksd
            FROM st_select s
            INNER JOIN st_returnmeans m
              ON m.weekdate = s.weekdate
             AND m.exchange = s.exchange
             AND m.symbol = s.symbol
            {where}
            ORDER BY s.weekdate DESC, s.prob13wk DESC
            LIMIT :limit
        """)
    else:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk,
                m.x4wk1,  m.x4wk2,  m.x4wk,  m.x4wksd,
                m.x13wk1, m.x13wk2, m.x13wk, m.x13wksd,
                m.x40wk1, m.x40wk2, m.x40wk, m.x40wksd,
                d.type,
                d.currency_code,
                d.fullname,
                d.shortname,
                d.industry_id,
                d.trend,
                d.trend_cnt,
                d.mt_cnt,
                d.rsi,
                d.rsi_updn,
                d.vol_tag,
                d.price,
                d.adj_close,
                d.pr_change,
                d.pr_chg13
            FROM st_select s
            INNER JOIN st_returnmeans m
              ON m.weekdate = s.weekdate
             AND m.exchange = s.exchange
             AND m.symbol = s.symbol
            LEFT JOIN st_data d
              ON d.weekdate = s.weekdate
             AND d.exchange = s.exchange
             AND d.symbol = s.symbol
             AND (:cs_only = 0 OR d.type = 'CS')
            {where}
            ORDER BY s.weekdate DESC, s.prob13wk DESC
            LIMIT :limit
        """)
        params["cs_only"] = 1 if cs_only else 0

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request.state.request_id, "error": "db_query_failed", "message": str(e)},
        )

    flat = [dict(r) for r in rows]
    for d in flat:
        d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'

    if not group_by_week:
        return {
            "request_id": request.state.request_id,
            "exchange": ex,
            "start": start,
            "end": end,
            "min_prob13wk": min_prob13wk,
            "base_means": {"4wk": base4wk, "13wk": base13wk, "40wk": base40wk},
            "include_data": include_data,
            "cs_only": (cs_only if include_data else None),
            "count": len(flat),
            "data": flat,
        }

    # Group by weekdate (descending week buckets)
    weeks: list[dict] = []
    current_week = None
    bucket: list[dict] = []

    for row in flat:
        wk = str(row["weekdate"])
        if current_week is None:
            current_week = wk

        if wk != current_week:
            weeks.append({"weekdate": current_week, "count": len(bucket), "data": bucket})
            current_week = wk
            bucket = []

        bucket.append(row)

    if current_week is not None:
        weeks.append({"weekdate": current_week, "count": len(bucket), "data": bucket})

    return {
        "request_id": request.state.request_id,
        "exchange": ex,
        "start": start,
        "end": end,
        "min_prob13wk": min_prob13wk,
        "base_means": {"4wk": base4wk, "13wk": base13wk, "40wk": base40wk},
        "include_data": include_data,
        "cs_only": (cs_only if include_data else None),
        "week_count": len(weeks),
        "count": len(flat),
        "weeks": weeks,
    }
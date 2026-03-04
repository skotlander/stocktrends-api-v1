# routers/selections.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from db import get_engine

from routers.signals import VALID_EXCHANGES

router = APIRouter(prefix="/selections", tags=["selections"])


def _norm_symbol(s: str) -> str:
    return s.strip().upper()


def _norm_exchange(ex: str) -> str:
    ex = ex.strip().upper()
    if ex not in VALID_EXCHANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid exchange '{ex}'. Must be one of {sorted(VALID_EXCHANGES)}",
        )
    return ex


@router.get("/latest")
def selections_latest(
    request: Request,
    exchange: str | None = Query(default=None, description="Optional exchange filter: N,Q,A,B,T,I"),
    min_prob13wk: float | None = Query(default=None, description="Optional minimum prob13wk threshold"),
    limit: int = Query(default=2000, ge=1, le=20000, description="Safety limit"),
    include_data: bool = Query(default=False, description="Join st_data for context fields"),
    cs_only: bool = Query(default=True, description="When include_data=true, filter st_data to CS"),
):
    """
    Latest ST-IM selection list from st_select for the most recent weekdate in the table.
    """
    ex = _norm_exchange(exchange) if exchange else None
    engine = get_engine()

    # 1) Find most recent weekdate available in st_select
    sql_latest_week = text("SELECT MAX(weekdate) AS weekdate FROM st_select")

    try:
        with engine.connect() as conn:
            latest = conn.execute(sql_latest_week).mappings().first()
            latest_week = latest["weekdate"] if latest else None
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "request_id": request.state.request_id,
                "error": "db_query_failed",
                "message": str(e),
            },
        )

    if not latest_week:
        raise HTTPException(
            status_code=404,
            detail={"request_id": request.state.request_id, "error": "no_selection_data"},
        )

    params: dict = {"weekdate": latest_week, "limit": limit}
    where = "WHERE s.weekdate = :weekdate"

    if ex:
        where += " AND s.exchange = :exchange"
        params["exchange"] = ex

    if min_prob13wk is not None:
        where += " AND s.prob13wk >= :min_prob13wk"
        params["min_prob13wk"] = float(min_prob13wk)

    if not include_data:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk
            FROM st_select s
            {where}
            ORDER BY s.prob13wk DESC
            LIMIT :limit
        """)
    else:
        # Join st_data for context (name, type, trend, rsi, etc.) on the same weekdate
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk,
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
            detail={
                "request_id": request.state.request_id,
                "error": "db_query_failed",
                "message": str(e),
            },
        )

    data = [dict(r) for r in rows]
    for d in data:
        d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'

    return {
        "request_id": request.state.request_id,
        "weekdate": str(latest_week),
        "exchange": ex,
        "min_prob13wk": min_prob13wk,
        "include_data": include_data,
        "cs_only": (cs_only if include_data else None),
        "count": len(data),
        "data": data,
    }


@router.get("/history")
def selections_history(
    request: Request,
    # Instrument targeting (optional)
    symbol_exchange: str | None = Query(default=None, description="e.g., IBM-N"),
    symbol: str | None = Query(default=None, description="e.g., IBM"),
    # Exchange is now a true optional FILTER (works with or without symbol)
    exchange: str | None = Query(default=None, description="Optional exchange filter: N,Q,A,B,T,I"),
    # Date filters (optional)
    start: str | None = Query(default=None, description="Start date YYYY-MM-DD (inclusive)"),
    end: str | None = Query(default=None, description="End date YYYY-MM-DD (inclusive)"),
    # Prob filter (optional)
    min_prob13wk: float | None = Query(default=None, description="Optional minimum prob13wk threshold"),
    # Output controls
    limit: int = Query(default=520, ge=1, le=5200, description="Safety limit"),
    include_data: bool = Query(default=False, description="Join st_data for context fields"),
    cs_only: bool = Query(default=True, description="When include_data=true, filter st_data to CS"),
):
    """
    Selection history.

    Supported filter modes:
      - symbol_exchange=IBM-N  (filters by symbol+exchange)
      - symbol=IBM&exchange=N  (filters by symbol+exchange)
      - symbol=IBM             (filters by symbol across all exchanges)
      - exchange=N             (filters by exchange across all symbols)
      - start/end only         (filters by date range across all selections)  [use with care]
    """
    engine = get_engine()

    s = None
    ex = None

    # Resolve explicit symbol_exchange first (strongest)
    if symbol_exchange:
        if "-" not in symbol_exchange:
            raise HTTPException(
                status_code=400,
                detail={
                    "request_id": request.state.request_id,
                    "error": "invalid_symbol_exchange",
                    "message": "Use like 'IBM-N'",
                },
            )
        s_part, ex_part = symbol_exchange.rsplit("-", 1)
        s = _norm_symbol(s_part)
        ex = _norm_exchange(ex_part)

    # If symbol provided, normalize it (exchange becomes optional filter)
    elif symbol:
        s = _norm_symbol(symbol)

    # If exchange provided as a filter (even without symbol), normalize it
    if exchange:
        ex = _norm_exchange(exchange)

    params: dict = {"limit": limit}
    where = "WHERE 1=1"

    if s:
        where += " AND s.symbol = :symbol"
        params["symbol"] = s

    if ex:
        where += " AND s.exchange = :exchange"
        params["exchange"] = ex

    if start:
        where += " AND s.weekdate >= :start"
        params["start"] = start

    if end:
        where += " AND s.weekdate <= :end"
        params["end"] = end

    if min_prob13wk is not None:
        where += " AND s.prob13wk >= :min_prob13wk"
        params["min_prob13wk"] = float(min_prob13wk)

    if not include_data:
        sql = text(f"""
            SELECT
                s.weekdate,
                s.exchange,
                s.symbol,
                s.prob13wk
            FROM st_select s
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
            detail={
                "request_id": request.state.request_id,
                "error": "db_query_failed",
                "message": str(e),
            },
        )

    data_desc = [dict(r) for r in rows]
    for d in data_desc:
        d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'

    # If it's clearly a single instrument (symbol+exchange), return ascending for charting
    if s and ex:
        data = list(reversed(data_desc))
    else:
        data = data_desc

    return {
        "request_id": request.state.request_id,
        "symbol": s,
        "exchange": ex,
        "symbol_exchange": f"{s}-{ex}" if (s and ex) else None,
        "start": start,
        "end": end,
        "min_prob13wk": min_prob13wk,
        "include_data": include_data,
        "cs_only": (cs_only if include_data else None),
        "count": len(data),
        "data": data,
    }
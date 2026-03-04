# routers/signals.py
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from db import get_engine

router = APIRouter(prefix="/signals", tags=["signals"])

VALID_EXCHANGES = {"N", "Q", "A", "B", "T", "I"}

def parse_symbol_exchange(symex: str) -> tuple[str, str]:
    # Expect "IBM-N"
    if "-" not in symex:
        raise ValueError("symbol_exchange must look like 'IBM-N'")
    symbol, exchange = symex.rsplit("-", 1)
    symbol = symbol.strip().upper()
    exchange = exchange.strip().upper()
    if exchange not in VALID_EXCHANGES:
        raise ValueError(f"Invalid exchange '{exchange}'. Must be one of {sorted(VALID_EXCHANGES)}")
    if not symbol:
        raise ValueError("Symbol is empty")
    return symbol, exchange


@router.get("/latest")
def latest_signals(
    symbol_exchange: str | None = Query(default=None, description="e.g., IBM-N"),
    symbol: str | None = Query(default=None, description="e.g., IBM"),
    exchange: str | None = Query(default=None, description="Exchange code: N,Q,A,B,T,I"),
    cs_only: bool = Query(default=True, description="Filter to Common Stocks only (type='CS')"),
    limit: int = Query(default=200, ge=1, le=5000),
):
    """
    Resolution rules:
    1) symbol_exchange wins (IBM-N)
    2) symbol + exchange
    3) symbol only -> unique ok, else 409 with matches
    """

    if not symbol_exchange and not symbol:
        # allow no symbol only if you want a "browse" mode
        engine = get_engine()
        sql = text("""
            SELECT symbol, exchange, trend, trend_cnt, mt_cnt, rsi, rsi_updn, vol_tag, weekdate
            FROM st_signals_latest
            WHERE (:cs_only = 0 OR type = 'CS')
            LIMIT :limit
        """)
        with engine.connect() as conn:
            rows = conn.execute(sql, {"cs_only": 1 if cs_only else 0, "limit": limit}).mappings().all()
        data = []
        for r in rows:
            d = dict(r)
            d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'
            data.append(d)
        return {"cs_only": cs_only, "count": len(data), "data": data}

    engine = get_engine()

    # Resolve symbol + exchange
    try:
        if symbol_exchange:
            s, ex = parse_symbol_exchange(symbol_exchange)
        else:
            s = symbol.strip().upper()  # type: ignore[union-attr]
            ex = exchange.strip().upper() if exchange else None
            if ex and ex not in VALID_EXCHANGES:
                raise HTTPException(status_code=400, detail=f"Invalid exchange '{ex}'")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # If symbol-only: check ambiguity in latest view (fast)
    if symbol and not exchange and not symbol_exchange:
        sql_ex = text("""
            SELECT DISTINCT exchange
            FROM st_signals_latest
            WHERE symbol = :symbol
              AND (:cs_only = 0 OR type = 'CS')
            ORDER BY exchange
        """)
        with engine.connect() as conn:
            exch_rows = conn.execute(sql_ex, {"symbol": s, "cs_only": 1 if cs_only else 0}).mappings().all()

        exchanges = [r["exchange"] for r in exch_rows if r.get("exchange")]

        if len(exchanges) == 0:
            raise HTTPException(status_code=404, detail="Symbol not found")
        if len(exchanges) > 1:
            matches = [{"symbol": s, "exchange": e, "symbol_exchange": f"{s}-{e}"} for e in exchanges]
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "ambiguous_symbol",
                    "symbol": s,
                    "matches": matches,
                    "hint": "Specify exchange=... or use symbol_exchange=... to resolve uniquely.",
                },
            )
        ex = exchanges[0]

    if not ex:
        raise HTTPException(status_code=400, detail="Exchange required. Use exchange=... or symbol_exchange=...")

    sql = text("""
        SELECT symbol, exchange, trend, trend_cnt, mt_cnt, rsi, rsi_updn, vol_tag, weekdate
        FROM st_signals_latest
        WHERE symbol = :symbol AND exchange = :exchange
          AND (:cs_only = 0 OR type = 'CS')
        LIMIT 1
    """)

    try:
        with engine.connect() as conn:
            row = conn.execute(sql, {"symbol": s, "exchange": ex, "cs_only": 1 if cs_only else 0}).mappings().first()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    if not row:
        raise HTTPException(status_code=404, detail="Instrument not found")

    d = dict(row)
    d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'
    return {"cs_only": cs_only, "count": 1, "data": [d]}


@router.get("/history")
def signal_history(
    symbol_exchange: str | None = Query(default=None, description="e.g., IBM-N"),
    symbol: str | None = Query(default=None, description="e.g., IBM"),
    exchange: str | None = Query(default=None, description="Exchange code: N,Q,A,B,T,I"),
    weeks: int = Query(default=104, ge=1, le=2000),
    cs_only: bool = Query(default=True, description="Filter to Common Stocks only (type='CS')"),
):
    """
    Resolution rules:
    1) symbol_exchange wins (IBM-N)
    2) symbol + exchange
    3) symbol only -> unique ok, else 409 with matches
    """
    if not symbol_exchange and not symbol:
        raise HTTPException(status_code=400, detail="Provide symbol_exchange (IBM-N) or symbol (IBM).")

    engine = get_engine()

    # Resolve symbol + exchange
    try:
        if symbol_exchange:
            s, ex = parse_symbol_exchange(symbol_exchange)
        else:
            s = symbol.strip().upper()  # type: ignore[union-attr]
            ex = exchange.strip().upper() if exchange else None
            if ex and ex not in VALID_EXCHANGES:
                raise HTTPException(status_code=400, detail=f"Invalid exchange '{ex}'")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # If symbol-only: check ambiguity using st_mast (fast and correct)
    if symbol and not exchange and not symbol_exchange:
        sql_ex = text("""
            SELECT exchange
            FROM st_mast
            WHERE symbol = :symbol
              AND (:cs_only = 0 OR type = 'CS')
            ORDER BY exchange
        """)
        try:
            with engine.connect() as conn:
                exch_rows = conn.execute(sql_ex, {"symbol": s, "cs_only": 1 if cs_only else 0}).mappings().all()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

        exchanges = [r["exchange"] for r in exch_rows if r.get("exchange")]

        if len(exchanges) == 0:
            raise HTTPException(status_code=404, detail="Symbol not found")
        if len(exchanges) > 1:
            matches = [{"symbol": s, "exchange": e, "symbol_exchange": f"{s}-{e}"} for e in exchanges]
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "ambiguous_symbol",
                    "symbol": s,
                    "matches": matches,
                    "hint": "Specify exchange=... or use symbol_exchange=... to resolve uniquely.",
                },
            )
        ex = exchanges[0]

    if not ex:
        raise HTTPException(status_code=400, detail="Exchange required. Use exchange=... or symbol_exchange=...")

    sql = text("""
        SELECT
            symbol,
            exchange,
            trend,
            trend_cnt,
            mt_cnt,
            rsi,
            rsi_updn,
            vol_tag,
            weekdate
        FROM st_data
        WHERE symbol = :symbol
          AND exchange = :exchange
          AND (:cs_only = 0 OR type = 'CS')
        ORDER BY weekdate DESC
        LIMIT :weeks
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {"symbol": s, "exchange": ex, "weeks": weeks, "cs_only": 1 if cs_only else 0},
            ).mappings().all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    rows = list(reversed(rows))
    data = []
    for r in rows:
        d = dict(r)
        d["symbol_exchange"] = f'{d["symbol"]}-{d["exchange"]}'
        data.append(d)

    return {
        "symbol": s,
        "exchange": ex,
        "symbol_exchange": f"{s}-{ex}",
        "cs_only": cs_only,
        "weeks_requested": weeks,
        "count": len(data),
        "from_weekdate": data[0]["weekdate"] if data else None,
        "to_weekdate": data[-1]["weekdate"] if data else None,
        "data": data,
    }
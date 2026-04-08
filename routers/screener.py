# routers/screener.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from db import get_engine

router = APIRouter(prefix="/agent/screener", tags=["agent_screener"])

_VALID_TREND_CODES = {"^+", "^-", "v^", "v+", "v-", "^v"}
_VALID_SORT_FIELDS = {"rsi", "mt_cnt"}
_VALID_EXCHANGES = {"A", "B", "I", "N", "Q", "T"}
_DEFAULT_TREND = "^+,^-,v^"


def _parse_trend_filter(trend: str | None) -> list[str] | None:
    """
    Parse and validate the trend query parameter.
    Returns a list of validated trend codes, or None when trend=all (no filter).
    Raises HTTP 400 if any code is not in VALID_TREND_CODES.
    """
    raw = (trend or _DEFAULT_TREND).strip()
    if raw.lower() == "all":
        return None
    codes = [t.strip() for t in raw.split(",") if t.strip()]
    if not codes:
        return None
    invalid = [c for c in codes if c not in _VALID_TREND_CODES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_trend_code",
                "invalid": invalid,
                "valid": sorted(_VALID_TREND_CODES),
            },
        )
    return codes


@router.get(
    "/top",
    summary="Top-ranked instruments screener",
    description=(
        "Returns a ranked list of instruments from the latest Stock Trends signal data. "
        "Results are filtered by trend state, RSI, and trend duration, then ranked by the "
        "selected sort field. Designed for agent-native workflows that need a scored "
        "instrument universe without per-instrument lookup overhead. "
        "Pricing rule: agent_screener_top (0.50 STC per call for agent-pay callers)."
    ),
)
def screener_top(
    request: Request,
    exchange: str | None = Query(
        default=None,
        description="Optional exchange filter: A, B, I, N, Q, T",
    ),
    trend: str | None = Query(
        default=None,
        description=(
            "Comma-separated trend filter, e.g. '^+,^-,v^'. "
            "Default restricts to bullish states (^+, ^-, v^). "
            "Pass 'all' to disable trend filter entirely."
        ),
    ),
    min_rsi: int = Query(
        default=100,
        ge=0,
        le=500,
        description="Minimum RSI threshold. 100 = outperforming the benchmark.",
    ),
    min_mt_cnt: int = Query(
        default=1,
        ge=0,
        le=500,
        description="Minimum weeks in current major trend.",
    ),
    min_trend_cnt: int = Query(
        default=1,
        ge=0,
        le=500,
        description="Minimum weeks in current specific trend state.",
    ),
    sort: str = Query(
        default="rsi",
        description="Primary sort field. Accepted values: rsi, mt_cnt.",
    ),
    limit: int = Query(
        default=25,
        ge=1,
        le=100,
        description="Maximum number of results. Hard cap at 100.",
    ),
    weekdate: str | None = Query(
        default=None,
        description="Override weekdate YYYY-MM-DD. Defaults to latest available in st_signals_latest.",
    ),
):
    # --- Validate sort ---
    if sort not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_sort",
                "value": sort,
                "valid": sorted(_VALID_SORT_FIELDS),
            },
        )

    # --- Validate exchange ---
    norm_exchange: str | None = None
    if exchange:
        norm_exchange = exchange.strip().upper()
        if norm_exchange not in _VALID_EXCHANGES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_exchange",
                    "value": exchange,
                    "valid": sorted(_VALID_EXCHANGES),
                },
            )

    # --- Parse and validate trend filter ---
    trend_codes = _parse_trend_filter(trend)

    engine = get_engine()

    with engine.connect() as conn:
        # --- Resolve weekdate ---
        resolved_weekdate = weekdate
        if not resolved_weekdate:
            row = conn.execute(
                text("SELECT MAX(weekdate) AS weekdate FROM st_data")
            ).mappings().first()
            resolved_weekdate = str(row["weekdate"]) if row and row["weekdate"] else None

        if not resolved_weekdate:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": getattr(request.state, "request_id", None),
                    "error": "no_signal_data",
                    "message": "No weekdate available in st_signals_latest.",
                },
            )

        # --- Build WHERE clause ---
        where_parts = [
            "weekdate = :weekdate",
            "type = 'CS'",
            "rsi >= :min_rsi",
            "mt_cnt >= :min_mt_cnt",
            "trend_cnt >= :min_trend_cnt",
        ]
        params: dict = {
            "weekdate": resolved_weekdate,
            "min_rsi": min_rsi,
            "min_mt_cnt": min_mt_cnt,
            "min_trend_cnt": min_trend_cnt,
            "limit": limit,
        }

        if norm_exchange:
            where_parts.append("exchange = :exchange")
            params["exchange"] = norm_exchange

        if trend_codes is not None:
            # Parameterized IN clause — no user input interpolated into SQL text
            trend_bind = {f"trend_{i}": code for i, code in enumerate(trend_codes)}
            placeholders = ", ".join(f":trend_{i}" for i in range(len(trend_codes)))
            where_parts.append(f"trend IN ({placeholders})")
            params.update(trend_bind)

        where_sql = " AND ".join(where_parts)

        # --- Deterministic ORDER BY ---
        # Secondary and tertiary keys ensure stable ordering when primary values tie.
        # symbol ASC, exchange ASC as final tiebreaker for full determinism.
        if sort == "rsi":
            order_sql = "rsi DESC, mt_cnt DESC, trend_cnt DESC, symbol ASC, exchange ASC"
        else:  # mt_cnt
            order_sql = "mt_cnt DESC, rsi DESC, trend_cnt DESC, symbol ASC, exchange ASC"

        # --- Main query ---
        data_sql = text(
            f"""
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
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT :limit
            """
        )

        # --- Count query (same WHERE, no LIMIT) ---
        count_sql = text(
            f"""
            SELECT COUNT(*) AS total
            FROM st_data
            WHERE {where_sql}
            """
        )
        count_params = {k: v for k, v in params.items() if k != "limit"}

        rows = conn.execute(data_sql, params).mappings().all()
        total = conn.execute(count_sql, count_params).scalar() or 0

    results = [
        {
            "rank": i + 1,
            "symbol": row["symbol"],
            "exchange": row["exchange"],
            "symbol_exchange": f'{row["symbol"]}-{row["exchange"]}',
            "trend": row["trend"],
            "trend_cnt": int(row["trend_cnt"] or 0),
            "mt_cnt": int(row["mt_cnt"] or 0),
            "rsi": int(row["rsi"] or 0),
            "rsi_updn": row["rsi_updn"],
            "vol_tag": row["vol_tag"],
            "weekdate": str(row["weekdate"]),
        }
        for i, row in enumerate(rows)
    ]

    return {
        "request_id": getattr(request.state, "request_id", None),
        "screener": "top",
        "weekdate": resolved_weekdate,
        "filter_summary": {
            "exchange": norm_exchange,
            "trend_filter": trend_codes if trend_codes is not None else ["all"],
            "min_rsi": min_rsi,
            "min_mt_cnt": min_mt_cnt,
            "min_trend_cnt": min_trend_cnt,
            "sort": sort,
        },
        "count": len(results),
        "total_matched": int(total),
        "results": results,
    }

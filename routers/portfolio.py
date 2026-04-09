# routers/portfolio.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from db import get_engine
from routers.signals import VALID_EXCHANGES, parse_symbol_exchange
from services import decision_service, regime_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_FORECAST_LOOKBACK = 5
_CANDIDATE_POOL_SIZE = 20
_VALID_UNIVERSES = {"top"}
_VALID_BIASES = {"auto", "bullish", "bearish"}
_WEIGHT_SUM_TOLERANCE = 0.01
_MAX_POSITIONS = 25


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ConstructPortfolioRequest(BaseModel):
    universe: str = "top"
    count: int = Field(default=5, ge=1, le=10)
    bias: str = "auto"
    exchange: str | None = None


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _resolve_trend_codes(bias: str, current_regime: str) -> list[str]:
    """
    Return the sorted list of trend codes to pass to the candidate SQL IN clause.
    bias='auto' defers to current_regime; mixed regime includes all directional codes.
    """
    if bias == "bullish":
        return sorted(regime_service.BULLISH_TRENDS)
    if bias == "bearish":
        return sorted(regime_service.BEARISH_TRENDS)
    # auto
    if current_regime == "bullish":
        return sorted(regime_service.BULLISH_TRENDS)
    if current_regime == "bearish":
        return sorted(regime_service.BEARISH_TRENDS)
    # mixed regime — include all directional trends; decision_score will still
    # penalise divergent symbols through the alignment component
    return sorted(regime_service.BULLISH_TRENDS | regime_service.BEARISH_TRENDS)


def _bias_resolved(bias: str, current_regime: str) -> str:
    if bias != "auto":
        return bias
    return current_regime  # "bullish", "bearish", or "mixed"


def _construction_notes(
    bias: str,
    resolved_bias: str,
    current_regime: str,
    current_regime_score: float,
    candidates_evaluated: int,
    requested_count: int,
    filled_count: int,
    weight: float,
) -> list[str]:
    notes: list[str] = []

    if bias == "auto":
        notes.append(
            f"Bias auto-resolved to {resolved_bias} based on current regime "
            f"(score: {round(current_regime_score, 4)})"
        )

    if bias != "auto" and bias != current_regime and current_regime != "mixed":
        notes.append(
            f"Requested bias ({bias}) opposes current regime ({current_regime}); "
            "expect lower decision_scores and divergent alignments"
        )

    trend_desc = (
        "bullish trend states" if resolved_bias == "bullish"
        else "bearish trend states" if resolved_bias == "bearish"
        else "all directional trend states"
    )
    notes.append(f"{candidates_evaluated} candidates evaluated across {trend_desc}")

    if filled_count < requested_count:
        notes.append(
            f"Only {filled_count} of {requested_count} requested positions filled "
            f"— insufficient candidates after filtering"
        )
    else:
        notes.append(f"{filled_count} of {requested_count} requested positions filled")

    notes.append(f"Equal weight: {weight} per position")
    return notes


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/construct",
    summary="Construct a scored equal-weight portfolio",
    description=(
        "Generates a small portfolio of symbols by running screener logic to produce "
        "a candidate pool, evaluating each candidate through the decision scoring system, "
        "and selecting the top N by decision_score. Fully deterministic — no ML. "
        "Reuses the same regime and decision logic as /market/regime/forecast and "
        "/decision/evaluate-symbol. "
        "Pricing rule: portfolio_construct (1.00 STC per call)."
    ),
)
def construct_portfolio(body: ConstructPortfolioRequest, request: Request):
    request_id = getattr(request.state, "request_id", None)

    # --- Validate request ---
    if body.universe not in _VALID_UNIVERSES:
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": request_id,
                "error": "invalid_universe",
                "value": body.universe,
                "valid": sorted(_VALID_UNIVERSES),
            },
        )

    if body.bias not in _VALID_BIASES:
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": request_id,
                "error": "invalid_bias",
                "value": body.bias,
                "valid": sorted(_VALID_BIASES),
            },
        )

    norm_exchange: str | None = None
    if body.exchange:
        norm_exchange = body.exchange.strip().upper()
        if norm_exchange not in VALID_EXCHANGES:
            raise HTTPException(
                status_code=400,
                detail={
                    "request_id": request_id,
                    "error": "invalid_exchange",
                    "value": body.exchange,
                    "valid": sorted(VALID_EXCHANGES),
                },
            )

    engine = get_engine()

    with engine.connect() as conn:

        # --- Query 1: Resolve most recent 5 weekdates ---
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
            {"limit": _FORECAST_LOOKBACK},
        ).mappings().all()

        weekdates = [r["weekdate"] for r in weekdate_rows if r["weekdate"]]
        if not weekdates:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": request_id,
                    "error": "no_signal_data",
                    "message": "No weekdates available in st_data.",
                },
            )

        latest_wd = weekdates[0]

        # --- Query 2: Regime aggregation over the 5-week lookback ---
        # Placeholders built from DB-returned date objects — no user input in SQL
        week_binds = {f"w{i}": wd for i, wd in enumerate(weekdates)}
        week_placeholders = ", ".join(f":w{i}" for i in range(len(weekdates)))
        agg_rows = conn.execute(
            text(
                f"""
                SELECT
                    weekdate,
                    trend,
                    COUNT(*) AS cnt
                FROM st_data
                WHERE weekdate IN ({week_placeholders})
                  AND type = 'CS'
                GROUP BY weekdate, trend
                ORDER BY weekdate DESC, trend
                """
            ),
            week_binds,
        ).mappings().all()

        # Compute regime in Python before resolving trend codes
        scores_by_week = regime_service.compute_scores_by_week(weekdates, agg_rows)
        if not scores_by_week:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": request_id,
                    "error": "no_signal_data",
                    "message": "Cannot compute regime score for the resolved weekdates.",
                },
            )

        _, current_regime_score = scores_by_week[0]
        current_regime = regime_service.classify_regime(current_regime_score)

        # Resolve bias → trend codes for candidate SQL
        trend_codes = _resolve_trend_codes(body.bias, current_regime)
        trend_binds = {f"t{i}": code for i, code in enumerate(trend_codes)}
        trend_placeholders = ", ".join(f":t{i}" for i in range(len(trend_codes)))

        # --- Query 3: Candidate pool ---
        # Neutral ordering — let decision_score fully determine ranking
        candidate_params: dict = {
            "latest_wd": latest_wd,
            "pool_size": _CANDIDATE_POOL_SIZE,
            **trend_binds,
        }
        # Exchange filter: explicit exchange overrides the US-market default.
        # Default (no exchange): restrict to US-listed exchanges (N, Q, A).
        # type = 'CS' already excludes non-tradable instrument types.
        if norm_exchange:
            exchange_clause = "AND exchange = :exchange"
            candidate_params["exchange"] = norm_exchange
        else:
            exchange_clause = "AND exchange IN ('N', 'Q', 'A')"

        candidate_rows = conn.execute(
            text(
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
                WHERE weekdate = :latest_wd
                  AND type = 'CS'
                  AND trend IN ({trend_placeholders})
                  {exchange_clause}
                ORDER BY symbol ASC
                LIMIT :pool_size
                """
            ),
            candidate_params,
        ).mappings().all()

    if not candidate_rows:
        raise HTTPException(
            status_code=422,
            detail={
                "request_id": request_id,
                "error": "insufficient_candidates",
                "message": (
                    f"No candidates found for bias='{body.bias}'"
                    + (f", exchange='{norm_exchange}'" if norm_exchange else "")
                    + f" on weekdate {latest_wd}."
                ),
            },
        )

    # --- Compute regime context (Python, no more SQL) ---
    forecast = regime_service.compute_forecast_signals(scores_by_week)
    scores = [s_val for _, s_val in scores_by_week]
    regime_confidence = regime_service.classify_confidence(current_regime_score)

    consistency_count = sum(
        1 for sv in scores if regime_service.classify_regime(sv) == current_regime
    )
    consistency_pct = consistency_count / len(scores)

    fc_confidence = regime_service.forecast_confidence(
        consistency_pct, current_regime_score, forecast["avg_delta"]
    )

    # --- Evaluate each candidate in-process ---
    evaluated: list[dict] = []
    for row in candidate_rows:
        trend = row["trend"] or ""
        trend_cnt = int(row["trend_cnt"] or 0)
        mt_cnt = int(row["mt_cnt"] or 0)
        rsi = int(row["rsi"] or 0)

        sym_bias = decision_service.symbol_bias(trend)
        sym_alignment = decision_service.alignment(sym_bias, current_regime)
        bias_label = decision_service.compute_bias(sym_bias, sym_alignment)
        confidence = decision_service.decision_confidence(
            sym_alignment, sym_bias, trend_cnt, rsi, current_regime_score
        )
        d_score = decision_service.decision_score(
            sym_alignment, sym_bias, trend_cnt, rsi, current_regime_score
        )

        evaluated.append({
            "symbol": row["symbol"],
            "exchange": row["exchange"],
            "symbol_exchange": f'{row["symbol"]}-{row["exchange"]}',
            "trend": trend,
            "trend_cnt": trend_cnt,
            "mt_cnt": mt_cnt,
            "rsi": rsi,
            "bias": bias_label,
            "confidence": confidence,
            "decision_score": d_score,
        })

    # --- Rank by decision_score DESC, stable secondary by symbol ASC ---
    evaluated.sort(key=lambda x: (-x["decision_score"], x["symbol"]))

    # --- Select top N and assign equal weight ---
    selected = evaluated[: body.count]
    weight = round(1.0 / len(selected), 4) if selected else 0.0

    portfolio = [
        {"rank": i + 1, "weight": weight, **item}
        for i, item in enumerate(selected)
    ]

    # --- Portfolio score = mean decision_score of selected positions ---
    portfolio_score = round(
        sum(p["decision_score"] for p in portfolio) / len(portfolio), 4
    ) if portfolio else 0.0

    resolved_bias = _bias_resolved(body.bias, current_regime)
    notes = _construction_notes(
        bias=body.bias,
        resolved_bias=resolved_bias,
        current_regime=current_regime,
        current_regime_score=current_regime_score,
        candidates_evaluated=len(candidate_rows),
        requested_count=body.count,
        filled_count=len(selected),
        weight=weight,
    )

    return {
        "request_id": request_id,
        "weekdate": str(latest_wd),
        "portfolio": portfolio,
        "count": len(portfolio),
        "candidates_evaluated": len(candidate_rows),
        "portfolio_score": portfolio_score,
        "bias_requested": body.bias,
        "bias_resolved": resolved_bias,
        "regime_context": {
            "current_regime": current_regime,
            "regime_score": round(current_regime_score, 4),
            "regime_confidence": regime_confidence,
            "forecast_regime": forecast["forecast_regime"],
            "forecast_confidence": fc_confidence,
            "recent_direction": forecast["recent_direction"],
            "regime_consistency": round(consistency_pct, 4),
            "weeks_analyzed": len(scores_by_week),
        },
        "construction_notes": notes,
    }


# ---------------------------------------------------------------------------
# Evaluate endpoint — request schema
# ---------------------------------------------------------------------------

class EvaluatePortfolioPosition(BaseModel):
    symbol_exchange: str   # "AAPL-Q"
    weight: float          # Must be > 0


class EvaluatePortfolioRequest(BaseModel):
    positions: list[EvaluatePortfolioPosition] = Field(min_length=1, max_length=_MAX_POSITIONS)


# ---------------------------------------------------------------------------
# Evaluate endpoint — aggregate helpers
# ---------------------------------------------------------------------------

_CONF_MAP = {"high": 1.0, "moderate": 0.5, "low": 0.0}
_ALIGN_MAP = {"aligned": 1.0, "neutral": 0.0, "divergent": -1.0}


def _agg_portfolio_bias(internal: list[dict]) -> str:
    """
    Score-weighted directional aggregation using normalized weights.
    bullish_score = sum(norm_weight * decision_score) for bullish positions
    bearish_score = sum(norm_weight * decision_score) for bearish positions
    net >= 0.05 → bullish, net <= -0.05 → bearish, else → mixed
    """
    bullish_score = sum(
        item["norm_weight"] * item["decision_score"]
        for item in internal if item["sym_bias"] == "bullish"
    )
    bearish_score = sum(
        item["norm_weight"] * item["decision_score"]
        for item in internal if item["sym_bias"] == "bearish"
    )
    net = bullish_score - bearish_score
    if net >= 0.05:
        return "bullish"
    if net <= -0.05:
        return "bearish"
    return "mixed"


def _agg_portfolio_confidence(internal: list[dict]) -> str:
    """Weighted mean of confidence scores mapped back to tier."""
    mean_conf = sum(item["norm_weight"] * _CONF_MAP[item["confidence"]] for item in internal)
    if mean_conf >= 0.75:
        return "high"
    if mean_conf >= 0.40:
        return "moderate"
    return "low"


def _agg_portfolio_alignment(internal: list[dict]) -> str:
    """Weighted mean of alignment values mapped back to label."""
    mean_align = sum(item["norm_weight"] * _ALIGN_MAP[item["alignment"]] for item in internal)
    if mean_align >= 0.50:
        return "aligned"
    if mean_align <= -0.50:
        return "divergent"
    return "mixed"


def _evaluation_notes(
    positions_missing: int,
    positions_total: int,
    found_weight_sum: float,
    latest_wd: str,
    portfolio_alignment: str,
    current_regime: str,
) -> list[str]:
    notes: list[str] = []
    if positions_missing > 0:
        notes.append(
            f"{positions_missing} of {positions_total} positions not found in st_data "
            f"for weekdate {latest_wd} — excluded from aggregates"
        )
        notes.append(
            f"Portfolio aggregates computed on {positions_total - positions_missing} positions "
            f"representing {round(found_weight_sum, 4)} of submitted weight"
        )
    notes.append(
        f"Portfolio is {portfolio_alignment} with current {current_regime} regime"
    )
    return notes


# ---------------------------------------------------------------------------
# Evaluate endpoint — handler
# ---------------------------------------------------------------------------

@router.post(
    "/evaluate",
    summary="Evaluate a user-supplied portfolio",
    description=(
        "Accepts a list of symbol-weight pairs and evaluates each position using the "
        "same decision scoring and regime logic as /decision/evaluate-symbol. "
        "Returns position-level and portfolio-level aggregates. "
        "Weights must be positive and sum to 1.0 (±0.01 tolerance). "
        "Duplicates are rejected. Missing symbols are included with found=false "
        "and excluded from portfolio aggregates. "
        "Pricing rule: portfolio_evaluate (0.75 STC per call)."
    ),
)
def evaluate_portfolio(body: EvaluatePortfolioRequest, request: Request):
    request_id = getattr(request.state, "request_id", None)

    # --- Step 1: Parse and validate all positions before any DB access ---
    parsed: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()

    for pos in body.positions:
        try:
            s, ex = parse_symbol_exchange(pos.symbol_exchange)
        except ValueError as ve:
            raise HTTPException(
                status_code=400,
                detail={
                    "request_id": request_id,
                    "error": "invalid_input",
                    "message": str(ve),
                },
            )

        key = (s, ex)
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail={
                    "request_id": request_id,
                    "error": "duplicate_positions",
                    "message": f"Duplicate position: {s}-{ex}",
                },
            )
        seen.add(key)

        if pos.weight <= 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "request_id": request_id,
                    "error": "invalid_weights",
                    "message": f"Weight for {s}-{ex} must be > 0, got {pos.weight}",
                },
            )

        parsed.append((s, ex, pos.weight))

    weight_sum = sum(w for _, _, w in parsed)
    if not (1.0 - _WEIGHT_SUM_TOLERANCE <= weight_sum <= 1.0 + _WEIGHT_SUM_TOLERANCE):
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": request_id,
                "error": "invalid_weights",
                "message": (
                    f"Weights must sum to 1.0 (±{_WEIGHT_SUM_TOLERANCE}), "
                    f"got {round(weight_sum, 6)}"
                ),
            },
        )

    engine = get_engine()

    with engine.connect() as conn:

        # --- Query 1: Resolve most recent 5 weekdates ---
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
            {"limit": _FORECAST_LOOKBACK},
        ).mappings().all()

        weekdates = [r["weekdate"] for r in weekdate_rows if r["weekdate"]]
        if not weekdates:
            raise HTTPException(
                status_code=503,
                detail={
                    "request_id": request_id,
                    "error": "no_signal_data",
                    "message": "No weekdates available in st_data.",
                },
            )

        latest_wd = weekdates[0]

        # --- Query 2: Regime aggregation over the 5-week lookback ---
        # Placeholders built from DB-returned date objects — no user input in SQL
        week_binds = {f"w{i}": wd for i, wd in enumerate(weekdates)}
        week_placeholders = ", ".join(f":w{i}" for i in range(len(weekdates)))
        agg_rows = conn.execute(
            text(
                f"""
                SELECT
                    weekdate,
                    trend,
                    COUNT(*) AS cnt
                FROM st_data
                WHERE weekdate IN ({week_placeholders})
                  AND type = 'CS'
                GROUP BY weekdate, trend
                ORDER BY weekdate DESC, trend
                """
            ),
            week_binds,
        ).mappings().all()

        # --- Query 3: Batch symbol lookup —
        # OR clauses built from parse_symbol_exchange-validated strings only
        or_parts = " OR ".join(
            f"(symbol = :s{i} AND exchange = :e{i})"
            for i in range(len(parsed))
        )
        sym_binds: dict = {"latest_wd": latest_wd}
        for i, (s, ex, _) in enumerate(parsed):
            sym_binds[f"s{i}"] = s
            sym_binds[f"e{i}"] = ex

        sym_rows = conn.execute(
            text(
                f"""
                SELECT
                    symbol,
                    exchange,
                    trend,
                    trend_cnt,
                    mt_cnt,
                    rsi,
                    weekdate
                FROM st_data
                WHERE weekdate = :latest_wd
                  AND type = 'CS'
                  AND ({or_parts})
                """
            ),
            sym_binds,
        ).mappings().all()

    # Index symbol lookup by (symbol, exchange)
    sym_lookup: dict[tuple[str, str], object] = {
        (r["symbol"], r["exchange"]): r for r in sym_rows
    }

    # --- Compute regime context (Python, no more SQL) ---
    scores_by_week = regime_service.compute_scores_by_week(weekdates, agg_rows)
    if not scores_by_week:
        raise HTTPException(
            status_code=503,
            detail={
                "request_id": request_id,
                "error": "no_signal_data",
                "message": "Cannot compute regime score for the resolved weekdates.",
            },
        )

    forecast = regime_service.compute_forecast_signals(scores_by_week)
    scores = [s_val for _, s_val in scores_by_week]
    _, current_regime_score = scores_by_week[0]
    current_regime = regime_service.classify_regime(current_regime_score)
    regime_confidence = regime_service.classify_confidence(current_regime_score)

    consistency_count = sum(
        1 for sv in scores if regime_service.classify_regime(sv) == current_regime
    )
    consistency_pct = consistency_count / len(scores)
    fc_confidence = regime_service.forecast_confidence(
        consistency_pct, current_regime_score, forecast["avg_delta"]
    )

    # --- Evaluate each position in-process ---
    evaluated: list[dict] = []   # response positions
    internal: list[dict] = []    # found positions only — used for aggregates

    for s, ex, weight in parsed:
        row = sym_lookup.get((s, ex))
        if row is None:
            evaluated.append({
                "symbol": s,
                "exchange": ex,
                "symbol_exchange": f"{s}-{ex}",
                "weight": weight,
                "trend": None,
                "trend_cnt": None,
                "mt_cnt": None,
                "rsi": None,
                "bias": None,
                "confidence": None,
                "decision_score": None,
                "alignment": None,
                "found": False,
            })
        else:
            trend = row["trend"] or ""
            trend_cnt = int(row["trend_cnt"] or 0)
            mt_cnt = int(row["mt_cnt"] or 0)
            rsi = int(row["rsi"] or 0)

            sym_bias = decision_service.symbol_bias(trend)
            sym_alignment = decision_service.alignment(sym_bias, current_regime)
            bias_label = decision_service.compute_bias(sym_bias, sym_alignment)
            confidence = decision_service.decision_confidence(
                sym_alignment, sym_bias, trend_cnt, rsi, current_regime_score
            )
            d_score = decision_service.decision_score(
                sym_alignment, sym_bias, trend_cnt, rsi, current_regime_score
            )

            evaluated.append({
                "symbol": s,
                "exchange": ex,
                "symbol_exchange": f"{s}-{ex}",
                "weight": weight,
                "trend": trend,
                "trend_cnt": trend_cnt,
                "mt_cnt": mt_cnt,
                "rsi": rsi,
                "bias": bias_label,
                "confidence": confidence,
                "decision_score": d_score,
                "alignment": sym_alignment,
                "found": True,
            })
            internal.append({
                "weight": weight,
                "decision_score": d_score,
                "sym_bias": sym_bias,
                "alignment": sym_alignment,
                "confidence": confidence,
            })

    if not internal:
        raise HTTPException(
            status_code=422,
            detail={
                "request_id": request_id,
                "error": "all_positions_missing",
                "message": (
                    f"None of the {len(parsed)} submitted positions were found "
                    f"in st_data for weekdate {latest_wd}."
                ),
            },
        )

    # --- Normalize weights and compute portfolio aggregates ---
    found_weight_sum = sum(item["weight"] for item in internal)
    for item in internal:
        item["norm_weight"] = item["weight"] / found_weight_sum

    portfolio_score = round(
        sum(item["norm_weight"] * item["decision_score"] for item in internal), 4
    )
    portfolio_bias = _agg_portfolio_bias(internal)
    portfolio_confidence = _agg_portfolio_confidence(internal)
    portfolio_alignment = _agg_portfolio_alignment(internal)

    positions_missing = len(evaluated) - len(internal)
    notes = _evaluation_notes(
        positions_missing=positions_missing,
        positions_total=len(evaluated),
        found_weight_sum=found_weight_sum,
        latest_wd=str(latest_wd),
        portfolio_alignment=portfolio_alignment,
        current_regime=current_regime,
    )

    return {
        "request_id": request_id,
        "weekdate": str(latest_wd),
        "positions": evaluated,
        "positions_found": len(internal),
        "positions_missing": positions_missing,
        "effective_weight": round(found_weight_sum, 4),
        "portfolio_score": portfolio_score,
        "portfolio_bias": portfolio_bias,
        "portfolio_confidence": portfolio_confidence,
        "portfolio_alignment": portfolio_alignment,
        "regime_context": {
            "current_regime": current_regime,
            "regime_score": round(current_regime_score, 4),
            "regime_confidence": regime_confidence,
            "forecast_regime": forecast["forecast_regime"],
            "forecast_confidence": fc_confidence,
            "recent_direction": forecast["recent_direction"],
            "regime_consistency": round(consistency_pct, 4),
            "weeks_analyzed": len(scores_by_week),
        },
        "evaluation_notes": notes,
    }

# services/decision_service.py
#
# Shared symbol-level decision logic.
# Consumed by routers/decision.py and routers/portfolio.py.
# No SQL here — callers pass pre-fetched field values.

from __future__ import annotations

from services import regime_service


def symbol_bias(trend: str) -> str:
    """Maps a trend code to 'bullish', 'bearish', or 'neutral'."""
    if trend in regime_service.BULLISH_TRENDS:
        return "bullish"
    if trend in regime_service.BEARISH_TRENDS:
        return "bearish"
    return "neutral"


def alignment(sym_bias: str, current_regime: str) -> str:
    """
    Returns 'aligned', 'divergent', or 'neutral'.
    Neutral symbol always produces 'neutral'.
    Both bullish or both bearish → aligned.
    Opposite directions → divergent.
    Mixed regime with directional symbol → neutral.
    """
    if sym_bias == "neutral":
        return "neutral"
    if sym_bias == current_regime:
        return "aligned"
    if current_regime == "mixed":
        return "neutral"
    return "divergent"


def compute_bias(sym_bias: str, sym_alignment: str) -> str:
    """
    Synthesize an overall bias label.
      aligned bullish  → strong_bullish
      aligned bearish  → strong_bearish
      neutral alignment, bullish symbol → bullish
      neutral alignment, bearish symbol → bearish
      divergent        → cautious_<sym_bias>
      neutral symbol   → neutral
    """
    if sym_bias == "neutral":
        return "neutral"
    if sym_alignment == "aligned":
        return f"strong_{sym_bias}"
    if sym_alignment == "neutral":
        return sym_bias
    return f"cautious_{sym_bias}"


def decision_confidence(
    sym_alignment: str,
    sym_bias: str,
    trend_cnt: int,
    rsi: int,
    regime_score: float,
) -> str:
    """
    Three-tier confidence:
      high     — aligned + mature trend (>=4w) + strong regime (|score|>=0.30) + RSI confirms
      low      — neutral symbol OR divergent + weak regime
      moderate — everything else
    """
    if sym_bias == "neutral":
        return "low"

    abs_regime = abs(regime_score)

    if (
        sym_alignment == "aligned"
        and trend_cnt >= 4
        and abs_regime >= 0.30
    ):
        bullish_rsi_ok = sym_bias == "bullish" and rsi >= 100
        bearish_rsi_ok = sym_bias == "bearish" and rsi < 100
        if bullish_rsi_ok or bearish_rsi_ok:
            return "high"

    if sym_alignment == "divergent" and abs_regime < 0.10:
        return "low"

    return "moderate"


def decision_score(
    sym_alignment: str,
    sym_bias: str,
    trend_cnt: int,
    rsi: int,
    regime_score: float,
) -> float:
    """
    Composite 0–1 score. Returns 0.0 for neutral symbols.

    Components:
      alignment        → 0.40 / 0.20 / 0.00
      regime strength  → up to 0.30 (abs(regime_score) * 0.5, capped)
      trend maturity   → 0.15 / 0.10 / 0.05 / 0.00
      RSI confirmation → 0.15 / 0.08 / 0.00
    """
    if sym_bias == "neutral":
        return 0.0

    if sym_alignment == "aligned":
        score = 0.40
    elif sym_alignment == "neutral":
        score = 0.20
    else:  # divergent
        score = 0.0

    score += min(0.30, abs(regime_score) * 0.5)

    if trend_cnt >= 8:
        score += 0.15
    elif trend_cnt >= 4:
        score += 0.10
    elif trend_cnt >= 2:
        score += 0.05

    if sym_bias == "bullish":
        if rsi >= 110:
            score += 0.15
        elif rsi >= 100:
            score += 0.08
    else:  # bearish
        if rsi < 90:
            score += 0.15
        elif rsi < 100:
            score += 0.08

    return round(min(1.0, score), 4)

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from db import get_engine


logger = logging.getLogger("stocktrends_api.stocktrends_strategies")
router = APIRouter(prefix="/stocktrends", tags=["stocktrends-strategies"])


class StockTrendsStrategyConditionCounts(BaseModel):
    buy: int = Field(..., description="Number of declared buy-condition metadata rows.")
    sell: int = Field(..., description="Number of declared sell-condition metadata rows.")
    total: int = Field(..., description="Total declared condition metadata rows.")


class StockTrendsStrategySummary(BaseModel):
    strategy_id: int = Field(..., description="Legacy Stock Trends strategy identifier.")
    description: str | None = Field(default=None, description="Legacy Stock Trends strategy description.")
    investment_amount: float | None = Field(
        default=None,
        description="Declared investment amount per position for this strategy.",
    )
    transaction_cost_pct: float | None = Field(
        default=None,
        description="Declared transaction-cost percentage estimate per trade side.",
    )
    round_trip_transaction_cost_pct: float | None = Field(
        default=None,
        description="Approximate round-trip transaction-cost percentage derived from the per-side estimate.",
    )
    stop_loss_pct: float | None = Field(default=None, description="Declared stop-loss percentage.")
    stop_loss_minimum: float | None = Field(default=None, description="Declared minimum stop-loss value.")
    condition_counts: StockTrendsStrategyConditionCounts


class StockTrendsStrategyListResponse(BaseModel):
    request_id: str
    count: int
    data: list[StockTrendsStrategySummary]


class StockTrendsStrategyCondition(BaseModel):
    sequence: int = Field(..., description="Deterministic sequence within the buy or sell condition group.")
    left_side: str | None = Field(default=None, description="Legacy left-side condition expression.")
    operator: str | None = Field(default=None, description="Legacy condition operator.")
    right_side: str | None = Field(default=None, description="Legacy right-side condition expression.")
    sell_trigger: str | None = Field(default=None, description="Legacy sell-trigger code attached to sell rows.")
    legacy_expression: str | None = Field(
        default=None,
        description="Null-safe legacy expression assembled as left_side, operator, and right_side metadata.",
    )


class StockTrendsStrategyConditions(BaseModel):
    buy: list[StockTrendsStrategyCondition]
    sell: list[StockTrendsStrategyCondition]


class StockTrendsStrategyPublicVerification(BaseModel):
    related_portfolios_endpoint: str = Field(
        ...,
        description="Public endpoint for official Stock Trends model portfolio metadata.",
    )
    portfolio_strategy_endpoint_template: str = Field(
        ...,
        description="Public endpoint template for portfolio-to-strategy provenance.",
    )
    current_live_holdings_excluded: bool = Field(
        ...,
        description="True when current live holdings are excluded from this metadata surface.",
    )
    conditions_are_metadata_not_executable_api: bool = Field(
        ...,
        description="True when strategy conditions are exposed only as provenance metadata.",
    )


class StockTrendsStrategyDetailData(BaseModel):
    strategy_id: int
    description: str | None
    investment_amount: float | None
    transaction_cost_pct: float | None
    round_trip_transaction_cost_pct: float | None
    stop_loss_pct: float | None
    stop_loss_minimum: float | None
    conditions: StockTrendsStrategyConditions
    public_verification: StockTrendsStrategyPublicVerification


class StockTrendsStrategyDetailResponse(BaseModel):
    request_id: str
    strategy_id: int
    data: StockTrendsStrategyDetailData


class StockTrendsPortfolioStrategyPortfolio(BaseModel):
    port_id: int = Field(..., description="Official Stock Trends portfolio identifier.")
    name: str | None = Field(default=None, description="Official Stock Trends portfolio name.")
    strategy_id: int | None = Field(default=None, description="Legacy strategy identifier configured for the portfolio.")
    selection_universe: str | None = Field(
        default=None,
        description="Stock Trends strategy selection/filter universe configured for the portfolio.",
    )


class StockTrendsPortfolioStrategyData(BaseModel):
    strategy_id: int
    description: str | None
    investment_amount: float | None
    transaction_cost_pct: float | None
    round_trip_transaction_cost_pct: float | None
    stop_loss_pct: float | None
    stop_loss_minimum: float | None
    conditions: StockTrendsStrategyConditions


class StockTrendsPortfolioStrategyVerification(BaseModel):
    portfolio_metadata_endpoint: str
    portfolio_returns_endpoint: str
    historical_positions_endpoint: str
    summary_endpoint: str
    current_live_holdings_excluded: bool
    current_matching_candidates_excluded: bool
    conditions_are_metadata_not_executable_api: bool


class StockTrendsPortfolioStrategyResponse(BaseModel):
    request_id: str
    port_id: int
    portfolio: StockTrendsPortfolioStrategyPortfolio
    strategy: StockTrendsPortfolioStrategyData
    verification: StockTrendsPortfolioStrategyVerification


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _to_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if text_value else None


def _round_trip_transaction_cost_pct(value: Any) -> float | None:
    cost = _to_decimal(value)
    if cost is None:
        return None
    return float(cost * Decimal("2"))


def _legacy_expression(left_side: Any, operator: Any, right_side: Any) -> str | None:
    parts = [
        str(value).strip()
        for value in (left_side, operator, right_side)
        if value is not None and str(value).strip()
    ]
    return " ".join(parts) if parts else None


def _raise_db_query_failed(request: Request, exc: Exception) -> None:
    logger.exception(
        "Stock Trends strategy metadata query failed; request_id=%s",
        request.state.request_id,
        exc_info=True,
    )
    raise HTTPException(
        status_code=500,
        detail={
            "request_id": request.state.request_id,
            "error": "db_query_failed",
            "message": "Database query failed.",
        },
    )


def _strategy_summary_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    transaction_cost_pct = _first_value(data, "transaction_cost_pct", "TransactionCostPct")
    buy_count = _to_int(_first_value(data, "buy_condition_count")) or 0
    sell_count = _to_int(_first_value(data, "sell_condition_count")) or 0
    total_count = _to_int(_first_value(data, "total_condition_count")) or 0
    return {
        "strategy_id": int(_first_value(data, "strategy_id", "StrategyId")),
        "description": _first_value(data, "description", "Description"),
        "investment_amount": _to_float(_first_value(data, "investment_amount", "InvestmentAmt")),
        "transaction_cost_pct": _to_float(transaction_cost_pct),
        "round_trip_transaction_cost_pct": _round_trip_transaction_cost_pct(transaction_cost_pct),
        "stop_loss_pct": _to_float(_first_value(data, "stop_loss_pct", "StopLossPct")),
        "stop_loss_minimum": _to_float(_first_value(data, "stop_loss_minimum", "StopLossMinimum")),
        "condition_counts": {
            "buy": buy_count,
            "sell": sell_count,
            "total": total_count,
        },
    }


def _strategy_base_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    transaction_cost_pct = _first_value(data, "transaction_cost_pct", "TransactionCostPct")
    return {
        "strategy_id": int(_first_value(data, "strategy_id", "StrategyId")),
        "description": _first_value(data, "description", "Description"),
        "investment_amount": _to_float(_first_value(data, "investment_amount", "InvestmentAmt")),
        "transaction_cost_pct": _to_float(transaction_cost_pct),
        "round_trip_transaction_cost_pct": _round_trip_transaction_cost_pct(transaction_cost_pct),
        "stop_loss_pct": _to_float(_first_value(data, "stop_loss_pct", "StopLossPct")),
        "stop_loss_minimum": _to_float(_first_value(data, "stop_loss_minimum", "StopLossMinimum")),
    }


def _condition_from_row(row: Any, sequence: int) -> dict[str, Any]:
    data = dict(row)
    left_side = _first_value(data, "left_side", "LeftSide")
    operator = _first_value(data, "operator", "Operator")
    right_side = _first_value(data, "right_side", "RightSide")
    return {
        "sequence": sequence,
        "left_side": _to_optional_string(left_side),
        "operator": _to_optional_string(operator),
        "right_side": _to_optional_string(right_side),
        "sell_trigger": _to_optional_string(_first_value(data, "sell_trigger")),
        "legacy_expression": _legacy_expression(left_side, operator, right_side),
    }


def _conditions_from_rows(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"buy": [], "sell": []}
    sequence_by_group = {"buy": 0, "sell": 0}

    for row in rows:
        data = dict(row)
        buy_sell = str(_first_value(data, "buy_sell", "BuySell") or "").strip().upper()
        if buy_sell == "B":
            group = "buy"
        elif buy_sell == "S":
            group = "sell"
        else:
            continue

        sequence_by_group[group] += 1
        grouped[group].append(_condition_from_row(row, sequence_by_group[group]))

    return grouped


def _public_verification() -> dict[str, Any]:
    return {
        "related_portfolios_endpoint": "/v1/stocktrends/portfolios",
        "portfolio_strategy_endpoint_template": "/v1/stocktrends/portfolios/{port_id}/strategy",
        "current_live_holdings_excluded": True,
        "conditions_are_metadata_not_executable_api": True,
    }


def _portfolio_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "port_id": int(data["port_id"]),
        "name": data.get("name"),
        "strategy_id": _to_int(data.get("strategy_id")),
        "selection_universe": data.get("index_symbols"),
    }


def _strategy_detail_payload(strategy_row: Any, condition_rows: list[Any]) -> dict[str, Any]:
    payload = _strategy_base_from_row(strategy_row)
    payload["conditions"] = _conditions_from_rows(condition_rows)
    return payload


def _fetch_strategy(conn: Any, strategy_id: int) -> Any:
    strategy_sql = text(
        """
        SELECT
            StrategyId AS strategy_id,
            Description AS description,
            InvestmentAmt AS investment_amount,
            TransactionCostPct AS transaction_cost_pct,
            StopLossPct AS stop_loss_pct,
            StopLossMinimum AS stop_loss_minimum
        FROM Strategy
        WHERE StrategyId = :strategy_id
        LIMIT 1
        """
    )
    return conn.execute(strategy_sql, {"strategy_id": strategy_id}).mappings().first()


def _fetch_strategy_conditions(conn: Any, strategy_id: int) -> list[Any]:
    conditions_sql = text(
        """
        SELECT
            StrategyId AS strategy_id,
            BuySell AS buy_sell,
            LeftSide AS left_side,
            Operator AS operator,
            RightSide AS right_side,
            sell_trigger AS sell_trigger
        FROM StrategyCondition
        WHERE StrategyId = :strategy_id
        ORDER BY StrategyId ASC, BuySell ASC, LeftSide ASC, Operator ASC, RightSide ASC, sell_trigger ASC
        """
    )
    return conn.execute(conditions_sql, {"strategy_id": strategy_id}).mappings().all()


@router.get(
    "/strategies",
    response_model=StockTrendsStrategyListResponse,
    summary="List official Stock Trends strategy metadata",
    description=(
        "Public/free strategy metadata for official Stock Trends model portfolios. "
        "Returns declared buy/sell condition counts and economic assumptions for "
        "provenance and verification. Conditions are metadata, not executable APIs; "
        "this route does not evaluate current matching stocks and does not return "
        "current live holdings."
    ),
)
def list_stocktrends_strategies(request: Request):
    sql = text(
        """
        SELECT
            s.StrategyId AS strategy_id,
            s.Description AS description,
            s.InvestmentAmt AS investment_amount,
            s.TransactionCostPct AS transaction_cost_pct,
            s.StopLossPct AS stop_loss_pct,
            s.StopLossMinimum AS stop_loss_minimum,
            SUM(CASE WHEN sc.BuySell = 'B' THEN 1 ELSE 0 END) AS buy_condition_count,
            SUM(CASE WHEN sc.BuySell = 'S' THEN 1 ELSE 0 END) AS sell_condition_count,
            COUNT(sc.StrategyId) AS total_condition_count
        FROM Strategy s
        LEFT JOIN StrategyCondition sc
            ON sc.StrategyId = s.StrategyId
        GROUP BY
            s.StrategyId,
            s.Description,
            s.InvestmentAmt,
            s.TransactionCostPct,
            s.StopLossPct,
            s.StopLossMinimum
        ORDER BY s.StrategyId ASC
        """
    )

    engine = get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()
    except Exception as exc:
        _raise_db_query_failed(request, exc)

    data = [_strategy_summary_from_row(row) for row in rows]
    return {
        "request_id": request.state.request_id,
        "count": len(data),
        "data": data,
    }


@router.get(
    "/strategies/{strategy_id}",
    response_model=StockTrendsStrategyDetailResponse,
    summary="Get official Stock Trends strategy metadata",
    description=(
        "Public/free strategy metadata for one official Stock Trends strategy. "
        "Returns declared economic assumptions and legacy buy/sell condition "
        "expressions for portfolio provenance. These conditions are metadata and "
        "are not executable query endpoints; this route does not evaluate current "
        "matches, current buy candidates, current sell candidates, or current live "
        "holdings."
    ),
)
def get_stocktrends_strategy(
    request: Request,
    strategy_id: int = Path(..., ge=1, description="Legacy Stock Trends strategy identifier."),
):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            strategy_row = _fetch_strategy(conn, strategy_id)
            if not strategy_row:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "request_id": request.state.request_id,
                        "error": "strategy_not_found",
                        "strategy_id": strategy_id,
                    },
                )
            condition_rows = _fetch_strategy_conditions(conn, strategy_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_db_query_failed(request, exc)

    data = _strategy_detail_payload(strategy_row, condition_rows)
    data["public_verification"] = _public_verification()
    return {
        "request_id": request.state.request_id,
        "strategy_id": strategy_id,
        "data": data,
    }


@router.get(
    "/portfolios/{port_id}/strategy",
    response_model=StockTrendsPortfolioStrategyResponse,
    summary="Get official Stock Trends portfolio strategy provenance",
    description=(
        "Public/free portfolio-to-strategy provenance for one live official Stock "
        "Trends model portfolio. Joins the portfolio strategy identifier to the "
        "declared strategy metadata and legacy buy/sell condition expressions. "
        "Conditions are metadata, not executable APIs; this route does not return "
        "current matching stocks, current live holdings, current buy candidates, "
        "or current sell candidates."
    ),
)
def get_stocktrends_portfolio_strategy(
    request: Request,
    port_id: int = Path(..., ge=1, description="Official Stock Trends portfolio identifier."),
):
    portfolio_sql = text(
        """
        SELECT
            port_id,
            name,
            strategy_id,
            index_symbols,
            status
        FROM stp_ports
        WHERE port_id = :port_id
          AND status = 1
        LIMIT 1
        """
    )

    engine = get_engine()
    try:
        with engine.connect() as conn:
            portfolio_row = conn.execute(portfolio_sql, {"port_id": port_id}).mappings().first()
            if not portfolio_row:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "request_id": request.state.request_id,
                        "error": "portfolio_not_found",
                        "port_id": port_id,
                    },
                )

            portfolio = _portfolio_from_row(portfolio_row)
            strategy_id = portfolio["strategy_id"]
            if strategy_id is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "request_id": request.state.request_id,
                        "error": "portfolio_strategy_not_found",
                        "port_id": port_id,
                    },
                )

            strategy_row = _fetch_strategy(conn, strategy_id)
            if not strategy_row:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "request_id": request.state.request_id,
                        "error": "strategy_not_found",
                        "strategy_id": strategy_id,
                        "port_id": port_id,
                    },
                )
            condition_rows = _fetch_strategy_conditions(conn, strategy_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_db_query_failed(request, exc)

    return {
        "request_id": request.state.request_id,
        "port_id": port_id,
        "portfolio": portfolio,
        "strategy": _strategy_detail_payload(strategy_row, condition_rows),
        "verification": {
            "portfolio_metadata_endpoint": f"/v1/stocktrends/portfolios/{port_id}",
            "portfolio_returns_endpoint": f"/v1/stocktrends/portfolios/{port_id}/returns",
            "historical_positions_endpoint": f"/v1/stocktrends/portfolios/{port_id}/positions/history",
            "summary_endpoint": f"/v1/stocktrends/portfolios/{port_id}/summary",
            "current_live_holdings_excluded": True,
            "current_matching_candidates_excluded": True,
            "conditions_are_metadata_not_executable_api": True,
        },
    }

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _compute_default_summary(
    conn,
    *,
    selections_router,
    signal_id: str,
    horizon: str,
    exchange: str | None,
    limit_rank: int | None,
) -> dict[str, Any]:
    latest_mature_weekdate = selections_router._latest_stim_select_mature_outcome_date(conn)
    if latest_mature_weekdate is None:
        raise RuntimeError("No mature ST-IM Select outcome date was found.")

    start_date = selections_router._subtract_years(
        latest_mature_weekdate,
        selections_router.STIM_SELECT_OUTCOME_DEFAULT_WINDOW_YEARS,
    )

    params: dict[str, Any] = {}
    where = selections_router._stim_select_outcomes_base_where(
        ex=exchange,
        start_date=start_date,
        end_date=latest_mature_weekdate,
        params=params,
    )
    if limit_rank is not None:
        params["limit_rank"] = int(limit_rank)

    aggregate_row = conn.execute(
        selections_router._stim_select_outcomes_aggregate_sql(where=where, limit_rank=limit_rank),
        params,
    ).mappings().first()
    value_rows = conn.execute(
        selections_router._stim_select_outcomes_values_sql(where=where, limit_rank=limit_rank),
        params,
    ).mappings().all()

    aggregate = dict(aggregate_row or {})
    count = selections_router._to_int_or_zero(aggregate.get("outcome_count"))
    positive_count = selections_router._to_int_or_zero(aggregate.get("positive_return_count"))
    outperform_count = selections_router._to_int_or_zero(aggregate.get("outperform_base_count"))
    outcome_values = [
        value
        for row in value_rows
        if (value := selections_router._to_decimal(dict(row).get("fpr_chg13"))) is not None
    ]
    median_fpr_chg13 = median(outcome_values) if outcome_values else None

    return {
        "signal_id": signal_id,
        "horizon": horizon,
        "start_date": start_date,
        "end_date": latest_mature_weekdate,
        "exchange": exchange,
        "limit_rank": limit_rank,
        "default_window_applied": True,
        "count": count,
        "first_weekdate": aggregate.get("first_weekdate"),
        "latest_weekdate": aggregate.get("latest_weekdate"),
        "average_fpr_chg13": aggregate.get("average_fpr_chg13"),
        "median_fpr_chg13": median_fpr_chg13,
        "positive_return_count": positive_count,
        "positive_return_rate": _rate(positive_count, count),
        "outperform_base_count": outperform_count,
        "outperform_base_rate": _rate(outperform_count, count),
        "base_period_mean_13wk": Decimal(str(selections_router.STIM_SELECT_BASE_13WK)),
        "generated_at": datetime.utcnow(),
        "source_latest_mature_weekdate": latest_mature_weekdate,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the precomputed ST-IM Select outcome summary cache."
    )
    parser.add_argument(
        "--exchange",
        action="append",
        help=(
            "Optional exchange filter to cache. Repeat for multiple exchanges. "
            "Omit to refresh the all-exchange default summary. Valid values: A, B, N, Q, T."
        ),
    )
    parser.add_argument(
        "--limit-rank",
        action="append",
        type=int,
        help=(
            "Per-week prob13wk rank cutoff to cache. Repeat for multiple cutoffs. "
            "Omit to refresh both the unranked summary and limit_rank=10."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    from db import get_engine
    from routers import selections as selections_router
    from services import stim_select_outcome_summary_cache as cache_repo

    exchanges = [exchange.upper() for exchange in args.exchange] if args.exchange else [None]
    limit_ranks = args.limit_rank if args.limit_rank is not None else [None, 10]
    invalid_exchanges = sorted(
        exchange
        for exchange in exchanges
        if exchange is not None and exchange not in selections_router.STIM_SELECT_OUTCOME_EXCHANGES
    )
    if invalid_exchanges:
        raise SystemExit(f"Invalid exchange value(s): {', '.join(invalid_exchanges)}")

    engine = get_engine()
    with engine.begin() as conn:
        cache_repo.create_stim_select_outcome_summary_cache_table(conn)
        for exchange in exchanges:
            for limit_rank in limit_ranks:
                record = _compute_default_summary(
                    conn,
                    selections_router=selections_router,
                    signal_id=cache_repo.STIM_SELECT_OUTCOME_CACHE_SIGNAL_ID,
                    horizon=cache_repo.STIM_SELECT_OUTCOME_CACHE_HORIZON,
                    exchange=exchange,
                    limit_rank=limit_rank,
                )
                summary_key = cache_repo.upsert_stim_select_outcome_summary_cache(conn, record)
                print(
                    "refreshed",
                    summary_key,
                    "count=",
                    record["count"],
                    "start_date=",
                    record["start_date"],
                    "end_date=",
                    record["end_date"],
                )


if __name__ == "__main__":
    main()

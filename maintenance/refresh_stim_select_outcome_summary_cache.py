from __future__ import annotations

import argparse
from datetime import datetime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the durable ST-IM Select outcome summary table."
    )
    parser.add_argument(
        "--exchange",
        action="append",
        help=(
            "Optional exchange filter to refresh. Repeat for multiple exchanges. "
            "Omit to refresh the all-exchange default summary. Valid values: A, B, N, Q, T."
        ),
    )
    parser.add_argument(
        "--limit-rank",
        action="append",
        type=int,
        help=(
            "Per-week prob13wk rank cutoff to refresh. Repeat for multiple cutoffs. "
            "Omit to refresh both the unranked summary and limit_rank=10."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    from db import get_engine
    from services import stim_select_outcome_summary as summary_service

    exchanges = [exchange.upper() for exchange in args.exchange] if args.exchange else [None]
    limit_ranks = args.limit_rank if args.limit_rank is not None else [None, 10]
    invalid_exchanges = sorted(
        exchange
        for exchange in exchanges
        if exchange is not None and exchange not in summary_service.STIM_SELECT_OUTCOME_EXCHANGES
    )
    if invalid_exchanges:
        raise SystemExit(f"Invalid exchange value(s): {', '.join(invalid_exchanges)}")

    engine = get_engine()
    with engine.connect() as conn:
        summary_service.create_stim_select_outcome_summary_table(conn)

    generated_at = datetime.utcnow()
    with engine.begin() as conn:
        for exchange in exchanges:
            for limit_rank in limit_ranks:
                record = summary_service.compute_summary_record(
                    conn,
                    exchange=exchange,
                    limit_rank=limit_rank,
                    generated_at=generated_at,
                )
                summary_key = summary_service.replace_stim_select_outcome_summary(conn, record)
                print(
                    "refreshed",
                    summary_key,
                    "count=",
                    record["count"],
                    "start_date=",
                    record["start_date"],
                    "end_date=",
                    record["end_date"],
                    "generated_at=",
                    generated_at.isoformat(timespec="seconds"),
                )


if __name__ == "__main__":
    main()

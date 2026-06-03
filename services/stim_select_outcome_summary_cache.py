from __future__ import annotations

from typing import Any

from sqlalchemy import text

STIM_SELECT_OUTCOME_SUMMARY_CACHE_TABLE = "stim_select_outcome_summary_cache"
STIM_SELECT_OUTCOME_CACHE_SIGNAL_ID = "stim_select"
STIM_SELECT_OUTCOME_CACHE_HORIZON = "13w"
STIM_SELECT_OUTCOME_CACHE_DEFAULT_WINDOW = "trailing_10y"


def build_default_summary_key(*, exchange: str | None, limit_rank: int | None) -> str:
    exchange_part = exchange or "all"
    rank_part = "all" if limit_rank is None else str(int(limit_rank))
    return (
        f"{STIM_SELECT_OUTCOME_CACHE_SIGNAL_ID}:"
        f"{STIM_SELECT_OUTCOME_CACHE_HORIZON}:"
        f"default_{STIM_SELECT_OUTCOME_CACHE_DEFAULT_WINDOW}:"
        f"exchange={exchange_part}:"
        f"limit_rank={rank_part}"
    )


def create_stim_select_outcome_summary_cache_table(conn) -> None:
    conn.execute(
        text(f"""
            CREATE TABLE IF NOT EXISTS {STIM_SELECT_OUTCOME_SUMMARY_CACHE_TABLE} (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                summary_key VARCHAR(191) NOT NULL,
                signal_id VARCHAR(64) NOT NULL,
                horizon VARCHAR(16) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                exchange VARCHAR(8) NULL,
                limit_rank INT NULL,
                default_window_applied TINYINT(1) NOT NULL DEFAULT 1,
                `count` BIGINT NOT NULL DEFAULT 0,
                first_weekdate DATE NULL,
                latest_weekdate DATE NULL,
                average_fpr_chg13 DECIMAL(18, 6) NULL,
                median_fpr_chg13 DECIMAL(18, 6) NULL,
                positive_return_count BIGINT NOT NULL DEFAULT 0,
                positive_return_rate DECIMAL(18, 10) NOT NULL DEFAULT 0,
                outperform_base_count BIGINT NOT NULL DEFAULT 0,
                outperform_base_rate DECIMAL(18, 10) NOT NULL DEFAULT 0,
                base_period_mean_13wk DECIMAL(10, 4) NOT NULL,
                generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source_latest_mature_weekdate DATE NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_stim_select_outcome_summary_cache_key (summary_key),
                KEY idx_stim_select_outcome_summary_cache_lookup (
                    signal_id,
                    horizon,
                    default_window_applied,
                    exchange,
                    limit_rank
                )
            )
        """)
    )


def fetch_default_stim_select_outcome_summary_cache(
    conn,
    *,
    exchange: str | None,
    limit_rank: int | None,
) -> dict[str, Any] | None:
    summary_key = build_default_summary_key(exchange=exchange, limit_rank=limit_rank)
    row = conn.execute(
        text(f"""
            SELECT
                id,
                summary_key,
                signal_id,
                horizon,
                start_date,
                end_date,
                exchange,
                limit_rank,
                default_window_applied,
                `count` AS outcome_count,
                first_weekdate,
                latest_weekdate,
                average_fpr_chg13,
                median_fpr_chg13,
                positive_return_count,
                positive_return_rate,
                outperform_base_count,
                outperform_base_rate,
                base_period_mean_13wk,
                generated_at,
                source_latest_mature_weekdate
            FROM {STIM_SELECT_OUTCOME_SUMMARY_CACHE_TABLE}
            WHERE summary_key = :summary_key
              AND signal_id = :signal_id
              AND horizon = :horizon
              AND default_window_applied = 1
            LIMIT 1
        """),
        {
            "summary_key": summary_key,
            "signal_id": STIM_SELECT_OUTCOME_CACHE_SIGNAL_ID,
            "horizon": STIM_SELECT_OUTCOME_CACHE_HORIZON,
        },
    ).mappings().first()
    return dict(row) if row else None


def upsert_stim_select_outcome_summary_cache(conn, record: dict[str, Any]) -> str:
    summary_key = record.get("summary_key") or build_default_summary_key(
        exchange=record.get("exchange"),
        limit_rank=record.get("limit_rank"),
    )
    params = {
        **record,
        "summary_key": summary_key,
        "signal_id": record.get("signal_id", STIM_SELECT_OUTCOME_CACHE_SIGNAL_ID),
        "horizon": record.get("horizon", STIM_SELECT_OUTCOME_CACHE_HORIZON),
        "default_window_applied": 1 if record.get("default_window_applied", True) else 0,
    }

    conn.execute(
        text(f"""
            INSERT INTO {STIM_SELECT_OUTCOME_SUMMARY_CACHE_TABLE} (
                summary_key,
                signal_id,
                horizon,
                start_date,
                end_date,
                exchange,
                limit_rank,
                default_window_applied,
                `count`,
                first_weekdate,
                latest_weekdate,
                average_fpr_chg13,
                median_fpr_chg13,
                positive_return_count,
                positive_return_rate,
                outperform_base_count,
                outperform_base_rate,
                base_period_mean_13wk,
                generated_at,
                source_latest_mature_weekdate
            )
            VALUES (
                :summary_key,
                :signal_id,
                :horizon,
                :start_date,
                :end_date,
                :exchange,
                :limit_rank,
                :default_window_applied,
                :count,
                :first_weekdate,
                :latest_weekdate,
                :average_fpr_chg13,
                :median_fpr_chg13,
                :positive_return_count,
                :positive_return_rate,
                :outperform_base_count,
                :outperform_base_rate,
                :base_period_mean_13wk,
                :generated_at,
                :source_latest_mature_weekdate
            )
            ON DUPLICATE KEY UPDATE
                signal_id = VALUES(signal_id),
                horizon = VALUES(horizon),
                start_date = VALUES(start_date),
                end_date = VALUES(end_date),
                exchange = VALUES(exchange),
                limit_rank = VALUES(limit_rank),
                default_window_applied = VALUES(default_window_applied),
                `count` = VALUES(`count`),
                first_weekdate = VALUES(first_weekdate),
                latest_weekdate = VALUES(latest_weekdate),
                average_fpr_chg13 = VALUES(average_fpr_chg13),
                median_fpr_chg13 = VALUES(median_fpr_chg13),
                positive_return_count = VALUES(positive_return_count),
                positive_return_rate = VALUES(positive_return_rate),
                outperform_base_count = VALUES(outperform_base_count),
                outperform_base_rate = VALUES(outperform_base_rate),
                base_period_mean_13wk = VALUES(base_period_mean_13wk),
                generated_at = VALUES(generated_at),
                source_latest_mature_weekdate = VALUES(source_latest_mature_weekdate)
        """),
        params,
    )
    return summary_key

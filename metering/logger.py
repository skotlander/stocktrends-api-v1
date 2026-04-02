import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from db import get_metering_engine

logger = logging.getLogger("stocktrends_api.metering.logger")


INSERT_REQUEST_LOG_SQL = text("""
INSERT INTO api_request_logs (
    event_time_utc,
    request_id,
    environment,
    api_key_id,
    customer_id,
    subscription_id,
    plan_code,
    actor_type,
    workflow_type,
    agent_identifier,
    agent_id,
    endpoint_path,
    route_template,
    endpoint_family,
    http_method,
    query_string,
    symbol,
    exchange,
    symbol_exchange,
    status_code,
    success,
    latency_ms,
    response_size_bytes,
    client_ip,
    user_agent,
    referer,
    is_metered,
    is_billable,
    payment_rail,
    payment_method,
    pricing_rule_id,
    error_code,
    notes
) VALUES (
    :event_time_utc,
    :request_id,
    :environment,
    :api_key_id,
    :customer_id,
    :subscription_id,
    :plan_code,
    :actor_type,
    :workflow_type,
    :agent_identifier,
    :agent_id,
    :endpoint_path,
    :route_template,
    :endpoint_family,
    :http_method,
    :query_string,
    :symbol,
    :exchange,
    :symbol_exchange,
    :status_code,
    :success,
    :latency_ms,
    :response_size_bytes,
    :client_ip,
    :user_agent,
    :referer,
    :is_metered,
    :is_billable,
    :payment_rail,
    :payment_method,
    :pricing_rule_id,
    :error_code,
    :notes
)
""")


INSERT_REQUEST_LOG_SQL_LEGACY = text("""
INSERT INTO api_request_logs (
    event_time_utc,
    request_id,
    environment,
    api_key_id,
    customer_id,
    subscription_id,
    plan_code,
    actor_type,
    workflow_type,
    agent_identifier,
    agent_id,
    endpoint_path,
    route_template,
    endpoint_family,
    http_method,
    query_string,
    symbol,
    exchange,
    symbol_exchange,
    status_code,
    success,
    latency_ms,
    response_size_bytes,
    client_ip,
    user_agent,
    referer,
    is_metered,
    is_billable,
    payment_method,
    pricing_rule_id,
    error_code,
    notes
) VALUES (
    :event_time_utc,
    :request_id,
    :environment,
    :api_key_id,
    :customer_id,
    :subscription_id,
    :plan_code,
    :actor_type,
    :workflow_type,
    :agent_identifier,
    :agent_id,
    :endpoint_path,
    :route_template,
    :endpoint_family,
    :http_method,
    :query_string,
    :symbol,
    :exchange,
    :symbol_exchange,
    :status_code,
    :success,
    :latency_ms,
    :response_size_bytes,
    :client_ip,
    :user_agent,
    :referer,
    :is_metered,
    :is_billable,
    :payment_method,
    :pricing_rule_id,
    :error_code,
    :notes
)
""")


INSERT_REQUEST_ECONOMICS_SQL = text("""
INSERT INTO api_request_economics (
    request_id,
    customer_id,
    api_key_id,
    pricing_rule_id,
    unit_price_usd,
    billed_amount_usd,
    payment_required,
    payment_rail,
    payment_status,
    payment_method,
    payment_network,
    payment_token,
    payment_amount_native,
    payment_amount_usd,
    payment_reference,
    session_id,
    payment_channel_id,
    agent_id,
    agent_type,
    agent_vendor,
    agent_version,
    request_purpose
) VALUES (
    :request_id,
    :customer_id,
    :api_key_id,
    :pricing_rule_id,
    :unit_price_usd,
    :billed_amount_usd,
    :payment_required,
    :payment_rail,
    :payment_status,
    :payment_method,
    :payment_network,
    :payment_token,
    :payment_amount_native,
    :payment_amount_usd,
    :payment_reference,
    :session_id,
    :payment_channel_id,
    :agent_id,
    :agent_type,
    :agent_vendor,
    :agent_version,
    :request_purpose
)
""")


INSERT_REQUEST_ECONOMICS_SQL_LEGACY = text("""
INSERT INTO api_request_economics (
    request_id,
    customer_id,
    api_key_id,
    pricing_rule_id,
    unit_price_usd,
    billed_amount_usd,
    payment_required,
    payment_status,
    payment_method,
    payment_network,
    payment_token,
    payment_amount_native,
    payment_amount_usd,
    payment_reference,
    session_id,
    payment_channel_id,
    agent_id,
    agent_type,
    agent_vendor,
    agent_version,
    request_purpose
) VALUES (
    :request_id,
    :customer_id,
    :api_key_id,
    :pricing_rule_id,
    :unit_price_usd,
    :billed_amount_usd,
    :payment_required,
    :payment_status,
    :payment_method,
    :payment_network,
    :payment_token,
    :payment_amount_native,
    :payment_amount_usd,
    :payment_reference,
    :session_id,
    :payment_channel_id,
    :agent_id,
    :agent_type,
    :agent_vendor,
    :agent_version,
    :request_purpose
)
""")


_request_log_legacy_warned = False
_request_econ_legacy_warned = False


def _is_missing_payment_rail_column_error(exc: Exception) -> bool:
    if not isinstance(exc, DBAPIError):
        return False

    message_parts = [str(exc)]

    if getattr(exc, "orig", None) is not None:
        message_parts.append(str(exc.orig))

    message = " ".join(message_parts).lower()
    return "payment_rail" in message and (
        "unknown column" in message
        or "invalid column" in message
        or "no column named" in message
    )


def _warn_legacy_fallback(table_name: str) -> None:
    global _request_log_legacy_warned, _request_econ_legacy_warned

    if table_name == "api_request_logs":
        if _request_log_legacy_warned:
            return
        _request_log_legacy_warned = True
    elif table_name == "api_request_economics":
        if _request_econ_legacy_warned:
            return
        _request_econ_legacy_warned = True

    logger.warning(
        "Metering schema mismatch detected for %s: missing payment_rail column. "
        "Falling back to legacy insert without payment_rail until the schema migration is applied.",
        table_name,
    )


def log_api_request_event(event: dict) -> None:
    engine = get_metering_engine()
    try:
        with engine.begin() as conn:
            conn.execute(INSERT_REQUEST_LOG_SQL, event)
    except DBAPIError as exc:
        if not _is_missing_payment_rail_column_error(exc):
            raise

        _warn_legacy_fallback("api_request_logs")
        legacy_event = dict(event)
        legacy_event.pop("payment_rail", None)

        with engine.begin() as conn:
            conn.execute(INSERT_REQUEST_LOG_SQL_LEGACY, legacy_event)


def log_api_request_economics(econ: dict) -> None:
    engine = get_metering_engine()
    try:
        with engine.begin() as conn:
            conn.execute(INSERT_REQUEST_ECONOMICS_SQL, econ)
    except DBAPIError as exc:
        if not _is_missing_payment_rail_column_error(exc):
            raise

        _warn_legacy_fallback("api_request_economics")
        legacy_econ = dict(econ)
        legacy_econ.pop("payment_rail", None)

        with engine.begin() as conn:
            conn.execute(INSERT_REQUEST_ECONOMICS_SQL_LEGACY, legacy_econ)

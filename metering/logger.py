from sqlalchemy import text

from db import get_metering_engine


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


def log_api_request_event(event: dict) -> None:
    engine = get_metering_engine()
    with engine.begin() as conn:
        conn.execute(INSERT_REQUEST_LOG_SQL, event)


def log_api_request_economics(econ: dict) -> None:
    engine = get_metering_engine()
    with engine.begin() as conn:
        conn.execute(INSERT_REQUEST_ECONOMICS_SQL, econ)
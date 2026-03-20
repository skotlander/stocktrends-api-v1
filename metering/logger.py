from sqlalchemy import text

from db import get_metering_engine


INSERT_SQL = text("""
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
    :error_code,
    :notes
)
""")


def log_api_request_event(event: dict) -> None:
    engine = get_metering_engine()
    with engine.begin() as conn:
        conn.execute(INSERT_SQL, event)
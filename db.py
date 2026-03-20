import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine


def _build_mysql_url(
    user: str,
    password: str,
    host: str,
    port: int,
    db_name: str,
) -> str:
    password_escaped = quote_plus(password)
    return f"mysql+mysqlconnector://{user}:{password_escaped}@{host}:{port}/{db_name}"


def _build_engine(user_env, password_env, host_env, port_env, name_env, label, socket_env=None):
    user = os.getenv(user_env)
    password = os.getenv(password_env)
    host = os.getenv(host_env)
    port = int(os.getenv(port_env, 3306))
    db_name = os.getenv(name_env)
    unix_socket = os.getenv(socket_env) if socket_env else None

    if not all([user, password, db_name]):
        raise RuntimeError(f"{label} DB environment variables are not fully configured.")

    if not unix_socket and not host:
        raise RuntimeError(f"{label} DB host is not configured.")

    url = _build_mysql_url(user, password, host or "localhost", port, db_name)

    connect_args = {
        "connection_timeout": 5,
    }

    if unix_socket:
        connect_args["unix_socket"] = unix_socket

    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def get_market_engine():
    return _build_engine(
        user_env="MARKET_DB_USER",
        password_env="MARKET_DB_PASSWORD",
        host_env="MARKET_DB_HOST",
        port_env="MARKET_DB_PORT",
        name_env="MARKET_DB_NAME",
        label="Market",
    )


def get_auth_engine():
    return _build_engine(
        user_env="AUTH_DB_USER",
        password_env="AUTH_DB_PASSWORD",
        host_env="AUTH_DB_HOST",
        port_env="AUTH_DB_PORT",
        name_env="AUTH_DB_NAME",
        label="Auth",
    )


def get_metering_engine():
    return _build_engine(
        user_env="METERING_DB_USER",
        password_env="METERING_DB_PASSWORD",
        host_env="METERING_DB_HOST",
        port_env="METERING_DB_PORT",
        name_env="METERING_DB_NAME",
        label="Metering",
        socket_env="METERING_DB_SOCKET",
    )


# backward-compat helper for older routes not yet refactored
def get_engine():
    return get_market_engine()
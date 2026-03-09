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


def get_market_engine():
    user = os.getenv("MARKET_DB_USER")
    password = os.getenv("MARKET_DB_PASSWORD")
    host = os.getenv("MARKET_DB_HOST")
    port = int(os.getenv("MARKET_DB_PORT", 3306))
    db_name = os.getenv("MARKET_DB_NAME")

    if not all([user, password, host, db_name]):
        raise RuntimeError("Market DB environment variables are not fully configured.")

    url = _build_mysql_url(user, password, host, port, db_name)
    return create_engine(
    url,
    pool_pre_ping=True,
    connect_args={
        "connection_timeout": 5,
    },
)


def get_auth_engine():
    user = os.getenv("AUTH_DB_USER")
    password = os.getenv("AUTH_DB_PASSWORD")
    host = os.getenv("AUTH_DB_HOST")
    port = int(os.getenv("AUTH_DB_PORT", 3306))
    db_name = os.getenv("AUTH_DB_NAME")

    if not all([user, password, host, db_name]):
        raise RuntimeError("Auth DB environment variables are not fully configured.")

    url = _build_mysql_url(user, password, host, port, db_name)
    return create_engine(
    url,
    pool_pre_ping=True,
    connect_args={
        "connection_timeout": 5,
    },
)


# backward-compat helper for older routes not yet refactored
def get_engine():
    return get_market_engine()
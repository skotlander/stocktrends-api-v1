import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME")

def get_engine():
    password = quote_plus(DB_PASSWORD)
    url = f"mysql+mysqlconnector://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url, pool_pre_ping=True)

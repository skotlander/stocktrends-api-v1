from sqlalchemy import create_engine

DB_USER = "root"
DB_PASSWORD = ""
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "stdata"

def get_engine():
    url = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url, pool_pre_ping=True)
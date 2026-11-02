import os
from sqlalchemy import create_engine

def get_engine():
    user = os.getenv("DB_USER", "ecommerce_user")
    password = os.getenv("DB_PASSWORD", "ecommerce_pass")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    database = os.getenv("DB_NAME", "ecommerce")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url, pool_pre_ping=True)

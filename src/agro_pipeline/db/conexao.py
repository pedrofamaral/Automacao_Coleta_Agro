from functools import lru_cache

from sqlalchemy import Engine, create_engine

from agro_pipeline.config import database_url


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 15})

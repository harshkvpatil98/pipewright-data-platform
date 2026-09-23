from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api_gateway.config import settings
from shared_python.db.slow_query import install_slow_query_logger
from shared_python.storage import build_storage_backend

# A sized pool keeps request latency off the connection handshake. pool_pre_ping
# discards connections a proxy or database restart has already closed, and
# pool_recycle retires them before a server-side idle timeout can do it mid-query.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_timeout=settings.db_pool_timeout_seconds,
)
# Off unless DB_SLOW_QUERY_MS is set; then slow statements are logged with the
# request's correlation id, without echoing every query.
install_slow_query_logger(engine, threshold_ms=settings.db_slow_query_ms)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
storage_backend = build_storage_backend(settings)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_storage_backend():
    return storage_backend

import logging
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncAttrs,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from vigilant_ai.config import settings

logger = logging.getLogger(__name__)

DB_URL = settings.DATABASE_URL
if DB_URL.startswith("sqlite:///"):
    DB_URL = DB_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

engine_args = {
    "echo": False,
    "future": True,
}

if "sqlite" in DB_URL:
    engine_args["connect_args"] = {"check_same_thread": False}
    if ":memory:" in DB_URL:
        engine_args["poolclass"] = StaticPool

engine = create_async_engine(DB_URL, **engine_args)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

class Base(AsyncAttrs, DeclarativeBase):
    pass

async def init_db() -> None:
    try:
        async with engine.begin() as conn:
            from vigilant_ai import models
            logger.info("Initializing database schema...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def close_db() -> None:
    if engine:
        await engine.dispose()
        logger.info("Database connection pool closed.")

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in DB_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

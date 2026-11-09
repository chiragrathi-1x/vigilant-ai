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

# Construct the database URL. Default to SQLite for simplicity as per requirements.
# We use aiosqlite for asynchronous SQLite support.
DB_URL = settings.DATABASE_URL
if DB_URL.startswith("sqlite:///"):
    # Convert standard sqlite sync URL to async if necessary
    DB_URL = DB_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

# Engine configuration
# For SQLite, we often need to handle threading differently than Postgres/MySQL.
# StaticPool is used if we are using :memory: databases to keep the connection alive,
# otherwise, standard pooling applies.
engine_args = {
    "echo": settings.DB_ECHO,
    "future": True,
}

if "sqlite" in DB_URL:
    # SQLite specific tuning
    engine_args["connect_args"] = {"check_same_thread": False}
    # If using an in-memory database, we must use a StaticPool to prevent
    # the database from being deleted when a connection is closed.
    if ":memory:" in DB_URL:
        engine_args["poolclass"] = StaticPool

engine = create_async_engine(DB_URL, **engine_args)

# Create a session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

class Base(AsyncAttrs, DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    Uses SQLAlchemy 2.0 style declarative mapping.
    """
    pass

async def init_db() -> None:
    """
    Initializes the database schema.
    In a production environment with migrations, this might be handled by Alembic,
    but for the vigilant-ai engine, we ensure tables exist on startup.
    """
    try:
        async with engine.begin() as conn:
            # Import models here to ensure they are registered on the Base metadata
            from vigilant_ai import models  # noqa: F401
            
            logger.info("Initializing database schema...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency/Helper to provide an asynchronous session.
    Ensures that the session is properly closed after use.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def close_db() -> None:
    """
    Closes the database engine connections.
    Should be called during application shutdown.
    """
    if engine:
        await engine.dispose()
        logger.info("Database connection pool closed.")

# Logic for enabling WAL mode on SQLite for better concurrent performance
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in DB_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

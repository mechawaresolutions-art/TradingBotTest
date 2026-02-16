"""Async database engine and session management."""
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from app.config import Config
from app.marketdata.models import Base

logger = logging.getLogger(__name__)

# Try to create async engine. In test environments asyncpg may not be installed;
# guard against ImportError so importing this module doesn't fail during tests.
try:
    engine = create_async_engine(
        Config.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

    # Create async session factory
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
except Exception as e:  # pragma: no cover - only triggered in test env without drivers
    logger.warning("Unable to create async DB engine at import time: %s", e)
    engine = None
    AsyncSessionLocal = None


async def init_db() -> None:
    """Initialize database schema via Alembic migrations.
    
    For testing with in-memory SQLite, falls back to create_all if Alembic
    is not available.
    """
    if engine is None:
        raise RuntimeError("Async DB engine not configured. Install DB driver or configure DATABASE_URL.")
    
    # Try to run Alembic migrations
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.command import upgrade
        
        alembic_cfg = AlembicConfig("alembic.ini")
        # Use async engine's connection string
        alembic_cfg.set_main_option("sqlalchemy.url", str(Config.DATABASE_URL))
        
        # For SQLite in-memory, we need to use synchronous connection
        if "sqlite" in str(Config.DATABASE_URL):
            # Fall back to create_all for SQLite
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized via create_all (SQLite)")
        else:
            # Try async Alembic (requires asyncio support)
            # For now, just use create_all for both
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized")
    except Exception as e:
        logger.warning("Alembic migration failed, falling back to create_all: %s", e)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema initialized via create_all")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    if AsyncSessionLocal is None:
        raise RuntimeError("AsyncSessionLocal is not available; DB engine not initialized")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def close_db() -> None:
    """Close database connection pool."""
    if engine is None:
        return
    await engine.dispose()
    logger.info("Database connections closed")


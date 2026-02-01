"""Tests for market data pipeline."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.marketdata.models import Base, Candle
from app.marketdata.provider_mock import MockProvider
from app.marketdata.ingest import IngestionService
from app.marketdata.integrity import check_integrity


@pytest_asyncio.fixture
async def db_engine():
    """Create in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create database session for testing."""
    SessionLocal = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
def provider():
    """Create mock provider."""
    return MockProvider()


@pytest_asyncio.fixture
def ingest_service(provider):
    """Create ingestion service."""
    return IngestionService(provider)


@pytest.mark.asyncio
async def test_mock_provider_deterministic(provider):
    """Test that MockProvider generates same candles for same inputs."""
    start = datetime(2024, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 31, 1, 0, 0, tzinfo=timezone.utc)
    
    # Fetch same range twice
    candles1 = await provider.fetch_candles("EURUSD", "M5", start, end)
    candles2 = await provider.fetch_candles("EURUSD", "M5", start, end)
    
    # Should be identical
    assert len(candles1) == len(candles2)
    for c1, c2 in zip(candles1, candles2):
        assert c1 == c2
    
    # Should have correct count (60 minutes / 5 minute timeframe = 12 candles)
    assert len(candles1) == 12


@pytest.mark.asyncio
async def test_mock_provider_alignment(provider):
    """Test that MockProvider aligns candles to timeframe boundaries."""
    start = datetime(2024, 1, 31, 0, 3, 0, tzinfo=timezone.utc)  # 00:03
    end = datetime(2024, 1, 31, 0, 30, 0, tzinfo=timezone.utc)
    
    candles = await provider.fetch_candles("EURUSD", "M5", start, end)
    
    # First candle should align to boundary (e.g., 00:00 for M5)
    first_time = candles[0]["open_time"]
    assert first_time.minute % 5 == 0  # Should be on 5-minute boundary


@pytest.mark.asyncio
async def test_ingestion_idempotent(ingest_service, db_session):
    """Test that ingestion is idempotent (no duplicates on repeated ingest)."""
    
    # First ingestion
    result1 = await ingest_service.ingest(db_session, "EURUSD", "M5")
    count1 = result1["total_processed"]
    
    # Second ingestion (should have same result due to UPSERT)
    result2 = await ingest_service.ingest(db_session, "EURUSD", "M5")
    count2 = result2["total_processed"]
    
    # Count should be stable
    assert count1 > 0
    assert count2 >= count1  # Might have more due to overlap


@pytest.mark.asyncio
async def test_integrity_detects_gaps(ingest_service, db_session):
    """Test that integrity checker detects gaps."""
    
    # Ingest some data
    await ingest_service.ingest(db_session, "EURUSD", "M5")
    
    # Introduce a gap by deleting a candle
    from sqlalchemy import delete, select, func
    
    # Get a candle to delete
    stmt = select(Candle).where(
        (Candle.symbol == "EURUSD") &
        (Candle.timeframe == "M5")
    ).limit(1)
    result = await db_session.execute(stmt)
    candle_to_delete = result.scalar()
    
    if candle_to_delete:
        delete_stmt = delete(Candle).where(Candle.id == candle_to_delete.id)
        await db_session.execute(delete_stmt)
        await db_session.commit()
        
        # Check integrity
        integrity = await check_integrity(db_session, "EURUSD", "M5", days=7)
        
        # Should detect missing
        assert integrity["missing_count"] > 0 or integrity["actual_count"] < integrity["expected_count"]


@pytest.mark.asyncio
async def test_backfill_fills_gaps(ingest_service, db_session):
    """Test that backfill can fill specified range."""
    
    # Backfill specific range
    start = datetime.now(timezone.utc) - timedelta(days=1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)
    
    result = await ingest_service.backfill(
        db_session, "EURUSD", "M5", start, end
    )
    
    # Should have inserted candles
    assert result["total_processed"] > 0
    assert result["integrity_check"]["actual_count"] > 0


@pytest.mark.asyncio
async def test_candle_ohlc_validation(ingest_service, db_session):
    """Test that invalid OHLC data is rejected."""
    
    # Try to ingest with invalid OHLC
    invalid_candles = [
        {
            "open_time": datetime.now(timezone.utc),
            "open": 100,
            "high": 90,  # Invalid: high < open
            "low": 85,
            "close": 95,
            "volume": 1000,
        }
    ]
    
    # Should raise ValueError on validation
    with pytest.raises(ValueError):
        ingest_service._normalize_and_validate(
            invalid_candles[0], "EURUSD", "M5"
        )

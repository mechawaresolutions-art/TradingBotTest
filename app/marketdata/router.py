"""FastAPI routes for market data endpoints."""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Config
from app.marketdata.db import get_session
from app.marketdata.models import Candle
from app.marketdata.schemas import (
    CandleSchema, CandleListSchema, IntegrityCheckSchema,
    IngestionResultSchema, BackfillResultSchema
)
from app.marketdata.ingest import IngestionService
from app.marketdata.integrity import check_integrity
from app.marketdata.retention import prune_old_candles
from app.marketdata.provider_mock import MockProvider
from app.marketdata.provider_real import RealProvider

logger = logging.getLogger(__name__)

# Create provider instance
if Config.MARKET_DATA_PROVIDER == "mock":
    provider = MockProvider()
elif Config.MARKET_DATA_PROVIDER == "real":
    provider = RealProvider()
else:
    raise ValueError(f"Invalid MARKET_DATA_PROVIDER: {Config.MARKET_DATA_PROVIDER}")

# Create ingestion service
ingest_service = IngestionService(provider)

# Create router
router = APIRouter(prefix="/v1/candles", tags=["market-data"])


# ==== PUBLIC ENDPOINTS ====

@router.get("/latest", response_model=CandleSchema)
async def get_latest_candle(
    symbol: str = Query(Config.SYMBOL),
    timeframe: str = Query(Config.TIMEFRAME),
    session: AsyncSession = Depends(get_session),
) -> CandleSchema:
    """Get latest closed candle from database."""
    stmt = select(Candle).where(
        (Candle.symbol == symbol) &
        (Candle.timeframe == timeframe)
    ).order_by(Candle.open_time.desc()).limit(1)
    
    result = await session.execute(stmt)
    candle = result.scalar()
    
    if not candle:
        raise HTTPException(
            status_code=404,
            detail=f"No candles found for {symbol}/{timeframe}"
        )
    
    return CandleSchema.from_orm(candle)


@router.get("", response_model=CandleListSchema)
async def get_candles(
    symbol: str = Query(Config.SYMBOL),
    timeframe: str = Query(Config.TIMEFRAME),
    start: Optional[str] = Query(None, description="Start time (ISO-8601 UTC)"),
    end: Optional[str] = Query(None, description="End time (ISO-8601 UTC)"),
    limit: int = Query(5000, ge=1, le=10000),
    session: AsyncSession = Depends(get_session),
) -> CandleListSchema:
    """
    Get candles for symbol/timeframe.
    
    - start: inclusive
    - end: exclusive
    - Returns candles in ascending open_time order
    """
    stmt = select(Candle).where(
        (Candle.symbol == symbol) &
        (Candle.timeframe == timeframe)
    )
    
    # Apply time filters
    if start:
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid start datetime format (use ISO-8601)"
            )
        stmt = stmt.where(Candle.open_time >= start_dt)
    
    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid end datetime format (use ISO-8601)"
            )
        stmt = stmt.where(Candle.open_time < end_dt)
    
    stmt = stmt.order_by(Candle.open_time.asc()).limit(limit)
    
    result = await session.execute(stmt)
    candles = result.scalars().all()
    
    candle_schemas = [CandleSchema.from_orm(c) for c in candles]
    earliest = candle_schemas[0].open_time if candle_schemas else None
    latest = candle_schemas[-1].open_time if candle_schemas else None
    
    return CandleListSchema(
        count=len(candle_schemas),
        candles=candle_schemas,
        earliest=earliest,
        latest=latest,
    )


@router.get("/integrity", response_model=IntegrityCheckSchema)
async def check_data_integrity(
    symbol: str = Query(Config.SYMBOL),
    timeframe: str = Query(Config.TIMEFRAME),
    days: int = Query(7, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> IntegrityCheckSchema:
    """
    Check data integrity.
    
    Returns: earliest/latest times, expected vs actual counts,
    missing ranges, duplicate count, completeness flag.
    """
    integrity = await check_integrity(session, symbol, timeframe, days)
    return IntegrityCheckSchema(**integrity)


# ==== ADMIN ENDPOINTS ====

@router.post("/admin/ingest", response_model=IngestionResultSchema)
async def ingest_candles(
    symbol: str = Query(Config.SYMBOL),
    timeframe: str = Query(Config.TIMEFRAME),
    session: AsyncSession = Depends(get_session),
) -> IngestionResultSchema:
    """
    Trigger candle ingestion.
    
    - Fetches from provider (with overlap if DB has data)
    - Validates OHLC constraints
    - Upserts into DB
    - Returns integrity check result
    """
    try:
        result = await ingest_service.ingest(session, symbol, timeframe)
        
        # Add integrity check to result
        integrity = result.pop("integrity_check")
        
        return IngestionResultSchema(
            **result,
            integrity_check=IntegrityCheckSchema(**integrity) if integrity else None
        )
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.post("/admin/backfill", response_model=BackfillResultSchema)
async def backfill_candles(
    symbol: str = Query(Config.SYMBOL),
    timeframe: str = Query(Config.TIMEFRAME),
    start: str = Query(..., description="Start time (ISO-8601 UTC, inclusive)"),
    end: str = Query(..., description="End time (ISO-8601 UTC, exclusive)"),
    session: AsyncSession = Depends(get_session),
) -> BackfillResultSchema:
    """
    Backfill candles for specific range.
    
    - Fetches exact range from provider
    - Validates and upserts
    - Returns integrity check result
    """
    try:
        # Parse datetime strings
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid datetime format: {e}"
            )
        
        result = await ingest_service.backfill(
            session, symbol, timeframe, start_dt, end_dt
        )
        
        # Add integrity check to result
        integrity = result.pop("integrity_check")
        
        return BackfillResultSchema(
            **result,
            integrity_check=IntegrityCheckSchema(**integrity) if integrity else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backfill failed: {str(e)}")


@router.post("/admin/prune")
async def prune_candles(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Prune candles older than CANDLE_RETENTION_DAYS.
    
    Admin-only endpoint for data maintenance.
    """
    try:
        result = await prune_old_candles(session)
        return result
    except Exception as e:
        logger.error(f"Prune failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prune failed: {str(e)}")

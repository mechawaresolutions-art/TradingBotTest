"""Candle ingestion service (fetch, validate, upsert, integrity checks)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.config import Config
from app.marketdata.models import Candle
from app.marketdata.provider_base import MarketDataProvider
from app.marketdata.integrity import check_integrity

logger = logging.getLogger(__name__)

TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


class IngestionService:
    """Service for ingesting and managing candle data."""
    
    def __init__(self, provider: MarketDataProvider) -> None:
        self.provider = provider
    
    async def ingest(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        Ingest candles for symbol/timeframe.
        
        Strategy:
        1. Find latest stored candle's open_time
        2. If DB empty: fetch last INITIAL_BACKFILL_DAYS
        3. If DB has data: fetch from (latest - overlap_delta) up to now
        4. Validate OHLC constraints
        5. Upsert into DB
        6. Run integrity check on recent window
        
        Returns:
            Dict with inserted, updated, total_processed, latest_open_time, missing_ranges
        """
        logger.info(f"Starting ingestion for {symbol}/{timeframe}")
        
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Invalid timeframe: {timeframe}")
        
        # Step 1: Find latest candle in DB
        stmt = select(func.max(Candle.open_time)).where(
            (Candle.symbol == symbol) &
            (Candle.timeframe == timeframe)
        )
        result = await session.execute(stmt)
        latest_stored = result.scalar()
        
        # Step 2: Determine fetch range
        now_utc = datetime.now(timezone.utc)
        candle_minutes = TIMEFRAME_MINUTES[timeframe]
        
        if latest_stored is None:
            # DB is empty: backfill initial days
            fetch_start = now_utc - timedelta(days=Config.INITIAL_BACKFILL_DAYS)
            logger.info(
                f"DB empty for {symbol}/{timeframe}, backfilling {Config.INITIAL_BACKFILL_DAYS} days"
            )
        else:
            # DB has data: overlap from previous candles
            overlap_delta = timedelta(minutes=candle_minutes * Config.INGEST_OVERLAP_CANDLES)
            fetch_start = latest_stored - overlap_delta
            logger.info(
                f"DB has data up to {latest_stored.isoformat()}, "
                f"fetching from {fetch_start.isoformat()} with {Config.INGEST_OVERLAP_CANDLES} candle overlap"
            )
        
        fetch_end = now_utc
        
        # Step 3: Fetch candles from provider
        try:
            raw_candles = await self.provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start=fetch_start,
                end=fetch_end,
            )
            logger.info(f"Provider returned {len(raw_candles)} candles")
        except Exception as e:
            logger.error(f"Provider fetch failed: {e}", exc_info=True)
            raise
        
        # Step 4: Validate and normalize
        validated_candles = []
        for raw in raw_candles:
            try:
                candle = self._normalize_and_validate(raw, symbol, timeframe)
                validated_candles.append(candle)
            except ValueError as e:
                logger.warning(f"Validation failed for candle: {e}")
                continue
        
        logger.info(f"Validated {len(validated_candles)} candles")
        
        # Step 5: Upsert into DB
        inserted = 0
        updated = 0
        
        if validated_candles:
            # PostgreSQL UPSERT
            stmt = pg_insert(Candle).values(validated_candles)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "open_time"],
                set_={
                    Candle.open: stmt.excluded.open,
                    Candle.high: stmt.excluded.high,
                    Candle.low: stmt.excluded.low,
                    Candle.close: stmt.excluded.close,
                    Candle.volume: stmt.excluded.volume,
                    Candle.source: stmt.excluded.source,
                    Candle.ingested_at: stmt.excluded.ingested_at,
                }
            )
            
            result = await session.execute(stmt)
            await session.commit()
            
            # Count inserted vs updated (rough estimate)
            inserted = len(validated_candles)  # Would need DB trigger for exact count
            
            logger.info(f"Upserted {inserted} candles into DB")
        
        # Step 6: Get latest and run integrity
        stmt = select(func.max(Candle.open_time)).where(
            (Candle.symbol == symbol) &
            (Candle.timeframe == timeframe)
        )
        result = await session.execute(stmt)
        latest_after = result.scalar()
        
        # Run integrity check
        integrity = await check_integrity(session, symbol, timeframe, days=7)
        
        return {
            "inserted": inserted,
            "updated": updated,
            "total_processed": len(validated_candles),
            "latest_open_time": latest_after.isoformat() if latest_after else None,
            "missing_ranges": integrity.get("missing_ranges", []),
            "integrity_check": integrity,
        }
    
    async def backfill(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        """
        Backfill candles for exact range.
        
        Args:
            session: AsyncSession
            symbol: Currency pair
            timeframe: Candle interval
            start: Inclusive start time
            end: Exclusive end time
        
        Returns:
            Dict with inserted, updated, total_processed, integrity_check
        """
        logger.info(
            f"Starting backfill for {symbol}/{timeframe} "
            f"from {start.isoformat()} to {end.isoformat()}"
        )
        
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Invalid timeframe: {timeframe}")
        
        # Ensure UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        
        # Fetch exact range
        try:
            raw_candles = await self.provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
            )
            logger.info(f"Provider returned {len(raw_candles)} candles for backfill")
        except Exception as e:
            logger.error(f"Provider fetch failed during backfill: {e}", exc_info=True)
            raise
        
        # Validate
        validated_candles = []
        for raw in raw_candles:
            try:
                candle = self._normalize_and_validate(raw, symbol, timeframe)
                validated_candles.append(candle)
            except ValueError as e:
                logger.warning(f"Validation failed during backfill: {e}")
                continue
        
        # Upsert
        inserted = 0
        if validated_candles:
            stmt = pg_insert(Candle).values(validated_candles)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "open_time"],
                set_={
                    Candle.open: stmt.excluded.open,
                    Candle.high: stmt.excluded.high,
                    Candle.low: stmt.excluded.low,
                    Candle.close: stmt.excluded.close,
                    Candle.volume: stmt.excluded.volume,
                    Candle.source: stmt.excluded.source,
                    Candle.ingested_at: stmt.excluded.ingested_at,
                }
            )
            
            await session.execute(stmt)
            await session.commit()
            inserted = len(validated_candles)
            logger.info(f"Backfilled {inserted} candles")
        
        # Run integrity check
        integrity = await check_integrity(session, symbol, timeframe, days=7)
        
        return {
            "requested_range_start": start.isoformat(),
            "requested_range_end": end.isoformat(),
            "inserted": inserted,
            "updated": 0,
            "total_processed": len(validated_candles),
            "integrity_check": integrity,
        }
    
    def _normalize_and_validate(
        self,
        raw: Dict[str, Any],
        symbol: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        Normalize raw candle dict and validate constraints.
        
        Raises ValueError if validation fails.
        """
        # Ensure timezone-aware UTC
        open_time = raw.get("open_time")
        if not isinstance(open_time, datetime):
            raise ValueError(f"open_time must be datetime, got {type(open_time)}")
        
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
        elif open_time.tzinfo != timezone.utc:
            open_time = open_time.astimezone(timezone.utc)
        
        # Align to timeframe boundary
        candle_minutes = TIMEFRAME_MINUTES.get(timeframe)
        if candle_minutes:
            epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
            delta = open_time - epoch
            candles_since = int(delta.total_seconds() / 60 / candle_minutes)
            open_time = epoch + timedelta(minutes=candles_since * candle_minutes)
        
        # Extract OHLCV
        o = float(raw.get("open", 0))
        h = float(raw.get("high", 0))
        l = float(raw.get("low", 0))
        c = float(raw.get("close", 0))
        v = raw.get("volume")
        if v is not None:
            v = float(v)
        
        # Validate OHLC constraints
        if not (h >= l):
            raise ValueError(f"High ({h}) must be >= Low ({l})")
        if not (h >= o and h >= c):
            raise ValueError(f"High ({h}) must be >= Open ({o}) and Close ({c})")
        if not (l <= o and l <= c):
            raise ValueError(f"Low ({l}) must be <= Open ({o}) and Close ({c})")
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": open_time,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "source": raw.get("source", "provider"),
        }

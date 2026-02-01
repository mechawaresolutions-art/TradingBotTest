"""Market data integrity checking and gap detection."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.marketdata.models import Candle

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


async def check_integrity(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    days: int = 7,
) -> dict:
    """
    Check data integrity: detect gaps, duplicates, expected vs actual counts.
    
    Args:
        session: AsyncSession
        symbol: Currency pair
        timeframe: Candle interval
        days: How many days back to check
    
    Returns:
        Dict with:
        - earliest, latest (datetime)
        - expected_count, actual_count
        - missing_count
        - duplicates_count
        - missing_ranges (list of (start, end) tuples, start inclusive end exclusive)
        - is_complete (bool)
    """
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Invalid timeframe: {timeframe}")
    
    # Query candles in range
    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - timedelta(days=days)
    
    stmt = select(Candle).where(
        (Candle.symbol == symbol) &
        (Candle.timeframe == timeframe) &
        (Candle.open_time >= start_time) &
        (Candle.open_time < now_utc)
    ).order_by(Candle.open_time.asc())
    
    result = await session.execute(stmt)
    candles = result.scalars().all()
    
    # Get earliest and latest
    earliest = candles[0].open_time if candles else None
    latest = candles[-1].open_time if candles else None
    
    actual_count = len(candles)
    
    # Calculate expected count based on timeframe
    candle_minutes = TIMEFRAME_MINUTES[timeframe]
    delta_seconds = (now_utc - start_time).total_seconds()
    expected_count = int(delta_seconds / 60 / candle_minutes)
    
    # Detect gaps and duplicates
    missing_ranges: List[Tuple[str, str]] = []
    duplicates_count = 0
    seen_times = set()
    
    if candles:
        prev_time = earliest
        for candle in candles:
            # Check for duplicate
            if candle.open_time in seen_times:
                duplicates_count += 1
            seen_times.add(candle.open_time)
            
            # Check for gap
            expected_next = prev_time + timedelta(minutes=candle_minutes)
            if candle.open_time > expected_next:
                gap_start = expected_next
                gap_end = candle.open_time
                missing_ranges.append((gap_start.isoformat(), gap_end.isoformat()))
            
            prev_time = candle.open_time
    
    missing_count = len(missing_ranges)
    is_complete = missing_count == 0 and duplicates_count == 0
    
    logger.info(
        f"Integrity check {symbol}/{timeframe}: "
        f"actual={actual_count}, expected={expected_count}, "
        f"missing={missing_count}, duplicates={duplicates_count}, "
        f"complete={is_complete}"
    )
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
        "expected_count": expected_count,
        "actual_count": actual_count,
        "missing_count": missing_count,
        "duplicates_count": duplicates_count,
        "missing_ranges": missing_ranges,
        "is_complete": is_complete,
    }


def get_missing_ranges(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> List[Tuple[datetime, datetime]]:
    """
    Detect missing candle ranges between start (inclusive) and end (exclusive).
    
    Returns list of (start_inclusive, end_exclusive) tuples for missing ranges.
    """
    # TODO: Implement gap detection in specific range
    # For now, return empty (will be filled by integrity checks)
    return []

"""Deterministic mock market data provider."""
import logging
import hashlib
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from app.marketdata.provider_base import MarketDataProvider

logger = logging.getLogger(__name__)

# Timeframe to minutes mapping
TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


class MockProvider:
    """Deterministic mock provider - same inputs produce same outputs."""
    
    def __init__(self) -> None:
        logger.info("MockProvider initialized (deterministic)")
    
    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Generate deterministic candles for testing.
        
        Ensures:
        - Same symbol/timeframe/range => same output
        - Candles aligned to timeframe boundaries
        - Closed candles only (no partial)
        - Smooth-ish OHLCV data
        - Ascending order
        """
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        # Ensure UTC timezone
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        
        # Align start to timeframe boundary (floor)
        candle_minutes = TIMEFRAME_MINUTES[timeframe]
        epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
        delta = start - epoch
        candles_since_epoch = delta.total_seconds() / 60 / candle_minutes
        start_aligned = epoch + timedelta(minutes=int(candles_since_epoch) * candle_minutes)
        
        candles = []
        current = start_aligned
        
        while current < end:
            candle = self._generate_candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=current,
            )
            candles.append(candle)
            current += timedelta(minutes=candle_minutes)
        
        logger.debug(
            f"MockProvider generated {len(candles)} candles "
            f"for {symbol} {timeframe} ({start} to {end})"
        )
        return candles
    
    def _generate_candle(
        self,
        symbol: str,
        timeframe: str,
        open_time: datetime,
    ) -> Dict[str, Any]:
        """Generate single deterministic candle."""
        # Deterministic seed based on symbol, timeframe, time
        seed_str = f"{symbol}:{timeframe}:{open_time.isoformat()}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
        
        # Pseudo-random but deterministic price generation
        # Base price depends on symbol
        base_price = 1.08 if symbol == "EURUSD" else 100.0
        
        # Generate OHLC using deterministic randomness
        price_seed = seed % 1000000
        open_delta = (price_seed % 100 - 50) / 10000
        open_price = base_price + open_delta
        
        # High/low/close offsets
        high_offset = abs((seed // 1000000) % 100) / 10000
        low_offset = abs((seed // 2000000) % 100) / 10000
        close_offset = (seed // 3000000) % 100 - 50
        close_offset = close_offset / 10000
        
        high_price = max(open_price, open_price + high_offset)
        low_price = min(open_price, open_price - low_offset)
        close_price = open_price + close_offset
        
        # Ensure OHLC constraints
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        
        # Volume (deterministic)
        volume = (seed % 100000) + 10000
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": open_time,
            "open": round(open_price, 5),
            "high": round(high_price, 5),
            "low": round(low_price, 5),
            "close": round(close_price, 5),
            "volume": float(volume),
            "source": "mock",
        }

"""Market data provider abstraction."""
from typing import Protocol, List, Dict, Any
from datetime import datetime


class MarketDataProvider(Protocol):
    """Protocol for market data providers."""
    
    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch candles for a symbol and timeframe.
        
        Args:
            symbol: Currency pair (e.g., 'EURUSD')
            timeframe: Candlestick interval (e.g., 'M5', 'H1')
            start: Start time (inclusive, UTC)
            end: End time (exclusive, UTC)
        
        Returns:
            List of candle dicts with keys: open_time, open, high, low, close, volume
            All timestamps must be timezone-aware UTC.
            Candles must be sorted ascending by open_time.
            Candles must be complete/closed only.
        """
        ...

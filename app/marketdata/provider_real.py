"""Real market data provider (placeholder for future integration)."""
import logging
from typing import List, Dict, Any
from datetime import datetime
from app.marketdata.provider_base import MarketDataProvider

logger = logging.getLogger(__name__)


class RealProvider:
    """Placeholder for real broker/API integration (MT5, OANDA, etc)."""
    
    def __init__(self) -> None:
        logger.warning(
            "RealProvider not yet implemented. "
            "To use: integrate MT5, OANDA, or other broker API."
        )
        raise NotImplementedError(
            "RealProvider requires integration with actual broker. "
            "Implement fetch_candles() to connect to MT5, OANDA, etc."
        )
    
    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch candles from real broker.
        
        TODO: Implement integration with:
        - MetaTrader5 (MT5)
        - OANDA REST API
        - Interactive Brokers
        - Alpha Vantage
        - Other forex/crypto providers
        
        Requirements:
        - Fetch closed candles only (no partial candles)
        - Return UTC timezone-aware datetimes
        - Return sorted ascending by open_time
        - Handle errors gracefully (retry, partial results)
        """
        raise NotImplementedError()

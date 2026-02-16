"""Trading strategy module."""
from typing import Optional
import logging
from typing import Dict, Any
from dataclasses import dataclass
from app.broker import PaperBroker
from app.risk import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Represents a trading signal."""
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class Strategy:
    """
    Base trading strategy.
    This is a stub - implement your trading logic in generate_signals().
    """

    def __init__(self, broker: PaperBroker, risk_manager: RiskManager) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        logger.info("Strategy initialized")

    def generate_signals(self, market_data: Dict[str, Any]) -> list[TradeSignal]:
        """
        Generate trading signals based on market data.
        
        Args:
            market_data: Dictionary with market prices and indicators
            
        Returns:
            List of TradeSignal objects
        """
        # STUB: Return empty list (no trades)
        return []

    def update_market_data(self, data: Dict[str, Any]) -> None:
        """
        Update internal market data state.
        Called on each bot iteration.
        """
        # STUB: No-op
        pass

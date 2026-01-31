"""Risk management module."""
import logging
from app.broker import PaperBroker

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Risk management system.
    Stub implementation - ready for expansion with position sizing,
    portfolio heat limits, drawdown limits, etc.
    """

    def __init__(
        self,
        broker: PaperBroker,
        max_position_size: float = 100000,
        max_positions: int = 5
    ) -> None:
        self.broker = broker
        self.max_position_size = max_position_size
        self.max_positions = max_positions

    def validate_trade(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        side: str
    ) -> bool:
        """
        Validate a proposed trade against risk limits.
        
        Args:
            symbol: Currency pair
            quantity: Position size
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            
        Returns:
            True if trade passes risk checks
        """
        try:
            # Check max positions
            open_positions = len(self.broker.get_positions())
            if open_positions >= self.max_positions:
                logger.warning(
                    f"Max positions ({self.max_positions}) reached"
                )
                return False
            
            # Check position size
            position_value = quantity * entry_price
            if position_value > self.max_position_size:
                logger.warning(
                    f"Position size ${position_value} exceeds max ${self.max_position_size}"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating trade: {e}")
            return False

    def get_available_balance(self) -> float:
        """Get available balance for new trades."""
        return self.broker.get_balance()

"""Legacy RiskManager compatibility shim."""
import logging

from app.broker import PaperBroker

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, broker: PaperBroker, max_position_size: float = 100000, max_positions: int = 5) -> None:
        self.broker = broker
        self.max_position_size = max_position_size
        self.max_positions = max_positions

    def validate_trade(self, symbol: str, quantity: float, entry_price: float, side: str) -> bool:
        try:
            open_positions = len(self.broker.get_positions())
            if open_positions >= self.max_positions:
                logger.warning("Max positions (%s) reached", self.max_positions)
                return False

            position_value = quantity * entry_price
            if position_value > self.max_position_size:
                logger.warning("Position size %s exceeds max %s", position_value, self.max_position_size)
                return False

            return True
        except Exception as e:
            logger.error("Error validating trade: %s", e)
            return False

    def get_available_balance(self) -> float:
        return self.broker.get_balance()

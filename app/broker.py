"""Paper trading broker placeholder."""
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open trading position."""
    symbol: str
    entry_price: float
    quantity: float
    side: str  # "BUY" or "SELL"
    entry_time: datetime = field(default_factory=datetime.utcnow)
    
    def pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L."""
        if self.side == "BUY":
            return (current_price - self.entry_price) * self.quantity
        else:  # SELL
            return (self.entry_price - current_price) * self.quantity


class PaperBroker:
    """
    Paper trading broker for backtesting and simulation.
    Ready to be replaced with MT5 or OANDA integration.
    """

    def __init__(self, initial_balance: float) -> None:
        self.balance = initial_balance
        self.positions: Dict[str, Position] = {}
        logger.info(f"Paper broker initialized with balance: ${initial_balance}")

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        side: str
    ) -> Optional[Position]:
        """
        Open a new position.
        
        Args:
            symbol: Currency pair (e.g., 'EURUSD')
            quantity: Position size
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            
        Returns:
            Position object if successful, None otherwise
        """
        try:
            # Validate
            if side not in ("BUY", "SELL"):
                logger.error(f"Invalid side: {side}")
                return None
            
            if symbol in self.positions:
                logger.warning(f"Position already open for {symbol}")
                return None
            
            # Calculate margin requirement (simplified, 2% of position value)
            required_margin = (entry_price * quantity) * 0.02
            if required_margin > self.balance:
                logger.warning(
                    f"Insufficient margin for {symbol}: "
                    f"required ${required_margin}, have ${self.balance}"
                )
                return None
            
            # Create position
            position = Position(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                side=side
            )
            
            self.positions[symbol] = position
            logger.info(
                f"Position opened: {side} {quantity} {symbol} @ ${entry_price}"
            )
            return position
            
        except Exception as e:
            logger.error(f"Error opening position: {e}")
            return None

    def close_position(self, symbol: str, exit_price: float) -> Optional[float]:
        """
        Close a position.
        
        Args:
            symbol: Currency pair
            exit_price: Exit price
            
        Returns:
            Realized P&L if successful, None otherwise
        """
        try:
            if symbol not in self.positions:
                logger.warning(f"No position open for {symbol}")
                return None
            
            position = self.positions.pop(symbol)
            pnl = position.pnl(exit_price)
            self.balance += pnl
            
            logger.info(
                f"Position closed: {position.side} {position.quantity} {symbol} "
                f"@ ${exit_price}, P&L: ${pnl:.2f}"
            )
            return pnl
            
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return None

    def get_balance(self) -> float:
        """Get current account balance."""
        return self.balance

    def get_positions(self) -> Dict[str, Position]:
        """Get all open positions."""
        return self.positions.copy()

    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total equity (balance + unrealized P&L).
        
        Args:
            current_prices: Dict mapping symbol to current price
            
        Returns:
            Total equity
        """
        equity = self.balance
        for symbol, position in self.positions.items():
            price = current_prices.get(symbol, position.entry_price)
            equity += position.pnl(price)
        return equity

"""Trading bot controller with background thread management."""
import logging
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from app.config import Config
from app.broker import PaperBroker
from app.risk import RiskManager
from app.strategy import Strategy
from app.notifier import Notifier

logger = logging.getLogger(__name__)


class BotState(Enum):
    """Bot operational states."""
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


class TradingBot:
    """
    Main trading bot controller.
    Runs trading loop in background thread. Thread-safe operations.
    """

    def __init__(
        self,
        webhook_url: str,
        initial_balance: float = 10000.0
    ) -> None:
        self.broker = PaperBroker(initial_balance)
        self.risk_manager = RiskManager(self.broker)
        self.strategy = Strategy(self.broker, self.risk_manager)
        self.notifier = Notifier(webhook_url)
        
        self.state = BotState.STOPPED
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self._lock = threading.Lock()
        
        self.stats = {
            "iterations": 0,
            "last_heartbeat": None,
            "started_at": None,
        }
        
        logger.info("TradingBot initialized")

    def start(self) -> bool:
        """
        Start the trading bot.
        
        Returns:
            True if started successfully
        """
        with self._lock:
            if self.running:
                logger.warning("Bot already running")
                return False
            
            try:
                self.running = True
                self.state = BotState.RUNNING
                self.stats["started_at"] = datetime.utcnow()
                self.stats["iterations"] = 0
                
                self.thread = threading.Thread(
                    target=self._trading_loop,
                    daemon=False
                )
                self.thread.start()
                
                logger.info("Trading bot started")
                self.notifier.send_started()
                return True
                
            except Exception as e:
                logger.error(f"Error starting bot: {e}")
                self.state = BotState.ERROR
                self.running = False
                return False

    def stop(self) -> bool:
        """
        Stop the trading bot.
        
        Returns:
            True if stopped successfully
        """
        with self._lock:
            if not self.running:
                logger.warning("Bot not running")
                return False
            
            self.running = False
        
        try:
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5)
            
            self.state = BotState.STOPPED
            logger.info("Trading bot stopped")
            self.notifier.send_stopped()
            return True
            
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
            self.state = BotState.ERROR
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        Get bot status and metrics.
        
        Returns:
            Status dictionary
        """
        with self._lock:
            positions = self.broker.get_positions()
            current_prices = {s: p.entry_price for s, p in positions.items()}
            equity = self.broker.get_equity(current_prices)
            
            return {
                "state": self.state.value,
                "running": self.running,
                "balance": round(self.broker.get_balance(), 2),
                "equity": round(equity, 2),
                "positions_count": len(positions),
                "iterations": self.stats["iterations"],
                "started_at": self.stats["started_at"].isoformat() if self.stats["started_at"] else None,
            }

    def _trading_loop(self) -> None:
        """Main trading loop executed in background thread."""
        last_heartbeat = time.time()
        
        try:
            while self.running:
                try:
                    with self._lock:
                        self.stats["iterations"] += 1
                    
                    # Placeholder market data (stub)
                    market_data = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "prices": {},
                    }
                    
                    # Update strategy state
                    self.strategy.update_market_data(market_data)
                    
                    # Generate signals (stub returns empty list)
                    signals = self.strategy.generate_signals(market_data)
                    
                    # Process signals
                    for signal in signals:
                        if self.risk_manager.validate_trade(
                            signal.symbol,
                            signal.quantity,
                            signal.entry_price,
                            signal.side
                        ):
                            self.broker.open_position(
                                signal.symbol,
                                signal.quantity,
                                signal.entry_price,
                                signal.side
                            )
                    
                    # Send heartbeat every N seconds
                    now = time.time()
                    if now - last_heartbeat >= Config.HEARTBEAT_INTERVAL:
                        last_heartbeat = now
                        status = self.get_status()
                        self.notifier.send_heartbeat(status)
                        with self._lock:
                            self.stats["last_heartbeat"] = datetime.utcnow()
                    
                    # Sleep to avoid busy loop
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error in trading loop iteration: {e}", exc_info=True)
                    self.state = BotState.ERROR
                    self.running = False
                    self.notifier.send_event(
                        "error",
                        {"message": f"Trading loop error: {str(e)[:200]}"}
                    )
                    
        except Exception as e:
            logger.error(f"Unexpected error in trading loop: {e}", exc_info=True)
            self.state = BotState.ERROR

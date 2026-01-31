"""Configuration management for the trading bot."""
import os
from dotenv import load_dotenv


load_dotenv()


class Config:
    """Load and validate environment configuration."""

    # Required
    N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")
    
    # Optional with defaults
    HEARTBEAT_INTERVAL: int = 60
    INITIAL_BALANCE: float = 10000.0
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    BOT_NAME: str = os.getenv("BOT_NAME", "ForexBot")
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.N8N_WEBHOOK_URL:
            raise ValueError("N8N_WEBHOOK_URL environment variable is required")
        
        # Parse and validate heartbeat interval
        try:
            heartbeat = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
            if heartbeat <= 0:
                raise ValueError("HEARTBEAT_INTERVAL must be a positive integer")
            cls.HEARTBEAT_INTERVAL = heartbeat
        except ValueError as e:
            raise ValueError(f"Invalid HEARTBEAT_INTERVAL: {e}")
        
        # Parse and validate initial balance
        try:
            balance = float(os.getenv("INITIAL_BALANCE", "10000.0"))
            if balance <= 0:
                raise ValueError("INITIAL_BALANCE must be a positive number")
            cls.INITIAL_BALANCE = balance
        except ValueError as e:
            raise ValueError(f"Invalid INITIAL_BALANCE: {e}")

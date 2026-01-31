"""Configuration management for the trading bot."""
import os
from typing import Optional
from dotenv import load_dotenv


load_dotenv()


class Config:
    """Load and validate environment configuration."""

    # Required
    N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")
    
    # Optional with defaults
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    BOT_NAME: str = os.getenv("BOT_NAME", "ForexBot")
    
    # Paper trading
    INITIAL_BALANCE: float = float(os.getenv("INITIAL_BALANCE", "10000.0"))
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.N8N_WEBHOOK_URL:
            raise ValueError("N8N_WEBHOOK_URL environment variable is required")
        if cls.HEARTBEAT_INTERVAL <= 0:
            raise ValueError("HEARTBEAT_INTERVAL must be a positive integer")

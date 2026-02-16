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
    
    # Database configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tradingbot:tradingbot_pass@localhost:5432/tradingbot"
    )
    
    # Market data configuration
    SYMBOL: str = os.getenv("SYMBOL", "EURUSD")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "M5")
    INGEST_OVERLAP_CANDLES: int = 10
    INITIAL_BACKFILL_DAYS: int = 7
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "mock")
    CANDLE_RETENTION_DAYS: int = 180
    # Execution parameters
    SPREAD_PIPS: float = float(os.getenv("SPREAD_PIPS", "1.0"))
    
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
        
        # Parse and validate market data config
        try:
            overlap = int(os.getenv("INGEST_OVERLAP_CANDLES", "10"))
            if overlap < 0:
                raise ValueError("INGEST_OVERLAP_CANDLES must be non-negative")
            cls.INGEST_OVERLAP_CANDLES = overlap
        except ValueError as e:
            raise ValueError(f"Invalid INGEST_OVERLAP_CANDLES: {e}")
        
        try:
            backfill = int(os.getenv("INITIAL_BACKFILL_DAYS", "7"))
            if backfill < 1:
                raise ValueError("INITIAL_BACKFILL_DAYS must be at least 1")
            cls.INITIAL_BACKFILL_DAYS = backfill
        except ValueError as e:
            raise ValueError(f"Invalid INITIAL_BACKFILL_DAYS: {e}")
        
        # Validate provider
        if cls.MARKET_DATA_PROVIDER not in ("mock", "real"):
            raise ValueError(f"Invalid MARKET_DATA_PROVIDER: {cls.MARKET_DATA_PROVIDER}")
        # Parse spread
        try:
            spread = float(os.getenv("SPREAD_PIPS", "1.0"))
            if spread < 0:
                raise ValueError("SPREAD_PIPS must be non-negative")
            cls.SPREAD_PIPS = spread
        except ValueError as e:
            raise ValueError(f"Invalid SPREAD_PIPS: {e}")
        
        # Validate database URL
        if not cls.DATABASE_URL.startswith(("postgresql", "sqlite")):
            raise ValueError("DATABASE_URL must be postgresql or sqlite")

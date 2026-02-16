"""SQLAlchemy ORM models for market data."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Candle(Base):
    """OHLCV candle data."""
    
    __tablename__ = "candles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    # Primary columns
    symbol = Column(String(20), primary_key=True, index=True)
    timeframe = Column(String(10), primary_key=True, index=True)
    open_time = Column(DateTime(timezone=True), primary_key=True, index=True)
    
    # OHLCV
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)
    
    # Metadata
    source = Column(String(50), nullable=False, default="provider")
    ingested_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Constraints
    __table_args__ = (
        # Unique constraint: only one candle per symbol/timeframe/time
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_time"),
        
        # OHLC sanity checks
        CheckConstraint("high >= low", name="ck_high_gte_low"),
        CheckConstraint("high >= open", name="ck_high_gte_open"),
        CheckConstraint("high >= close", name="ck_high_gte_close"),
        CheckConstraint("low <= open", name="ck_low_lte_open"),
        CheckConstraint("low <= close", name="ck_low_lte_close"),
        
        # Composite index for common queries
        Index("ix_candle_lookup", "symbol", "timeframe", "open_time"),
    )
    
    def __repr__(self) -> str:
        return (
            f"Candle("
            f"symbol={self.symbol}, "
            f"timeframe={self.timeframe}, "
            f"open_time={self.open_time.isoformat()}, "
            f"close={self.close})"
        )

"""Pydantic schemas for market data API."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class CandleSchema(BaseModel):
    """Candle data schema."""
    
    symbol: str
    timeframe: str
    open_time: datetime = Field(..., description="UTC timestamp of candle open")
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    source: str = "provider"
    ingested_at: datetime
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class CandleListSchema(BaseModel):
    """List of candles."""
    
    count: int
    candles: List[CandleSchema]
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None


class IntegrityCheckSchema(BaseModel):
    """Market data integrity check result."""
    
    symbol: str
    timeframe: str
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    expected_count: int
    actual_count: int
    missing_count: int
    duplicates_count: int = 0
    missing_ranges: List[tuple[str, str]] = Field(default_factory=list)
    is_complete: bool


class IngestionResultSchema(BaseModel):
    """Ingestion operation result."""
    
    inserted: int
    updated: int
    total_processed: int
    latest_open_time: Optional[datetime] = None
    missing_ranges: List[tuple[str, str]] = Field(default_factory=list)
    integrity_check: Optional[IntegrityCheckSchema] = None


class BackfillResultSchema(BaseModel):
    """Backfill operation result."""
    
    requested_range_start: datetime
    requested_range_end: datetime
    inserted: int
    updated: int
    total_processed: int
    integrity_check: Optional[IntegrityCheckSchema] = None

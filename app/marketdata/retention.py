"""Candle retention policy and pruning."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Config
from app.marketdata.models import Candle

logger = logging.getLogger(__name__)


async def prune_old_candles(session: AsyncSession) -> dict:
    """Delete candles older than CANDLE_RETENTION_DAYS.
    
    Returns dict with counts deleted.
    """
    retention_days = getattr(Config, "CANDLE_RETENTION_DAYS", 180)
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    # Count before
    stmt_before = select(func.count(Candle.id)).where(Candle.open_time < cutoff_time)
    res_before = await session.execute(stmt_before)
    count_before = res_before.scalar() or 0
    
    # Delete candles older than cutoff
    stmt_delete = delete(Candle).where(Candle.open_time < cutoff_time)
    result = await session.execute(stmt_delete)
    deleted_count = result.rowcount
    
    await session.commit()
    
    logger.info(f"Pruned {deleted_count} candles older than {retention_days} days (cutoff: {cutoff_time})")
    
    return {
        "deleted_count": deleted_count,
        "cutoff_time": cutoff_time.isoformat(),
        "retention_days": retention_days,
    }

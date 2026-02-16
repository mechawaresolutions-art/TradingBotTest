import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.marketdata.models import Base
from app.execution.models import Order
from app.execution.service import place_market_order


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s

    await engine.dispose()


@pytest.mark.asyncio
async def test_place_market_order_requires_candle_and_never_uses_wall_clock(session):
    """No-candle branch must fail fast to preserve deterministic timestamps."""
    with pytest.raises(RuntimeError, match="No market data available for fills"):
        await place_market_order(session, "EURUSD", "BUY", 1.0)

    order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    assert order_count == 0

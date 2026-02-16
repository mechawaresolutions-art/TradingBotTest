import asyncio
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.execution.models import Fill, Order, Position
from app.execution.service import ensure_account, place_market_order
from app.marketdata.models import Base, Candle


POSTGRES_TEST_DSN = os.getenv("TEST_POSTGRES_DSN", "")


pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_DSN,
    reason="Set TEST_POSTGRES_DSN to run Postgres concurrency test",
)


def _make_candle(open_time: datetime, close: float = 1.1000) -> Candle:
    return Candle(
        symbol="EURUSD",
        timeframe="M5",
        open_time=open_time,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=0.0,
        source="mock",
    )


@pytest.mark.asyncio
async def test_postgres_concurrent_orders_are_race_safe():
    engine = create_async_engine(POSTGRES_TEST_DSN, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    async with Session() as s:
        s.add(_make_candle(base_time, close=1.1000))
        await s.commit()
        await ensure_account(s)

    async def submit_buy_once() -> None:
        async with Session() as s:
            await place_market_order(s, "EURUSD", "BUY", 0.1)

    await asyncio.gather(*(submit_buy_once() for _ in range(10)))

    async with Session() as verify:
        pos = (await verify.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one()
        order_count = (await verify.execute(select(func.count(Order.id)))).scalar() or 0
        fill_count = (await verify.execute(select(func.count(Fill.id)))).scalar() or 0

        assert pos.qty_signed == 1.0
        assert order_count == 10
        assert fill_count == 10

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

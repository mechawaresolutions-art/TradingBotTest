from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.execution.models import Fill, Order
from app.execution.service import process_new_orders_for_candle
from app.marketdata.models import Base, Candle


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def make_candle(ts: datetime, open_price: float, symbol: str = "EURUSD") -> Candle:
    return Candle(
        symbol=symbol,
        timeframe="M5",
        open_time=ts,
        open=open_price,
        high=open_price,
        low=open_price,
        close=open_price,
        volume=0.0,
        source="mock",
    )


async def _determinism_run() -> list[tuple[int, float, datetime]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    async with Session() as s:
        s.add_all([make_candle(t0, 1.1000), make_candle(t1, 1.1010)])
        s.add_all(
            [
                Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW"),
                Order(ts=t0, symbol="EURUSD", side="SELL", type="market", qty=1.0, status="NEW"),
            ]
        )
        await s.commit()

        fills = await process_new_orders_for_candle(s, t1, symbol="EURUSD")
        return [(f.order_id, f.price, f.ts) for f in fills]


@pytest.mark.asyncio
async def test_determinism_same_inputs_same_fills(monkeypatch):
    monkeypatch.setattr(Config, "SPREAD_PIPS", 1.0, raising=False)
    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.5, raising=False)

    run1 = await _determinism_run()
    run2 = await _determinism_run()
    assert run1 == run2


@pytest.mark.asyncio
async def test_bid_ask_correctness_buy_above_mid_sell_below_mid(session, monkeypatch):
    monkeypatch.setattr(Config, "SPREAD_PIPS", 1.0, raising=False)
    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.0, raising=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    session.add_all([make_candle(t0, 1.0990), make_candle(t1, 1.1000)])
    session.add_all(
        [
            Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW"),
            Order(ts=t0, symbol="EURUSD", side="SELL", type="market", qty=1.0, status="NEW"),
        ]
    )
    await session.commit()

    fills = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    buy_fill = next(f for f in fills if f.side == "BUY")
    sell_fill = next(f for f in fills if f.side == "SELL")

    assert buy_fill.price > 1.1000
    assert sell_fill.price < 1.1000


@pytest.mark.asyncio
async def test_spread_effect_worsens_fill_price(session, monkeypatch):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    session.add_all([make_candle(t0, 1.0990), make_candle(t1, 1.1000)])
    order = Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW")
    session.add(order)
    await session.commit()

    monkeypatch.setattr(Config, "SPREAD_PIPS", 1.0, raising=False)
    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.0, raising=False)
    fills_1 = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    p1 = fills_1[0].price

    # Reset order/fill for second run in same DB
    await session.execute(select(Fill))
    await session.execute(
        Fill.__table__.delete().where(Fill.order_id == order.id)
    )
    order.status = "NEW"
    await session.commit()

    monkeypatch.setattr(Config, "SPREAD_PIPS", 2.0, raising=False)
    fills_2 = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    p2 = fills_2[0].price

    assert p2 > p1


@pytest.mark.asyncio
async def test_slippage_effect_worsens_fill_price(session, monkeypatch):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    session.add_all([make_candle(t0, 1.0990), make_candle(t1, 1.1000)])
    order = Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW")
    session.add(order)
    await session.commit()

    monkeypatch.setattr(Config, "SPREAD_PIPS", 1.0, raising=False)
    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.0, raising=False)
    fills_1 = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    p1 = fills_1[0].price

    await session.execute(Fill.__table__.delete().where(Fill.order_id == order.id))
    order.status = "NEW"
    await session.commit()

    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.5, raising=False)
    fills_2 = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    p2 = fills_2[0].price

    assert p2 > p1


@pytest.mark.asyncio
async def test_fail_fast_missing_fill_candle(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    session.add(make_candle(t0, 1.1000))
    session.add(Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW"))
    await session.commit()

    with pytest.raises(RuntimeError, match="deterministic execution requires latest candle.open_time"):
        await process_new_orders_for_candle(session, t1, symbol="EURUSD")


@pytest.mark.asyncio
async def test_idempotency_no_duplicate_fill(session, monkeypatch):
    monkeypatch.setattr(Config, "SPREAD_PIPS", 1.0, raising=False)
    monkeypatch.setattr(Config, "EXECUTION_SLIPPAGE_PIPS", 0.5, raising=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    session.add_all([make_candle(t0, 1.1000), make_candle(t1, 1.1010)])
    session.add(Order(ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="NEW"))
    await session.commit()

    fills_first = await process_new_orders_for_candle(session, t1, symbol="EURUSD")
    fills_second = await process_new_orders_for_candle(session, t1, symbol="EURUSD")

    count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    assert len(fills_first) == 1
    assert len(fills_second) == 0
    assert count == 1

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.execution.models import Fill, Order, Position
from app.execution.service import ensure_account, place_market_order
from app.marketdata.models import Base, Candle
from app.marketdata.retention import prune_old_candles


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s

    await engine.dispose()


def make_candle(open_time: datetime, close: float = 1.1000) -> Candle:
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
async def test_atomicity_rolls_back_on_mid_operation_failure(session, monkeypatch):
    c = make_candle(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), close=1.1000)
    session.add(c)
    await session.commit()

    fired = {"value": False}
    original_execute = session.execute

    async def flaky_execute(stmt, *args, **kwargs):
        sql = str(stmt)
        if not fired["value"] and "FROM positions" in sql:
            fired["value"] = True
            raise RuntimeError("simulated failure")
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(session, "execute", flaky_execute)

    with pytest.raises(RuntimeError, match="simulated failure"):
        await place_market_order(session, "EURUSD", "BUY", 1.0)

    order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    pos_count = (await session.execute(select(func.count(Position.symbol)))).scalar() or 0

    assert order_count == 0
    assert fill_count == 0
    assert pos_count == 0


@pytest.mark.asyncio
async def test_concurrent_market_orders_shared_state(tmp_path):
    db_path = tmp_path / "concurrency_hardening.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    async with SessionLocal() as setup_session:
        setup_session.add(make_candle(base_time, close=1.1000))
        await setup_session.commit()
        await ensure_account(setup_session)

    async def submit_buy():
        async with SessionLocal() as s:
            await place_market_order(s, "EURUSD", "BUY", 1.0)

    await asyncio.gather(submit_buy(), submit_buy())

    async with SessionLocal() as verify_session:
        pos = (await verify_session.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one()
        fill_count = (await verify_session.execute(select(func.count(Fill.id)))).scalar() or 0
        order_count = (await verify_session.execute(select(func.count(Order.id)))).scalar() or 0

        assert pos.qty_signed == 2.0
        assert fill_count == 2
        assert order_count == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_bid_ask_pricing_is_unambiguous(session):
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    mid = 1.2000
    session.add(make_candle(base_time, close=mid))
    await session.commit()

    _, buy_fill = await place_market_order(session, "EURUSD", "BUY", 1.0)
    _, sell_fill = await place_market_order(session, "EURUSD", "SELL", 1.0)

    assert buy_fill.price > mid
    assert sell_fill.price < mid


@pytest.mark.asyncio
async def test_duplicate_fill_for_same_order_fails(session):
    order = Order(
        symbol="EURUSD",
        side="BUY",
        qty=1.0,
        status="filled",
        reason="test",
        ts=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.flush()

    fill1 = Fill(
        order_id=order.id,
        symbol="EURUSD",
        side="BUY",
        qty=1.0,
        price=1.1001,
        fee=0.0,
        slippage=0.0,
        ts=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    session.add(fill1)
    await session.commit()

    fill2 = Fill(
        order_id=order.id,
        symbol="EURUSD",
        side="BUY",
        qty=1.0,
        price=1.1002,
        fee=0.0,
        slippage=0.0,
        ts=datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    session.add(fill2)

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


@pytest.mark.asyncio
async def test_prune_uses_open_time_not_ingested_time(session, monkeypatch):
    monkeypatch.setattr(Config, "CANDLE_RETENTION_DAYS", 30, raising=False)

    now = datetime.now(timezone.utc)
    old_open_time = now - timedelta(days=31)
    recent_open_time = now - timedelta(days=5)

    old_candle = make_candle(old_open_time, close=1.1000)
    recent_candle = make_candle(recent_open_time, close=1.1010)
    session.add_all([old_candle, recent_candle])
    await session.commit()

    result = await prune_old_candles(session)

    remaining = (await session.execute(select(func.count(Candle.id)))).scalar() or 0

    assert result["deleted_count"] == 1
    assert "cutoff_time" in result
    assert remaining == 1

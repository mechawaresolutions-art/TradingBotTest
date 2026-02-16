import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.execution.models import Fill, Order, Position, Trade
from app.execution.service import ensure_account, place_market_order, update_on_candle
from app.marketdata.models import Base, Candle


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s

    await engine.dispose()


def make_candle(open_time: datetime, close: float, high: float | None = None, low: float | None = None) -> Candle:
    high = close if high is None else high
    low = close if low is None else low
    high = max(high, close)
    low = min(low, close)
    return Candle(
        symbol="EURUSD",
        timeframe="M5",
        open_time=open_time,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=0.0,
        source="mock",
    )


@pytest.mark.asyncio
async def test_manual_partial_close_creates_trade_and_updates_balance(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    session.add_all([make_candle(t0, 1.1000), make_candle(t1, 1.1010)])
    await session.commit()

    acct_before = await ensure_account(session)
    starting_balance = acct_before.balance

    buy_order, buy_fill = await place_market_order(session, "EURUSD", "BUY", 2.0)
    sell_order, sell_fill = await place_market_order(session, "EURUSD", "SELL", 1.0, reason="manual_reduce")

    pnl_expected = (sell_fill.price - buy_fill.price) * 1.0

    trade = (await session.execute(select(Trade))).scalar_one()
    assert trade.qty == 1.0
    assert trade.exit_reason == "manual_reduce"
    assert trade.entry_order_id == buy_order.id
    assert trade.exit_order_id == sell_order.id
    assert trade.pnl == pytest.approx(pnl_expected)

    pos = (await session.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one()
    assert pos.qty_signed == 1.0

    acct_after = await ensure_account(session)
    assert acct_after.balance == pytest.approx(starting_balance + pnl_expected)


@pytest.mark.asyncio
async def test_flip_creates_trade_and_resets_position_entry_anchor(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    session.add_all([make_candle(t0, 1.2000), make_candle(t1, 1.2010)])
    await session.commit()

    open_order, _ = await place_market_order(session, "EURUSD", "BUY", 1.0)
    flip_order, _ = await place_market_order(session, "EURUSD", "SELL", 2.0, reason="manual_flip")

    trade = (await session.execute(select(Trade))).scalar_one()
    assert trade.qty == 1.0
    assert trade.entry_order_id == open_order.id
    assert trade.exit_order_id == flip_order.id
    assert trade.exit_reason == "manual_flip"

    pos = (await session.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one()
    assert pos.qty_signed == -1.0
    assert pos.entry_order_id == flip_order.id
    assert pos.opened_at == t1.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_strict_restart_recovery_with_new_engine(tmp_path):
    db_path = tmp_path / "restart_recovery.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine1 = create_async_engine(db_url, echo=False)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    async with Session1() as s1:
        s1.add(make_candle(t0, 1.1000))
        await s1.commit()
        await place_market_order(s1, "EURUSD", "BUY", 1.0, sl=1.0950, tp=1.1050)

    await engine1.dispose()

    # New engine/session simulates real process restart.
    engine2 = create_async_engine(db_url, echo=False)
    Session2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    async with Session2() as s2:
        pos = (await s2.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one()
        assert pos.qty_signed == 1.0

        s2.add(make_candle(t1, close=1.1060, high=1.1065, low=1.1000))
        await s2.commit()

        candle2 = (await s2.execute(select(Candle).where(Candle.open_time == t1))).scalar_one()
        executed = await update_on_candle(s2, candle2)
        assert len(executed) == 1

        pos_after = (await s2.execute(select(Position).where(Position.symbol == "EURUSD"))).scalar_one_or_none()
        assert pos_after is None

        trade_count = (await s2.execute(select(func.count(Trade.id)))).scalar() or 0
        fill_count = (await s2.execute(select(func.count(Fill.id)))).scalar() or 0
        assert trade_count == 1
        assert fill_count == 2

    await engine2.dispose()


@pytest.mark.asyncio
async def test_order_idempotency_key_prevents_duplicate_fills(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add(make_candle(t0, 1.1000))
    await session.commit()

    order1, fill1 = await place_market_order(
        session,
        "EURUSD",
        "BUY",
        1.0,
        idempotency_key="k-123",
    )
    order2, fill2 = await place_market_order(
        session,
        "EURUSD",
        "BUY",
        1.0,
        idempotency_key="k-123",
    )

    assert order1.id == order2.id
    assert fill1.id == fill2.id

    order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    assert order_count == 1
    assert fill_count == 1


@pytest.mark.asyncio
async def test_order_idempotency_key_concurrent_retry_safe(tmp_path):
    db_path = tmp_path / "idempotency_concurrent.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    async with Session() as s:
        s.add(make_candle(base_time, 1.1000))
        await s.commit()

    async def submit_once() -> tuple[int, int]:
        async with Session() as s:
            order, fill = await place_market_order(
                s,
                "EURUSD",
                "BUY",
                1.0,
                idempotency_key="same-request-key",
            )
            return order.id, fill.id

    ids = await asyncio.gather(submit_once(), submit_once())
    assert ids[0] == ids[1]

    async with Session() as verify:
        order_count = (await verify.execute(select(func.count(Order.id)))).scalar() or 0
        fill_count = (await verify.execute(select(func.count(Fill.id)))).scalar() or 0
        assert order_count == 1
        assert fill_count == 1

    await engine.dispose()

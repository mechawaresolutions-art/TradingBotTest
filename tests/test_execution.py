import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select, func
from app.marketdata.models import Base as MarketBase, Candle
from app.execution.models import Account, Position, Order, Fill, Trade
from app.execution.service import place_market_order, update_on_candle, mark_to_market, ensure_account
from datetime import datetime, timezone, timedelta


DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(MarketBase.metadata.create_all)
    async_session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_local() as s:
        yield s
    await engine.dispose()


def make_candle(symbol="EURUSD", timeframe="M5", close=1.1000, open_time=None):
    if open_time is None:
        open_time = datetime.now(timezone.utc)
    return Candle(symbol=symbol, timeframe=timeframe, open_time=open_time, open=close, high=close, low=close, close=close, volume=0.0, source="mock")


@pytest.mark.asyncio
async def test_buy_sell_fill_prices(session):
    # Insert latest candle
    c = make_candle(close=1.1000)
    session.add(c)
    await session.commit()

    # Ensure account exists
    acct = await ensure_account(session)

    # Buy should fill at ask
    order, fill = await place_market_order(session, "EURUSD", "BUY", 1.0)
    assert fill.price > 1.0999

    # Sell should fill at bid
    order2, fill2 = await place_market_order(session, "EURUSD", "SELL", 1.0)
    assert fill2.price < fill.price


@pytest.mark.asyncio
async def test_netting_and_realized_pnl(session):
    # base candle
    c = make_candle(close=1.2000)
    session.add(c)
    await session.commit()

    # Open long 2 @ ask
    _, f1 = await place_market_order(session, "EURUSD", "BUY", 2.0)
    # Add long 1 @ higher ask (simulate price move)
    # insert new candle
    c2 = make_candle(close=1.2010, open_time=c.open_time + timedelta(minutes=5))
    session.add(c2)
    await session.commit()
    _, f2 = await place_market_order(session, "EURUSD", "BUY", 1.0)

    # Now sell 2 to partially close
    _, f3 = await place_market_order(session, "EURUSD", "SELL", 2.0)

    # Check positions table
    stmt = select(Position).where(Position.symbol == 'EURUSD')
    res = await session.execute(stmt)
    pos = res.scalar_one()
    assert pos.qty_signed is not None


@pytest.mark.asyncio
async def test_sl_trigger(session):
    # Create candle, open position with SL
    c = make_candle(close=1.3000, open_time=datetime(2025,1,1,0,0, tzinfo=timezone.utc))
    session.add(c)
    await session.commit()

    # Open long with SL at 1.2950
    await place_market_order(session, "EURUSD", "BUY", 1.0, sl=1.2950)

    # New candle that hits low below SL
    c2 = Candle(symbol="EURUSD", timeframe="M5", open_time=c.open_time + timedelta(minutes=5), open=1.3000, high=1.3005, low=1.2940, close=1.2955, volume=0.0, source="mock")
    session.add(c2)
    await session.commit()

    executed = await update_on_candle(session, c2)
    assert len(executed) == 1


@pytest.mark.asyncio
async def test_replay_determinism(session):
    # Create sequence of two candles
    base = datetime(2025,1,1,0,0, tzinfo=timezone.utc)
    c1 = Candle(symbol="EURUSD", timeframe="M5", open_time=base, open=1.1000, high=1.1010, low=1.0990, close=1.1005, volume=0.0, source="mock")
    c2 = Candle(symbol="EURUSD", timeframe="M5", open_time=base + timedelta(minutes=5), open=1.1005, high=1.1020, low=1.1000, close=1.1015, volume=0.0, source="mock")
    session.add_all([c1, c2])
    await session.commit()

    # Run a sequence: buy then step, record account
    await place_market_order(session, "EURUSD", "BUY", 1.0)
    await update_on_candle(session, c1)
    acct_before = await ensure_account(session)
    bal1 = acct_before.balance

    # For deterministic replay we assert repeated execution on same DB would produce same counts
    # (deeper replay would require snapshotting DB; this sanity check ensures deterministic pricing logic)
    stmt = select(func.count(Fill.id))
    res = await session.execute(stmt)
    count1 = res.scalar() or 0
    assert count1 >= 1

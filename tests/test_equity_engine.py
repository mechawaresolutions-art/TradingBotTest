from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.equity.service import derive_bid_ask, mark_to_market_account
from app.execution.models import Account, AccountSnapshot, Fill, Order
from app.execution.service import place_market_order
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
async def test_mtm_correctness_long_and_short(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    c0 = make_candle(t0, 1.1000)
    c1 = make_candle(t1, 1.1010)
    session.add_all([c0, c1])
    await session.commit()

    _, fill_buy = await place_market_order(session, "EURUSD", "BUY", 1.0)
    async with session.begin():
        mtm_buy = await mark_to_market_account(session, c1)

    bid1, ask1 = derive_bid_ask(c1, Config.SPREAD_PIPS)
    expected_long_unrealized = (bid1 - fill_buy.price) * 1.0
    assert mtm_buy["unrealized_pnl"] == pytest.approx(expected_long_unrealized)
    assert mtm_buy["equity"] == pytest.approx(mtm_buy["balance"] + expected_long_unrealized)

    # Close long and open short to validate ASK-based MTM for shorts.
    _, _ = await place_market_order(session, "EURUSD", "SELL", 1.0)
    _, fill_short = await place_market_order(session, "EURUSD", "SELL", 1.0)

    c2 = make_candle(t1 + timedelta(minutes=5), 1.0990)
    session.add(c2)
    await session.commit()

    async with session.begin():
        mtm_short = await mark_to_market_account(session, c2)

    bid2, ask2 = derive_bid_ask(c2, Config.SPREAD_PIPS)
    expected_short_unrealized = (fill_short.price - ask2) * 1.0
    assert mtm_short["unrealized_pnl"] == pytest.approx(expected_short_unrealized)


@pytest.mark.asyncio
async def test_margin_used_correctness(session, monkeypatch):
    monkeypatch.setattr(Config, "ACCOUNT_LEVERAGE", 50.0, raising=False)
    monkeypatch.setattr(Config, "CONTRACT_SIZE", 100000.0, raising=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    c0 = make_candle(t0, 1.2000)
    session.add(c0)
    await session.commit()

    await place_market_order(session, "EURUSD", "BUY", 2.0)

    async with session.begin():
        mtm = await mark_to_market_account(session, c0)

    bid, _ = derive_bid_ask(c0, Config.SPREAD_PIPS)
    expected_margin = abs(2.0) * bid * Config.CONTRACT_SIZE / Config.ACCOUNT_LEVERAGE
    assert mtm["margin_used"] == pytest.approx(expected_margin)


@pytest.mark.asyncio
async def test_trade_blocking_when_free_margin_insufficient(session, monkeypatch):
    monkeypatch.setattr(Config, "ACCOUNT_LEVERAGE", 10.0, raising=False)
    monkeypatch.setattr(Config, "CONTRACT_SIZE", 100000.0, raising=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    c0 = make_candle(t0, 1.2000)
    session.add(c0)
    await session.commit()

    with pytest.raises(RuntimeError, match="Insufficient free margin"):
        await place_market_order(session, "EURUSD", "BUY", 2.0)

    order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    assert order_count == 0
    assert fill_count == 0


@pytest.mark.asyncio
async def test_mtm_snapshot_idempotent_same_candle(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    c0 = make_candle(t0, 1.1000)
    session.add(c0)
    await session.commit()

    async with session.begin():
        first = await mark_to_market_account(session, c0)
    async with session.begin():
        second = await mark_to_market_account(session, c0)

    snap_count = (await session.execute(select(func.count(AccountSnapshot.id)))).scalar() or 0
    assert snap_count == 1
    assert first["snapshot_id"] == second["snapshot_id"]
    assert second["idempotent"] is True


@pytest.mark.asyncio
async def test_restart_safety_for_mtm_snapshots(tmp_path):
    db_path = tmp_path / "equity_restart.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine1 = create_async_engine(db_url, echo=False)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)

    async with Session1() as s1:
        c0 = make_candle(t0, 1.1000)
        s1.add(c0)
        await s1.commit()
        await place_market_order(s1, "EURUSD", "BUY", 1.0)
        async with s1.begin():
            await mark_to_market_account(s1, c0)

    await engine1.dispose()

    engine2 = create_async_engine(db_url, echo=False)
    Session2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    async with Session2() as s2:
        c1 = make_candle(t1, 1.1010)
        s2.add(c1)
        await s2.commit()

        async with s2.begin():
            mtm = await mark_to_market_account(s2, c1)

        acct = (await s2.execute(select(Account).limit(1))).scalar_one()
        snap_count = (await s2.execute(select(func.count(AccountSnapshot.id)))).scalar() or 0

        assert acct.updated_at == t1.replace(tzinfo=None)
        assert mtm["ts"] == t1
        assert snap_count == 2

    await engine2.dispose()

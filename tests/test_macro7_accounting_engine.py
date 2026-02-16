from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.accounting.models import AccountingPosition, AccountingSnapshot, RealizedTrade
from app.accounting.service import AccountingEngine
from app.config import Config
from app.execution.models import Account, Fill, Order
from app.marketdata.models import Base, Candle


@pytest_asyncio.fixture
async def session(monkeypatch):
    monkeypatch.setattr(Config, "TIMEFRAME", "M5", raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def candle(ts: datetime, open_price: float, symbol: str = "EURUSD") -> Candle:
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


async def seed_account(session: AsyncSession, ts: datetime):
    session.add(
        Account(
            id=1,
            balance=10000.0,
            equity=10000.0,
            margin_used=0.0,
            free_margin=10000.0,
            leverage=30.0,
            currency="USD",
            updated_at=ts,
        )
    )


@pytest.mark.asyncio
async def test_open_position(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED")])
    session.add(Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.1000, fee=0.0, slippage=0.0))
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(1.0)
    assert pos.avg_entry_price == pytest.approx(1.1000)


@pytest.mark.asyncio
async def test_increase_same_side_weighted_avg(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), candle(t1, 1.1010)])
    session.add_all([
        Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
        Order(id=2, ts=t1, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
    ])
    session.add_all([
        Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.1000, fee=0.0, slippage=0.0),
        Fill(id=2, order_id=2, ts=t1, symbol="EURUSD", side="BUY", qty=1.0, price=1.1020, fee=0.0, slippage=0.0),
    ])
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t1)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(2.0)
    assert pos.avg_entry_price == pytest.approx((1.1000 + 1.1020) / 2)


@pytest.mark.asyncio
async def test_partial_close_realizes_pnl(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), candle(t1, 1.1010)])
    session.add_all([
        Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=2.0, status="FILLED"),
        Order(id=2, ts=t1, symbol="EURUSD", side="SELL", type="market", qty=1.0, status="FILLED"),
    ])
    session.add_all([
        Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=2.0, price=1.1000, fee=0.0, slippage=0.0),
        Fill(id=2, order_id=2, ts=t1, symbol="EURUSD", side="SELL", qty=1.0, price=1.1010, fee=0.0, slippage=0.0),
    ])
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t1)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(1.0)

    acct = (await session.execute(select(Account).where(Account.id == 1))).scalar_one()
    assert acct.balance == pytest.approx(10000.001)


@pytest.mark.asyncio
async def test_full_close_resets_position(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), candle(t1, 1.1010)])
    session.add_all([
        Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
        Order(id=2, ts=t1, symbol="EURUSD", side="SELL", type="market", qty=1.0, status="FILLED"),
    ])
    session.add_all([
        Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.1000, fee=0.0, slippage=0.0),
        Fill(id=2, order_id=2, ts=t1, symbol="EURUSD", side="SELL", qty=1.0, price=1.1010, fee=0.0, slippage=0.0),
    ])
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t1)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(0.0)
    assert pos.avg_entry_price == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_cross_through_reversal(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), candle(t1, 1.1010)])
    session.add_all([
        Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
        Order(id=2, ts=t1, symbol="EURUSD", side="SELL", type="market", qty=2.0, status="FILLED"),
    ])
    session.add_all([
        Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.1000, fee=0.0, slippage=0.0),
        Fill(id=2, order_id=2, ts=t1, symbol="EURUSD", side="SELL", qty=2.0, price=1.1010, fee=0.0, slippage=0.0),
    ])
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t1)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(-1.0)
    assert pos.avg_entry_price == pytest.approx(1.1010)


@pytest.mark.asyncio
async def test_idempotency_apply_new_fills(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    await seed_account(session, t0)
    session.add(candle(t0, 1.1000))
    session.add(Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"))
    session.add(Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.1, fee=0.0, slippage=0.0))
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)
    bal1 = (await session.execute(select(Account.balance).where(Account.id == 1))).scalar_one()

    await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)
    bal2 = (await session.execute(select(Account.balance).where(Account.id == 1))).scalar_one()

    assert bal1 == bal2
    trades = (await session.execute(select(func.count(RealizedTrade.id)))).scalar() or 0
    assert trades == 0


@pytest.mark.asyncio
async def test_mark_to_market_snapshot(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    await seed_account(session, t0)
    session.add_all([candle(t0, 1.1000), candle(t1, 1.1010)])
    session.add(AccountingPosition(account_id=1, symbol="EURUSD", net_qty=1.0, avg_entry_price=1.1000, updated_open_time=t0))
    await session.commit()

    async with session.begin():
        snap = await AccountingEngine.mark_to_market(
            session,
            account_id=1,
            symbol="EURUSD",
            timeframe="M5",
            asof_open_time=t1,
        )
    assert float(snap.unrealized_pnl) == pytest.approx(0.001)
    assert float(snap.equity) == pytest.approx(10000.001)


@pytest.mark.asyncio
async def test_snapshot_upsert_uniqueness(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    await seed_account(session, t0)
    session.add(candle(t0, 1.1000))
    await session.commit()

    async with session.begin():
        await AccountingEngine.mark_to_market(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)
    async with session.begin():
        await AccountingEngine.mark_to_market(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)

    count = (await session.execute(select(func.count(AccountingSnapshot.id)))).scalar() or 0
    assert count == 1


@pytest.mark.asyncio
async def test_deterministic_ordering_same_open_time_by_fill_id(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    await seed_account(session, t0)
    session.add(candle(t0, 1.1000))
    session.add_all([
        Order(id=1, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
        Order(id=2, ts=t0, symbol="EURUSD", side="BUY", type="market", qty=1.0, status="FILLED"),
    ])
    session.add_all([
        Fill(id=2, order_id=2, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.2, fee=0.0, slippage=0.0),
        Fill(id=1, order_id=1, ts=t0, symbol="EURUSD", side="BUY", qty=1.0, price=1.0, fee=0.0, slippage=0.0),
    ])
    await session.commit()

    async with session.begin():
        await AccountingEngine.apply_new_fills(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)

    pos = (await session.execute(select(AccountingPosition))).scalar_one()
    assert pos.net_qty == pytest.approx(2.0)
    assert pos.avg_entry_price == pytest.approx(1.1)


@pytest.mark.asyncio
async def test_margin_free_margin_sanity(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    await seed_account(session, t0)
    session.add(candle(t0, 1.2))
    session.add(AccountingPosition(account_id=1, symbol="EURUSD", net_qty=2.0, avg_entry_price=1.0, updated_open_time=t0))
    await session.commit()

    async with session.begin():
        snap = await AccountingEngine.mark_to_market(session, account_id=1, symbol="EURUSD", timeframe="M5", asof_open_time=t0)

    expected_margin = 2.0 * 1.2 / 30.0
    assert float(snap.margin_used) == pytest.approx(expected_margin)
    assert float(snap.free_margin) == pytest.approx(float(snap.equity) - expected_margin)

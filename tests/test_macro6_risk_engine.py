from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.execution.models import Account, Position
from app.marketdata.models import Base, Candle
from app.risk.models import DailyEquity, RiskLimits
from app.risk.service import RiskEngine
from app.oms.schemas import OMSPlaceOrderIn
from app.oms.service import place_order


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


def make_candle(symbol: str, ts: datetime, open_price: float) -> Candle:
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


async def seed_basics(session: AsyncSession):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add_all(
        [
            make_candle("EURUSD", t0, 1.1000),
            make_candle("GBPUSD", t0, 1.2500),
        ]
    )
    session.add(
        Account(
            id=1,
            balance=10000.0,
            equity=10000.0,
            margin_used=0.0,
            free_margin=10000.0,
            currency="USD",
            leverage=30.0,
            updated_at=t0,
        )
    )
    await session.commit()
    return t0


@pytest.mark.asyncio
async def test_max_open_positions_rejection(session):
    t0 = await seed_basics(session)
    session.add_all(
        [
            Position(symbol="EURUSD", qty_signed=1.0, avg_price=1.1, opened_at=t0, updated_at=t0),
            Position(symbol="GBPUSD", qty_signed=1.0, avg_price=1.25, opened_at=t0, updated_at=t0),
        ]
    )
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=2,
            max_open_positions_per_symbol=2,
            max_total_notional=1e9,
            max_symbol_notional=1e9,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=1.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert decision.allowed is False
    assert "Max open positions" in (decision.reason or "")


@pytest.mark.asyncio
async def test_per_symbol_position_cap_rejection(session):
    t0 = await seed_basics(session)
    session.add(Position(symbol="EURUSD", qty_signed=1.0, avg_price=1.1, opened_at=t0, updated_at=t0))
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=1,
            max_total_notional=1e9,
            max_symbol_notional=1e9,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=1.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert decision.allowed is False
    assert "per symbol" in (decision.reason or "")


@pytest.mark.asyncio
async def test_symbol_notional_cap_rejection(session):
    t0 = await seed_basics(session)
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=1e9,
            max_symbol_notional=2.0,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=3.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert decision.allowed is False
    assert "symbol notional" in (decision.reason or "")


@pytest.mark.asyncio
async def test_total_notional_cap_rejection(session):
    t0 = await seed_basics(session)
    session.add(Position(symbol="EURUSD", qty_signed=1.0, avg_price=1.1, opened_at=t0, updated_at=t0))
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=2.0,
            max_symbol_notional=100.0,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="GBPUSD",
            side="BUY",
            qty=2.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert decision.allowed is False
    assert "total notional" in (decision.reason or "")


@pytest.mark.asyncio
async def test_risk_sizing_approved_qty(session):
    t0 = await seed_basics(session)
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=1e9,
            max_symbol_notional=1e9,
            risk_per_trade_pct=0.01,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=50000.0,
            stop_distance_pips=50.0,
            asof_open_time=t0,
        )
    assert decision.allowed is True
    assert decision.approved_qty == pytest.approx(20000.0)


@pytest.mark.asyncio
async def test_daily_loss_limit_breach_blocks_new_orders(session):
    t0 = await seed_basics(session)
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=1e9,
            max_symbol_notional=1e9,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.05,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    async with session.begin():
        first = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=1.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert first.allowed is True

    acct = (await session.execute(select(Account).where(Account.id == 1))).scalar_one()
    acct.balance = 9000.0
    await session.commit()

    async with session.begin():
        second = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=1.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert second.allowed is False
    assert "Daily loss limit" in (second.reason or "")


@pytest.mark.asyncio
async def test_margin_check_rejects_when_free_margin_insufficient(session):
    t0 = await seed_basics(session)
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=1e12,
            max_symbol_notional=1e12,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=1.0,
        )
    )
    await session.commit()

    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol="EURUSD",
            side="BUY",
            qty=10000.0,
            stop_distance_pips=None,
            asof_open_time=t0,
        )
    assert decision.allowed is False
    assert "free margin" in (decision.reason or "")


@pytest.mark.asyncio
async def test_idempotent_daily_equity_creation_single_row(session):
    t0 = await seed_basics(session)

    async with session.begin():
        _ = await RiskEngine.compute_snapshot(session, account_id=1, asof_open_time=t0, symbol="EURUSD")

    async with session.begin():
        _ = await RiskEngine.compute_snapshot(session, account_id=1, asof_open_time=t0 + timedelta(minutes=1), symbol="EURUSD")

    count = (await session.execute(select(func.count(DailyEquity.id)))).scalar() or 0
    assert count == 1


@pytest.mark.asyncio
async def test_oms_integration_rejects_before_new_when_risk_denies(session):
    t0 = await seed_basics(session)
    session.add(
        RiskLimits(
            account_id=1,
            max_open_positions=10,
            max_open_positions_per_symbol=10,
            max_total_notional=1.0,
            max_symbol_notional=1.0,
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=0.5,
            daily_loss_limit_amount=0.0,
            leverage=30.0,
        )
    )
    await session.commit()

    result = await place_order(
        session,
        OMSPlaceOrderIn(symbol="EURUSD", side="BUY", qty=10.0, type="market"),
    )
    assert result["status"] == "REJECTED"
    assert "notional" in (result["reason"] or "").lower()

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.execution.models import Fill, Order, Position
from app.marketdata.models import Base, Candle
from app.oms.schemas import OMSPlaceOrderIn
from app.oms.service import cancel_order, list_orders, place_order


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s

    await engine.dispose()


def make_candle(open_time: datetime, close: float) -> Candle:
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
async def test_place_order_filled_creates_fill(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add(make_candle(t0, 1.1000))
    await session.commit()

    result = await place_order(
        session,
        OMSPlaceOrderIn(symbol="EURUSD", side="BUY", qty=0.5, type="market"),
    )

    assert result["status"] == "FILLED"
    assert result["fill_id"] is not None

    order = (await session.execute(select(Order).where(Order.id == result["order_id"]))).scalar_one()
    fill = (await session.execute(select(Fill).where(Fill.id == result["fill_id"]))).scalar_one()
    assert order.status == "FILLED"
    assert fill.order_id == order.id


@pytest.mark.asyncio
async def test_place_order_rejected_no_fill_no_position_change(session, monkeypatch):
    monkeypatch.setattr(Config, "ACCOUNT_LEVERAGE", 10.0, raising=False)
    monkeypatch.setattr(Config, "CONTRACT_SIZE", 100000.0, raising=False)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add(make_candle(t0, 1.2000))
    await session.commit()

    result = await place_order(
        session,
        OMSPlaceOrderIn(symbol="EURUSD", side="BUY", qty=2.0, type="market"),
    )

    assert result["status"] == "REJECTED"
    assert "Insufficient free margin" in (result["reason"] or "")
    assert result["fill_id"] is None

    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    pos_count = (await session.execute(select(func.count(Position.symbol)))).scalar() or 0
    assert fill_count == 0
    assert pos_count == 0


@pytest.mark.asyncio
async def test_idempotency_key_returns_same_order(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add(make_candle(t0, 1.1000))
    await session.commit()

    payload = OMSPlaceOrderIn(
        symbol="EURUSD",
        side="BUY",
        qty=0.5,
        type="market",
        idempotency_key="oms-key-1",
    )
    first = await place_order(session, payload)
    second = await place_order(session, payload)

    assert first["order_id"] == second["order_id"]
    assert first["fill_id"] == second["fill_id"]

    order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
    assert order_count == 1
    assert fill_count == 1


@pytest.mark.asyncio
async def test_list_orders_filters_work(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    t2 = t1 + timedelta(minutes=5)
    session.add_all([make_candle(t0, 1.1000), make_candle(t1, 1.1010), make_candle(t2, 1.1020)])
    await session.commit()

    await place_order(session, OMSPlaceOrderIn(symbol="EURUSD", side="BUY", qty=0.1, type="market"))
    rejected = await place_order(
        session,
        OMSPlaceOrderIn(symbol="USDJPY", side="BUY", qty=0.1, type="market"),
    )
    assert rejected["status"] == "REJECTED"

    rows_all = await list_orders(session, limit=100)
    rows_filled = await list_orders(session, status="FILLED", limit=100)
    rows_symbol = await list_orders(session, symbol="EURUSD", limit=100)

    assert len(rows_all) == 2
    assert len(rows_filled) == 1
    assert len(rows_symbol) == 1
    assert rows_all[0]["ts"] >= rows_all[1]["ts"]


@pytest.mark.asyncio
async def test_cancel_new_order(session):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.add(make_candle(t0, 1.1000))
    await session.commit()

    order = Order(
        ts=t0,
        symbol="EURUSD",
        side="BUY",
        type="market",
        qty=0.1,
        status="NEW",
        reason=None,
    )
    session.add(order)
    await session.commit()

    out = await cancel_order(session, order.id)
    assert out is not None
    assert out["status"] == "CANCELED"

    order_db = (await session.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert order_db.status == "CANCELED"

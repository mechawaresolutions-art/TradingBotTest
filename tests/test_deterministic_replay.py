"""Deterministic replay and crash-recovery tests for MACRO 2."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, func, text
from app.marketdata.models import Base, Candle
from app.execution.models import Account, Order, Fill, Position, Trade
from app.execution.service import place_market_order, update_on_candle, mark_to_market, ensure_account

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session():
    """Create fresh in-memory SQLite session for each test."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_local() as s:
        yield s
    await engine.dispose()


def make_candle(symbol="EURUSD", timeframe="M5", open_time=None, open=1.1000, high=1.1010, low=1.0990, close=1.1005):
    """Create a deterministic candle. Ensures OHLC constraints: high >= close, high >= open, low <= close, low <= open."""
    if open_time is None:
        open_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    # Ensure high >= max(open, close) and low <= min(open, close)
    high = max(high, open, close)
    low = min(low, open, close)
    return Candle(symbol=symbol, timeframe=timeframe, open_time=open_time, open=open, high=high, low=low, close=close, volume=0.0, source="mock")


DETERMINISTIC_SCENARIO = [
    # (candle_open_time, candle_close, order_side, order_qty, sl, tp)
    (datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), 1.1000, "BUY", 1.0, 1.0950, 1.1050),
    (datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc), 1.1010, None, None, None, None),
    (datetime(2025, 1, 1, 0, 10, tzinfo=timezone.utc), 1.1020, None, None, None, None),
    (datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc), 1.1055, None, None, None, None),  # TP hit
]


@pytest.mark.asyncio
async def test_deterministic_replay(session):
    """Verify identical execution across two replay runs."""
    
    # Run 1: Execute scenario
    results_run1 = await _run_scenario(session)
    
    # Run 2: Reset and replay
    # Delete all state
    await session.execute(text("DELETE FROM trades"))
    await session.execute(text("DELETE FROM positions"))
    await session.execute(text("DELETE FROM fills"))
    await session.execute(text("DELETE FROM orders"))
    await session.execute(text("DELETE FROM accounts"))
    await session.execute(text("DELETE FROM candles"))
    await session.commit()
    
    results_run2 = await _run_scenario(session)
    
    # Assert identical results
    assert results_run1["final_balance"] == results_run2["final_balance"]
    assert results_run1["final_pnl"] == results_run2["final_pnl"]
    assert results_run1["trade_count"] == results_run2["trade_count"]
    assert results_run1["fill_count"] == results_run2["fill_count"]


@pytest.mark.asyncio
async def test_crash_recovery(session):
    """Verify no state loss after simulated crash."""
    
    # Setup: Place order and get position
    candle1 = make_candle(open_time=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), close=1.1000)
    session.add(candle1)
    await session.commit()
    
    # Place market order
    order, fill = await place_market_order(session, "EURUSD", "BUY", 1.0, sl=1.0950, tp=1.1050)
    await session.refresh(order)
    await session.refresh(fill)
    
    order_id_1 = order.id
    fill_price_1 = fill.price
    
    # Get account balance after order
    acct = await ensure_account(session)
    balance_after_order = acct.balance
    
    # Simulate crash: query position state (this is what would be restored from DB)
    stmt_pos = select(Position).where(Position.symbol == "EURUSD")
    res = await session.execute(stmt_pos)
    pos_before = res.scalar_one()
    assert pos_before.qty_signed == 1.0
    assert pos_before.avg_price == fill_price_1
    
    # "Restart" by querying same DB (in real scenario, this is a fresh connection)
    stmt_pos_after = select(Position).where(Position.symbol == "EURUSD")
    res_after = await session.execute(stmt_pos_after)
    pos_after = res_after.scalar_one()
    
    # Verify state not lost
    assert pos_after.qty_signed == pos_before.qty_signed
    assert pos_after.avg_price == pos_before.avg_price
    assert pos_after.stop_loss == pos_before.stop_loss
    assert pos_after.take_profit == pos_before.take_profit
    
    # Verify account balance not lost
    acct_after = await ensure_account(session)
    assert acct_after.balance == balance_after_order
    
    # Verify fill not duplicated (only 1 order, 1 fill)
    stmt_order_count = select(func.count(Order.id))
    res_count = await session.execute(stmt_order_count)
    assert res_count.scalar() == 1
    
    stmt_fill_count = select(func.count(Fill.id))
    res_fill_count = await session.execute(stmt_fill_count)
    assert res_fill_count.scalar() == 1


@pytest.mark.asyncio
async def test_idempotent_execution_step(session):
    """Verify calling execution step twice on same candle doesn't duplicate."""
    
    # Setup candles
    candle1 = make_candle(open_time=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), close=1.1000, high=1.1000, low=1.1000)
    candle2 = make_candle(open_time=datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc), close=1.1100, high=1.1200, low=1.0900)
    session.add_all([candle1, candle2])
    await session.commit()
    
    # Place order
    await place_market_order(session, "EURUSD", "BUY", 1.0, sl=1.0950, tp=1.1050)
    
    # Execute candle2 (should trigger TP at 1.1050 < 1.1100 high)
    executed_1 = await update_on_candle(session, candle2)
    assert len(executed_1) == 1
    
    # Count trades after first execution
    stmt = select(func.count(Trade.id))
    res = await session.execute(stmt)
    count_1 = res.scalar()
    
    # Execute candle2 again (idempotent: should do nothing)
    executed_2 = await update_on_candle(session, candle2)
    assert len(executed_2) == 0  # No new exits
    
    # Verify trade count unchanged
    res2 = await session.execute(stmt)
    count_2 = res2.scalar()
    assert count_2 == count_1
    assert count_2 == 1  # Only 1 trade total


async def _run_scenario(session) -> dict:
    """Run the deterministic scenario and return results."""
    # Create account
    acct = await ensure_account(session)
    initial_balance = acct.balance
    
    trade_count = 0
    fill_count = 0
    
    for step, (open_time, close, side, qty, sl, tp) in enumerate(DETERMINISTIC_SCENARIO):
        # Add candle
        candle = make_candle(open_time=open_time, close=close)
        session.add(candle)
        await session.commit()
        
        # If order specified, place it
        if side is not None:
            await place_market_order(session, "EURUSD", side, qty, sl=sl, tp=tp)
            stmt = select(func.count(Fill.id))
            res = await session.execute(stmt)
            fill_count = res.scalar() or 0
        
        # Process candle for SL/TP
        executed = await update_on_candle(session, candle)
        if executed:
            trade_count += len(executed)
    
    # Get final account state
    acct_final = await ensure_account(session)
    final_balance = acct_final.balance
    final_pnl = final_balance - initial_balance
    
    # Count trades
    stmt_trade = select(func.count(Trade.id))
    res_trade = await session.execute(stmt_trade)
    final_trade_count = res_trade.scalar() or 0
    
    # Count fills
    stmt_fill2 = select(func.count(Fill.id))
    res_fill2 = await session.execute(stmt_fill2)
    final_fill_count = res_fill2.scalar() or 0
    
    return {
        "final_balance": final_balance,
        "final_pnl": final_pnl,
        "trade_count": final_trade_count,
        "fill_count": final_fill_count,
    }

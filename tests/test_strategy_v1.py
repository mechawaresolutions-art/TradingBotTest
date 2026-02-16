from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Config
from app.execution.models import Order
from app.execution.service import place_market_order
from app.marketdata.models import Base, Candle
from app.strategy_v1 import compute_atr, compute_sma, generate_signal


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def _candle(open_time: datetime, close: float, high: float, low: float) -> Candle:
    return Candle(
        symbol="EURUSD",
        timeframe="M5",
        open_time=open_time,
        open=close,
        high=max(high, close),
        low=min(low, close),
        close=close,
        volume=0.0,
        source="mock",
    )


def _build_oscillating_candles(n: int = 200) -> list[Candle]:
    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = []
    for i in range(n):
        # Deterministic up/down waves to force several crossovers.
        wave = ((i % 40) - 20) / 2000.0
        close = 1.1000 + wave
        high = close + 0.0008
        low = close - 0.0008
        candles.append(_candle(base + timedelta(minutes=5 * i), close, high, low))
    return candles


def test_indicator_correctness_sma_and_atr():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    sma3 = compute_sma(closes, 3)
    assert sma3 == [None, None, 2.0, 3.0, 4.0]

    highs = [1.1, 2.1, 3.1, 4.1, 5.1]
    lows = [0.9, 1.9, 2.9, 3.9, 4.9]
    atr3 = compute_atr(highs, lows, closes, 3)
    # First ATR appears at index period (=3) and should be positive.
    assert atr3[:3] == [None, None, None]
    assert atr3[3] is not None and atr3[3] > 0
    assert atr3[4] is not None and atr3[4] > 0


def test_signal_determinism_same_input_same_key():
    candles = _build_oscillating_candles(120)

    sig1 = generate_signal(
        candles,
        symbol="EURUSD",
        timeframe="M5",
        qty=1.0,
        sma_fast=20,
        sma_slow=50,
        atr_period=14,
        atr_sl_mult=2.0,
        atr_tp_mult=3.0,
    )
    sig2 = generate_signal(
        candles,
        symbol="EURUSD",
        timeframe="M5",
        qty=1.0,
        sma_fast=20,
        sma_slow=50,
        atr_period=14,
        atr_sl_mult=2.0,
        atr_tp_mult=3.0,
    )

    assert sig1 == sig2
    if sig1 is not None:
        assert sig1.idempotency_key == sig2.idempotency_key


@pytest.mark.asyncio
async def test_strategy_integration_200_candles_replay_idempotent(session, monkeypatch):
    candles = _build_oscillating_candles(200)

    # Pass 1: ingest progressively, run strategy on each closed candle.
    orders_after_first_pass = 0
    for i, candle in enumerate(candles):
        session.add(candle)
        await session.commit()

        signal = generate_signal(
            candles[: i + 1],
            symbol=Config.SYMBOL,
            timeframe=Config.TIMEFRAME,
            qty=1.0,
            sma_fast=20,
            sma_slow=50,
            atr_period=14,
            atr_sl_mult=2.0,
            atr_tp_mult=3.0,
        )
        if signal is None:
            continue

        await place_market_order(
            session,
            signal.symbol,
            signal.side,
            signal.qty,
            sl=signal.sl,
            tp=signal.tp,
            reason="strategy_v1_entry",
            idempotency_key=signal.idempotency_key,
        )

    orders_after_first_pass = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    assert orders_after_first_pass > 0

    # Pass 2 (re-run same sequence): same signals + same idempotency keys must not create new orders.
    for i in range(len(candles)):
        signal = generate_signal(
            candles[: i + 1],
            symbol=Config.SYMBOL,
            timeframe=Config.TIMEFRAME,
            qty=1.0,
            sma_fast=20,
            sma_slow=50,
            atr_period=14,
            atr_sl_mult=2.0,
            atr_tp_mult=3.0,
        )
        if signal is None:
            continue

        await place_market_order(
            session,
            signal.symbol,
            signal.side,
            signal.qty,
            sl=signal.sl,
            tp=signal.tp,
            reason="strategy_v1_entry",
            idempotency_key=signal.idempotency_key,
        )

    orders_after_second_pass = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    assert orders_after_second_pass == orders_after_first_pass

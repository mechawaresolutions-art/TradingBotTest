from datetime import datetime, timedelta, timezone

import pytest

from app.marketdata.models import Candle
from app.strategy_engine.ema_atr import EmaAtrStrategy
from app.strategy_engine.service import StrategyRunner


def make_candles(closes: list[float], symbol: str = "EURUSD", timeframe: str = "M5") -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        ts = start + timedelta(minutes=5 * idx)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=ts,
                open=close,
                high=close + 0.0005,
                low=close - 0.0005,
                close=close,
                volume=0.0,
                source="mock",
            )
        )
    return candles


def test_cross_up_emits_buy_intent():
    strategy = EmaAtrStrategy(
        params={
            "ema_fast_period": 2,
            "ema_slow_period": 3,
            "atr_period": 3,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
        }
    )
    candles = make_candles([5.0, 4.0, 3.0, 2.0, 1.0, 2.0, 3.0])

    intent = strategy.compute_intent(candles)

    assert intent.action == "BUY"
    assert intent.reason == "cross_up"
    assert intent.ts == candles[-1].open_time


def test_cross_down_emits_sell_intent():
    strategy = EmaAtrStrategy(
        params={
            "ema_fast_period": 2,
            "ema_slow_period": 3,
            "atr_period": 3,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
        }
    )
    candles = make_candles([1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0])

    intent = strategy.compute_intent(candles)

    assert intent.action == "SELL"
    assert intent.reason == "cross_down"
    assert intent.ts == candles[-1].open_time


@pytest.mark.asyncio
async def test_runner_not_enough_candles_returns_hold():
    candles = make_candles([1.1, 1.2, 1.3])

    runner = StrategyRunner(session=None, warmup_limit=200)  # type: ignore[arg-type]
    async def fake_fetch(symbol: str, timeframe: str, *, limit: int) -> list[Candle]:
        return candles

    runner._fetch_recent_candles = fake_fetch  # type: ignore[method-assign]
    intent = await runner.run(
        symbol="EURUSD",
        timeframe="M5",
        strategy_name="ema_atr",
        params={
            "ema_fast_period": 2,
            "ema_slow_period": 4,
            "atr_period": 4,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
        },
    )

    assert intent.action == "HOLD"
    assert "insufficient_data" in intent.reason


def test_atr_risk_hints_sanity_for_buy():
    strategy = EmaAtrStrategy(
        params={
            "ema_fast_period": 2,
            "ema_slow_period": 3,
            "atr_period": 3,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
        }
    )
    candles = make_candles([5.0, 4.0, 3.0, 2.0, 1.0, 2.0, 3.0])

    intent = strategy.compute_intent(candles)

    assert intent.action == "BUY"
    assert intent.indicators.atr is not None
    assert intent.risk_hints.stop_loss_price is not None
    assert intent.risk_hints.take_profit_price is not None

    close = candles[-1].close
    atr = intent.indicators.atr
    sl_dist = close - intent.risk_hints.stop_loss_price
    tp_dist = intent.risk_hints.take_profit_price - close

    assert sl_dist == pytest.approx(1.5 * atr, rel=1e-9)
    assert tp_dist == pytest.approx(2.0 * atr, rel=1e-9)

"""Strategy v1: SMA crossover with ATR-based SL/TP."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    timeframe: str
    candle_open_time: datetime
    side: str
    qty: float
    sl: float
    tp: float
    idempotency_key: str


def compute_sma(values: Sequence[float], period: int) -> list[Optional[float]]:
    """Return SMA series aligned with input length."""
    if period <= 0:
        raise ValueError("period must be > 0")

    out: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out

    rolling_sum = sum(values[:period])
    out[period - 1] = rolling_sum / period

    for idx in range(period, len(values)):
        rolling_sum += values[idx] - values[idx - period]
        out[idx] = rolling_sum / period

    return out


def _true_range(curr_high: float, curr_low: float, prev_close: float) -> float:
    return max(curr_high - curr_low, abs(curr_high - prev_close), abs(curr_low - prev_close))


def compute_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> list[Optional[float]]:
    """Return ATR series aligned with input length."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs/lows/closes must have same length")

    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n < 2:
        return out

    tr_values: list[float] = [0.0]
    for i in range(1, n):
        tr_values.append(_true_range(highs[i], lows[i], closes[i - 1]))

    if n <= period:
        return out

    # First ATR is average of TR[1..period]
    first_atr = sum(tr_values[1: period + 1]) / period
    out[period] = first_atr

    # Wilder smoothing
    prev_atr = first_atr
    for i in range(period + 1, n):
        prev_atr = ((prev_atr * (period - 1)) + tr_values[i]) / period
        out[i] = prev_atr

    return out


def _build_idempotency_key(symbol: str, timeframe: str, candle_open_time: datetime, side: str) -> str:
    return f"strategy_v1:{symbol}:{timeframe}:{candle_open_time.isoformat()}:{side}"


def _extract_series(candles: Sequence[object]) -> tuple[list[float], list[float], list[float]]:
    closes = [float(c.close) for c in candles]
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    return highs, lows, closes


def generate_signal(
    candles: Sequence[object],
    *,
    symbol: str,
    timeframe: str,
    qty: float,
    sma_fast: int = 20,
    sma_slow: int = 50,
    atr_period: int = 14,
    atr_sl_mult: float = 2.0,
    atr_tp_mult: float = 3.0,
) -> Optional[StrategySignal]:
    """Generate deterministic signal from candle history (uses latest closed candle)."""
    if sma_fast <= 0 or sma_slow <= 0 or atr_period <= 0:
        raise ValueError("periods must be > 0")
    if sma_fast >= sma_slow:
        raise ValueError("sma_fast must be < sma_slow")

    min_needed = max(sma_slow + 1, atr_period + 1)
    if len(candles) < min_needed:
        return None

    highs, lows, closes = _extract_series(candles)
    sma_f = compute_sma(closes, sma_fast)
    sma_s = compute_sma(closes, sma_slow)
    atr = compute_atr(highs, lows, closes, atr_period)

    i = len(candles) - 1
    prev = i - 1

    if sma_f[prev] is None or sma_s[prev] is None or sma_f[i] is None or sma_s[i] is None:
        return None
    if atr[i] is None:
        return None

    side: Optional[str] = None
    if sma_f[prev] <= sma_s[prev] and sma_f[i] > sma_s[i]:
        side = "BUY"
    elif sma_f[prev] >= sma_s[prev] and sma_f[i] < sma_s[i]:
        side = "SELL"

    if side is None:
        return None

    entry = closes[i]
    atr_val = float(atr[i])

    if side == "BUY":
        sl = entry - (atr_val * atr_sl_mult)
        tp = entry + (atr_val * atr_tp_mult)
    else:
        sl = entry + (atr_val * atr_sl_mult)
        tp = entry - (atr_val * atr_tp_mult)

    candle_open_time = candles[i].open_time
    key = _build_idempotency_key(symbol, timeframe, candle_open_time, side)

    return StrategySignal(
        symbol=symbol,
        timeframe=timeframe,
        candle_open_time=candle_open_time,
        side=side,
        qty=qty,
        sl=float(sl),
        tp=float(tp),
        idempotency_key=key,
    )

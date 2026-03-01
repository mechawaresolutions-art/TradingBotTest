"""Indicator calculations for MACRO 8."""
from __future__ import annotations

from typing import Sequence


def compute_ema(values: Sequence[float], period: int) -> list[float | None]:
    """Return EMA values aligned with input length."""
    if period <= 0:
        raise ValueError("period must be > 0")

    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out

    seed = sum(values[:period]) / period
    idx = period - 1
    out[idx] = seed

    alpha = 2.0 / (period + 1.0)
    ema_prev = seed
    for i in range(idx + 1, len(values)):
        ema_prev = ((values[i] - ema_prev) * alpha) + ema_prev
        out[i] = ema_prev

    return out


def _true_range(curr_high: float, curr_low: float, prev_close: float) -> float:
    return max(curr_high - curr_low, abs(curr_high - prev_close), abs(curr_low - prev_close))


def compute_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> list[float | None]:
    """Return Wilder ATR values aligned with input length."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs/lows/closes must have same length")

    n = len(closes)
    out: list[float | None] = [None] * n
    if n < 2:
        return out

    tr_values: list[float] = [0.0]
    for i in range(1, n):
        tr_values.append(_true_range(highs[i], lows[i], closes[i - 1]))

    if n <= period:
        return out

    first_atr = sum(tr_values[1 : period + 1]) / period
    out[period] = first_atr

    prev_atr = first_atr
    for i in range(period + 1, n):
        prev_atr = ((prev_atr * (period - 1)) + tr_values[i]) / period
        out[i] = prev_atr

    return out

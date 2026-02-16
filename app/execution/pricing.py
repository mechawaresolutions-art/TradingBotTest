"""Deterministic pricing utilities for Macro 5 execution."""
from __future__ import annotations

from dataclasses import dataclass


PIP_VALUE_EURUSD = 0.0001


@dataclass(frozen=True)
class PriceQuote:
    bid: float
    ask: float


class PricingModel:
    """Deterministic bid/ask and slippage calculations."""

    @staticmethod
    def quote(candle, spread_pips: float) -> tuple[float, float]:
        mid = float(candle.open)
        spread = float(spread_pips) * PIP_VALUE_EURUSD
        bid = mid - (spread / 2.0)
        ask = mid + (spread / 2.0)
        return bid, ask

    @staticmethod
    def apply_slippage(side: str, bid: float, ask: float, slippage_pips: float) -> float:
        slip = float(slippage_pips) * PIP_VALUE_EURUSD
        side_upper = side.upper()
        if side_upper == "BUY":
            return ask + slip
        if side_upper == "SELL":
            return bid - slip
        raise RuntimeError(f"Unsupported side for deterministic execution: {side}")

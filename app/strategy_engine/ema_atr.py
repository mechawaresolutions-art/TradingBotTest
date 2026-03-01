"""EMA crossover + ATR risk-hint strategy."""
from __future__ import annotations

from typing import Any, TypedDict

from app.marketdata.models import Candle
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.indicators import compute_atr, compute_ema
from app.strategy_engine.schemas import StrategyIndicators, StrategyIntent, StrategyRiskHints


class EmaAtrParams(TypedDict):
    ema_fast_period: int
    ema_slow_period: int
    atr_period: int
    sl_atr_mult: float
    tp_atr_mult: float


class EmaAtrStrategy(BaseStrategy[EmaAtrParams]):
    name = "ema_atr"
    default_params: dict[str, Any] = {
        "ema_fast_period": 20,
        "ema_slow_period": 50,
        "atr_period": 14,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
    }

    def _validate_params(self, params: dict[str, Any]) -> EmaAtrParams:
        ema_fast = int(params["ema_fast_period"])
        ema_slow = int(params["ema_slow_period"])
        atr_period = int(params["atr_period"])
        sl_atr_mult = float(params["sl_atr_mult"])
        tp_atr_mult = float(params["tp_atr_mult"])

        if ema_fast <= 0 or ema_slow <= 0 or atr_period <= 0:
            raise ValueError("ema/atr periods must be > 0")
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast_period must be < ema_slow_period")
        if sl_atr_mult <= 0 or tp_atr_mult <= 0:
            raise ValueError("sl_atr_mult and tp_atr_mult must be > 0")

        return EmaAtrParams(
            ema_fast_period=ema_fast,
            ema_slow_period=ema_slow,
            atr_period=atr_period,
            sl_atr_mult=sl_atr_mult,
            tp_atr_mult=tp_atr_mult,
        )

    def minimum_candles(self) -> int:
        return max(self.params["ema_slow_period"] + 1, self.params["atr_period"] + 1)

    def compute_intent(self, candles: list[Candle]) -> StrategyIntent:
        if not candles:
            return StrategyIntent(
                action="HOLD",
                reason="insufficient_data",
                symbol="",
                timeframe="",
                ts=None,
                indicators=StrategyIndicators(),
                risk_hints=StrategyRiskHints(),
                summary="no candles => HOLD (insufficient_data)",
            )

        latest = candles[-1]
        symbol = str(latest.symbol).upper()
        timeframe = str(latest.timeframe).upper()
        ts = latest.open_time

        if len(candles) < self.minimum_candles():
            return StrategyIntent(
                action="HOLD",
                reason="insufficient_data",
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                indicators=StrategyIndicators(),
                risk_hints=StrategyRiskHints(),
                summary=(
                    f"{symbol} {timeframe} candles={len(candles)} required={self.minimum_candles()}"
                    " => HOLD (insufficient_data)"
                ),
            )

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]

        ema_fast_series = compute_ema(closes, self.params["ema_fast_period"])
        ema_slow_series = compute_ema(closes, self.params["ema_slow_period"])
        atr_series = compute_atr(highs, lows, closes, self.params["atr_period"])

        idx = len(candles) - 1
        prev_idx = idx - 1

        ema_fast = ema_fast_series[idx]
        ema_slow = ema_slow_series[idx]
        atr = atr_series[idx]
        prev_fast = ema_fast_series[prev_idx]
        prev_slow = ema_slow_series[prev_idx]

        if None in (ema_fast, ema_slow, atr, prev_fast, prev_slow):
            return StrategyIntent(
                action="HOLD",
                reason="insufficient_data",
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                indicators=StrategyIndicators(ema_fast=ema_fast, ema_slow=ema_slow, atr=atr),
                risk_hints=StrategyRiskHints(),
                summary=f"{symbol} {timeframe} indicator warmup incomplete => HOLD (insufficient_data)",
            )

        action = "HOLD"
        reason = "no_cross"

        if prev_fast <= prev_slow and ema_fast > ema_slow:
            action = "BUY"
            reason = "cross_up"
        elif prev_fast >= prev_slow and ema_fast < ema_slow:
            action = "SELL"
            reason = "cross_down"

        close_price = closes[idx]
        stop_loss = None
        take_profit = None
        if action == "BUY":
            stop_loss = close_price - (atr * self.params["sl_atr_mult"])
            take_profit = close_price + (atr * self.params["tp_atr_mult"])
        elif action == "SELL":
            stop_loss = close_price + (atr * self.params["sl_atr_mult"])
            take_profit = close_price - (atr * self.params["tp_atr_mult"])

        summary = (
            f"{symbol} {timeframe} ema{self.params['ema_fast_period']}={ema_fast:.6f}, "
            f"ema{self.params['ema_slow_period']}={ema_slow:.6f}, atr={atr:.6f} "
            f"=> {action} ({reason}), "
            f"SL={self._fmt_price(stop_loss)}, TP={self._fmt_price(take_profit)}"
        )

        return StrategyIntent(
            action=action,
            reason=reason,
            symbol=symbol,
            timeframe=timeframe,
            ts=ts,
            indicators=StrategyIndicators(ema_fast=ema_fast, ema_slow=ema_slow, atr=atr),
            risk_hints=StrategyRiskHints(stop_loss_price=stop_loss, take_profit_price=take_profit),
            summary=summary,
        )

    @staticmethod
    def _fmt_price(value: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{value:.6f}"

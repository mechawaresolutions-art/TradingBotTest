"""Service layer for MACRO 8 strategy execution."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.models import Candle
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.ema_atr import EmaAtrStrategy
from app.strategy_engine.schemas import StrategyCatalogItem, StrategyIndicators, StrategyIntent, StrategyRiskHints


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    tf = timeframe.upper()
    if tf.startswith("M"):
        return timedelta(minutes=int(tf[1:]))
    if tf.startswith("H"):
        return timedelta(hours=int(tf[1:]))
    if tf.startswith("D"):
        return timedelta(days=int(tf[1:]))
    raise ValueError(f"Unsupported timeframe: {timeframe}")


class StrategyRunner:
    """Loads deterministic candle history and runs pure strategies."""

    _registry: dict[str, type[BaseStrategy]] = {
        EmaAtrStrategy.name: EmaAtrStrategy,
    }

    def __init__(self, session: AsyncSession, warmup_limit: int = 200) -> None:
        self.session = session
        self.warmup_limit = warmup_limit

    @classmethod
    def list_strategies(cls) -> list[StrategyCatalogItem]:
        out: list[StrategyCatalogItem] = []
        for key, strategy_cls in cls._registry.items():
            out.append(StrategyCatalogItem(strategy=key, default_params=dict(strategy_cls.default_params)))
        return out

    @classmethod
    def create_strategy(cls, strategy_name: str, params: dict[str, Any] | None = None) -> BaseStrategy:
        key = strategy_name.lower()
        strategy_cls = cls._registry.get(key)
        if strategy_cls is None:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        return strategy_cls(params=params)

    async def run(
        self,
        *,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        params: dict[str, Any] | None = None,
    ) -> StrategyIntent:
        symbol_norm = symbol.upper()
        timeframe_norm = timeframe.upper()

        strategy = self.create_strategy(strategy_name, params)

        candles = await self._fetch_recent_candles(symbol_norm, timeframe_norm, limit=self.warmup_limit)
        if len(candles) < strategy.minimum_candles():
            latest_ts = candles[-1].open_time if candles else None
            reason = "insufficient_data"
            if self._has_gap(candles, timeframe_norm):
                reason = "insufficient_data,data_gap_detected"
            return StrategyIntent(
                action="HOLD",
                reason=reason,
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                ts=latest_ts,
                indicators=StrategyIndicators(),
                risk_hints=StrategyRiskHints(),
                summary=(
                    f"{symbol_norm} {timeframe_norm} candles={len(candles)} "
                    f"required={strategy.minimum_candles()} => HOLD ({reason})"
                ),
            )

        intent = strategy.compute_intent(candles)
        if intent.symbol and intent.symbol != symbol_norm:
            raise RuntimeError("Strategy output symbol mismatch")
        if intent.timeframe and intent.timeframe != timeframe_norm:
            raise RuntimeError("Strategy output timeframe mismatch")

        intent.symbol = symbol_norm
        intent.timeframe = timeframe_norm

        if self._has_gap(candles, timeframe_norm):
            intent.reason = f"{intent.reason},data_gap_detected"
            intent.summary = f"{intent.summary} [data_gap_detected]"

        return intent

    async def _fetch_recent_candles(self, symbol: str, timeframe: str, *, limit: int) -> list[Candle]:
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(Candle.open_time.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        candles_desc = list(res.scalars().all())
        candles_desc.reverse()
        return candles_desc

    @staticmethod
    def _has_gap(candles: list[Candle], timeframe: str) -> bool:
        if len(candles) < 2:
            return False
        expected_step = _timeframe_to_timedelta(timeframe)
        for prev, curr in zip(candles[:-1], candles[1:]):
            if (curr.open_time - prev.open_time) != expected_step:
                return True
        return False

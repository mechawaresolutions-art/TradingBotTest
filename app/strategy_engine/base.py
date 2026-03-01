"""Strategy abstractions for MACRO 8."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from app.marketdata.models import Candle
from app.strategy_engine.schemas import StrategyIntent


ParamsT = TypeVar("ParamsT", bound=dict[str, Any])


class BaseStrategy(ABC, Generic[ParamsT]):
    """Base class for pure deterministic strategies."""

    name: str = "base"
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        merged = dict(self.default_params)
        if params:
            merged.update(params)
        self.params: ParamsT = self._validate_params(merged)

    def _validate_params(self, params: dict[str, Any]) -> ParamsT:
        return params  # type: ignore[return-value]

    @abstractmethod
    def minimum_candles(self) -> int:
        """Return minimum number of candles required for a stable signal."""

    @abstractmethod
    def compute_intent(self, candles: list[Candle]) -> StrategyIntent:
        """Compute an intent from deterministic candle history."""

    def reset(self) -> None:
        """Reset internal strategy state (MVP strategies are stateless)."""

    def get_state(self) -> dict[str, Any]:
        """Return serializable strategy state for observability."""
        return {"params": dict(self.params)}

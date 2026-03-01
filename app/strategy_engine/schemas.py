"""Pydantic schemas for MACRO 8 strategy engine."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


StrategyAction = Literal["BUY", "SELL", "HOLD", "CLOSE"]


class StrategyIndicators(BaseModel):
    ema_fast: float | None = None
    ema_slow: float | None = None
    atr: float | None = None


class StrategyRiskHints(BaseModel):
    stop_loss_price: float | None = None
    take_profit_price: float | None = None


class StrategyIntent(BaseModel):
    action: StrategyAction
    reason: str
    symbol: str
    timeframe: str
    ts: datetime | None = None
    indicators: StrategyIndicators
    risk_hints: StrategyRiskHints
    summary: str


class StrategyCatalogItem(BaseModel):
    strategy: str
    default_params: dict[str, Any]


class StrategyCatalogOut(BaseModel):
    strategies: list[StrategyCatalogItem]


class StrategyRunRequest(BaseModel):
    symbol: str = Field(default="EURUSD")
    timeframe: str = Field(default="M5")
    strategy: str = Field(default="ema_atr")
    params: dict[str, Any] = Field(default_factory=dict)

"""Schemas for Macro 9 orchestrator."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["OK", "NOOP", "ERROR"]
RunMode = Literal["execute", "dry_run"]


class OrderPlan(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str


class RunReportModel(BaseModel):
    run_id: str
    symbol: str
    timeframe: str
    candle_ts: datetime
    status: RunStatus
    intent_json: dict[str, Any] | None = None
    risk_json: dict[str, Any] | None = None
    order_json: dict[str, Any] | None = None
    fill_json: dict[str, Any] | None = None
    positions_json: dict[str, Any] | None = None
    account_json: dict[str, Any] | None = None
    summary_text: str
    telegram_text: str
    error_text: str | None = None
    mode: RunMode


class OrchestratorRunRequest(BaseModel):
    symbol: str = Field(default="EURUSD")
    timeframe: str = Field(default="M5")
    candle_ts: datetime
    mode: RunMode = "execute"


class OrchestratorRunResult(BaseModel):
    run_id: str
    status: RunStatus
    candle_ts: datetime
    summary: str
    telegram_text: str
    details: dict[str, Any] | None = None

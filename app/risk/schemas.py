"""Pydantic schemas for Macro 6 Risk Engine."""
from __future__ import annotations

from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field


class RiskSnapshotOut(BaseModel):
    account_id: int
    asof_open_time: datetime
    day: date
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    open_positions_count: int
    open_positions_per_symbol: int
    notional_per_symbol: float
    total_notional: float
    day_start_equity: float
    min_equity: float
    daily_loss_breached: bool


class RiskDecisionOut(BaseModel):
    allowed: bool
    approved_qty: float
    reason: str | None = None
    metrics: RiskSnapshotOut


class RiskCheckIn(BaseModel):
    account_id: int = Field(default=1)
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float = Field(gt=0)
    stop_distance_pips: float | None = Field(default=None, ge=0)
    asof_open_time: datetime | None = None


class RiskStatusOut(BaseModel):
    account_id: int
    limits: dict
    snapshot: RiskSnapshotOut

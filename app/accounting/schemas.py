"""Pydantic schemas for Macro 7 accounting API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PositionOut(BaseModel):
    account_id: int
    symbol: str
    net_qty: float
    avg_entry_price: float
    updated_open_time: datetime


class SnapshotOut(BaseModel):
    account_id: int
    asof_open_time: datetime
    balance: float
    equity: float
    unrealized_pnl: float
    margin_used: float
    free_margin: float


class RealizedTradeOut(BaseModel):
    id: int
    account_id: int
    symbol: str
    open_time: datetime
    closed_qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    fill_id: int | None
    order_id: int | None


class AccountStatusOut(BaseModel):
    snapshot: SnapshotOut
    position: PositionOut | None
    realized_trades: list[RealizedTradeOut]


class RecomputeIn(BaseModel):
    account_id: int
    symbol: str
    timeframe: str
    from_open_time: datetime
    to_open_time: datetime


class RecomputeOut(BaseModel):
    processed_candles: int
    final_snapshot: SnapshotOut | None

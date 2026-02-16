"""Pydantic schemas for OMS API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OMSPlaceOrderIn(BaseModel):
    symbol: str = Field(..., examples=["EURUSD"])
    side: Literal["BUY", "SELL"]
    qty: float = Field(..., gt=0)
    type: Literal["market"] = "market"
    stop_loss: float | None = None
    take_profit: float | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class OMSOrderOut(BaseModel):
    order_id: int
    status: Literal["NEW", "FILLED", "REJECTED", "CANCELED"]
    reason: str | None = None
    fill_id: int | None = None


class OMSOrderRowOut(BaseModel):
    id: int
    ts: datetime
    symbol: str
    side: str
    type: str
    qty: float
    status: str
    reason: str | None
    requested_price: float | None
    idempotency_key: str | None
    fill_id: int | None = None

"""Deterministic execution engine for Macro 5."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.execution.pricing import PricingModel


@dataclass(frozen=True)
class OrderInput:
    order_id: int
    symbol: str
    side: str
    type: str
    qty: float
    created_candle_time: datetime
    status: str


@dataclass(frozen=True)
class CandleInput:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class FillOutput:
    fill_id: int | None
    order_id: int
    symbol: str
    side: str
    qty: float
    price: float
    fill_candle_time: datetime
    spread_pips: float
    slippage_pips: float


@dataclass(frozen=True)
class ExecutionError:
    error_type: str
    message: str
    order_id: int


class ExecutionEngine:
    """Converts an eligible NEW market order into a deterministic fill output."""

    def __init__(self, spread_pips: float, slippage_pips: float):
        self.spread_pips = float(spread_pips)
        self.slippage_pips = float(slippage_pips)

    def execute_market_order(self, order: OrderInput, fill_candle: CandleInput) -> FillOutput:
        if order.qty <= 0:
            raise RuntimeError("Invalid qty for deterministic execution: qty must be > 0")
        if order.type.upper() != "MARKET":
            raise RuntimeError(f"Unsupported order type for deterministic execution: {order.type}")
        if order.side.upper() not in ("BUY", "SELL"):
            raise RuntimeError(f"Unsupported side for deterministic execution: {order.side}")

        bid, ask = PricingModel.quote(fill_candle, self.spread_pips)
        fill_price = PricingModel.apply_slippage(order.side, bid, ask, self.slippage_pips)

        return FillOutput(
            fill_id=None,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.upper(),
            qty=float(order.qty),
            price=float(fill_price),
            fill_candle_time=fill_candle.open_time,
            spread_pips=self.spread_pips,
            slippage_pips=self.slippage_pips,
        )

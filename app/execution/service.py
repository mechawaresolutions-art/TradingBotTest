"""Paper broker execution service."""
import logging
from typing import Optional, Tuple
from decimal import Decimal
from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Config
from app.execution.models import Account, Order, Fill, Position, Trade
from datetime import datetime
from app.marketdata.models import Candle

logger = logging.getLogger(__name__)


PIP_VALUE = 0.0001  # EURUSD pip size


async def _get_latest_candle(session: AsyncSession, symbol: str, timeframe: str) -> Optional[Candle]:
    stmt = select(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe).order_by(Candle.open_time.desc()).limit(1)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


def _price_from_mid(mid: float, spread_pips: float, side: str) -> float:
    half = (spread_pips * PIP_VALUE) / 2.0
    if side.upper() == "BUY":
        return mid + half  # BUY fills at ask
    else:
        return mid - half  # SELL fills at bid


async def ensure_account(session: AsyncSession) -> Account:
    stmt = select(Account).limit(1)
    res = await session.execute(stmt)
    acct = res.scalar_one_or_none()
    if acct is None:
        acct = Account(balance=Config.INITIAL_BALANCE, currency="USD", leverage=1.0)
        session.add(acct)
        await session.commit()
        await session.refresh(acct)
    return acct


async def place_market_order(
    session: AsyncSession,
    symbol: str,
    side: str,
    qty: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    reason: str = "",
) -> Tuple[Order, Fill]:
    """Place a market order and create a fill deterministically from latest candle.

    Returns (order, fill).
    """
    # Determine fill price from latest candle
    candle = await _get_latest_candle(session, symbol, Config.TIMEFRAME)
    if candle is None:
        # create rejected order with reason
        order = Order(symbol=symbol, side=side.upper(), qty=qty, reason="no_market_data", status="rejected", ts=func.now())
        session.add(order)
        await session.commit()
        await session.refresh(order)
        raise RuntimeError("No market data available for fills")

    mid = float(candle.close)
    fill_price = _price_from_mid(mid, Config.SPREAD_PIPS, side)

    # Create order record with deterministic ts == candle.open_time
    order = Order(symbol=symbol, side=side.upper(), qty=qty, reason=reason, status="filled", ts=candle.open_time)
    session.add(order)
    await session.flush()

    fill = Fill(order_id=order.id, symbol=symbol, side=side.upper(), qty=qty, price=fill_price, fee=0.0, slippage=0.0, ts=candle.open_time)
    session.add(fill)

    # Update / create position
    stmt = select(Position).where(Position.symbol == symbol)
    res = await session.execute(stmt)
    pos = res.scalar_one_or_none()

    qty_signed = qty if side.upper() == "BUY" else -qty

    if pos is None:
        # open new position (use candle.open_time for deterministic opened_at)
        pos = Position(symbol=symbol, qty_signed=qty_signed, avg_price=fill_price, stop_loss=sl, take_profit=tp, opened_at=candle.open_time, entry_order_id=order.id)
        session.add(pos)
    else:
        # netting rules
        existing = pos.qty_signed
        # same direction
        if existing == 0 or (existing > 0 and qty_signed > 0) or (existing < 0 and qty_signed < 0):
            new_qty = existing + qty_signed
            # weighted average
            if new_qty != 0:
                avg = (existing * pos.avg_price + qty_signed * fill_price) / new_qty
            else:
                avg = fill_price
            pos.qty_signed = new_qty
            pos.avg_price = avg
            pos.stop_loss = sl if sl is not None else pos.stop_loss
            pos.take_profit = tp if tp is not None else pos.take_profit
        else:
            # opposite direction: reduce or flip
            if abs(qty_signed) < abs(existing):
                # partial close
                closed_qty = qty if existing > 0 else qty  # magnitude
                # realized pnl for closed part
                if existing > 0:
                    pnl = (fill_price - pos.avg_price) * closed_qty
                else:
                    pnl = (pos.avg_price - fill_price) * closed_qty
                # update position qty and realized pnl
                pos.qty_signed = existing + qty_signed
                pos.realized_pnl = pos.realized_pnl + pnl
            else:
                # closing existing fully, maybe opening new in opposite direction
                closed_qty = abs(existing)
                if existing > 0:
                    pnl = (fill_price - pos.avg_price) * closed_qty
                else:
                    pnl = (pos.avg_price - fill_price) * closed_qty
                pos.realized_pnl = pos.realized_pnl + pnl
                remaining = qty_signed + existing  # could be negative or positive
                if remaining == 0:
                    # fully closed
                    await session.delete(pos)
                else:
                    # flipped
                    pos.qty_signed = remaining
                    pos.avg_price = fill_price
                    pos.stop_loss = sl
                    pos.take_profit = tp
                    # update entry order id when we flipped and opened new net position
                    pos.entry_order_id = order.id

    # Commit records
    await session.commit()
    await session.refresh(order)
    await session.refresh(fill)
    return order, fill


async def mark_to_market(session: AsyncSession, symbol: str, bid: float, ask: float) -> dict:
    """Compute account equity/unrealized pnl for symbol using provided bid/ask."""
    acct = await ensure_account(session)
    stmt = select(Position).where(Position.symbol == symbol)
    res = await session.execute(stmt)
    pos = res.scalar_one_or_none()

    unrealized = 0.0
    if pos is not None:
        if pos.qty_signed > 0:
            # long: use bid to value position
            unrealized = (bid - pos.avg_price) * pos.qty_signed
        else:
            # short: use ask
            unrealized = (pos.avg_price - ask) * abs(pos.qty_signed)

    equity = acct.balance + unrealized
    return {"balance": acct.balance, "equity": equity, "unrealized": unrealized}


async def update_on_candle(session: AsyncSession, candle: Candle) -> list:
    """Check SL/TP for existing position on this candle and close if triggered.

    Returns list of executed trades (as dicts).
    """
    symbol = candle.symbol
    half_spread = (Config.SPREAD_PIPS * PIP_VALUE) / 2.0
    bid = float(candle.close) - half_spread
    ask = float(candle.close) + half_spread

    stmt = select(Position).where(Position.symbol == symbol)
    res = await session.execute(stmt)
    pos = res.scalar_one_or_none()
    executed = []
    if pos is None:
        return executed

    # Check triggers (deterministic order: stop_loss first, then take_profit)
    triggered = None
    exit_price = None
    exit_reason = None

    if pos.qty_signed > 0:
        # long: SL if low <= stop_loss, TP if high >= take_profit
        if pos.stop_loss is not None and candle.low <= pos.stop_loss:
            triggered = "SL"
            exit_price = bid
            exit_reason = "stop_loss"
        elif pos.take_profit is not None and candle.high >= pos.take_profit:
            triggered = "TP"
            exit_price = bid
            exit_reason = "take_profit"
    else:
        # short: SL if high >= stop_loss (above), TP if low <= take_profit
        if pos.stop_loss is not None and candle.high >= pos.stop_loss:
            triggered = "SL"
            exit_price = ask
            exit_reason = "stop_loss"
        elif pos.take_profit is not None and candle.low <= pos.take_profit:
            triggered = "TP"
            exit_price = ask
            exit_reason = "take_profit"

    if triggered:
        # Idempotency: if a trade already exists for this symbol with same exit_ts and reason, do nothing
        stmt_check = select(Trade).where(Trade.symbol == symbol, Trade.exit_ts == candle.open_time, Trade.exit_reason == exit_reason)
        res_check = await session.execute(stmt_check)
        existing_trade = res_check.scalar_one_or_none()
        if existing_trade is not None:
            return executed

        qty = abs(pos.qty_signed)
        entry_price = pos.avg_price
        if pos.qty_signed > 0:
            pnl = (exit_price - entry_price) * qty
        else:
            pnl = (entry_price - exit_price) * qty

        # Create synthetic order + fill record for the closing action with deterministic ts
        order = Order(symbol=symbol, side=("SELL" if pos.qty_signed > 0 else "BUY"), qty=qty, status="filled", reason=exit_reason, ts=candle.open_time)
        session.add(order)
        await session.flush()
        fill = Fill(order_id=order.id, symbol=symbol, side=order.side, qty=qty, price=exit_price, fee=0.0, slippage=0.0, ts=candle.open_time)
        session.add(fill)

        # Create trade record linking to entry/exit orders and using deterministic timestamps
        trade = Trade(entry_ts=pos.opened_at, exit_ts=candle.open_time, symbol=symbol, qty=qty, entry_price=entry_price, exit_price=exit_price, pnl=pnl, exit_reason=exit_reason, entry_order_id=pos.entry_order_id, exit_order_id=order.id)
        session.add(trade)

        # Update account balance with realized pnl and remove position
        acct = await ensure_account(session)
        acct.balance = acct.balance + pnl

        # delete position
        await session.delete(pos)

        await session.commit()
        executed.append({"symbol": symbol, "qty": qty, "exit_price": exit_price, "pnl": pnl, "reason": exit_reason})

    return executed

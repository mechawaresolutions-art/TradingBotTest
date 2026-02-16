"""Paper broker execution service."""
import logging
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.equity.service import compute_account_state, compute_additional_margin_for_netting
from app.execution.engine import CandleInput, ExecutionEngine, OrderInput
from app.execution.models import Account, Order, Fill, Position, Trade
from app.marketdata.models import Candle

logger = logging.getLogger(__name__)


PIP_VALUE = 0.0001  # EURUSD pip size


@asynccontextmanager
async def _transaction_scope(session: AsyncSession):
    """Open an explicit transaction unless caller already owns one."""
    if session.in_transaction():
        yield
    else:
        async with session.begin():
            yield


def _supports_for_update(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def _maybe_for_update(session: AsyncSession, stmt):
    return stmt.with_for_update() if _supports_for_update(session) else stmt


def derive_bid_ask(candle: Candle, spread_pips: float) -> tuple[float, float]:
    """Derive bid/ask from candle close (mid) and spread in pips."""
    mid = float(candle.close)
    spread_price = spread_pips * PIP_VALUE
    bid = mid - spread_price / 2.0
    ask = mid + spread_price / 2.0
    return bid, ask


def _build_trade(
    *,
    pos: Position,
    candle_time: datetime,
    qty: float,
    exit_price: float,
    pnl: float,
    exit_reason: str,
    exit_order_id: int,
) -> Trade:
    """Create a trade row for any realized-close event."""
    return Trade(
        entry_ts=pos.opened_at,
        exit_ts=candle_time,
        symbol=pos.symbol,
        qty=qty,
        entry_price=pos.avg_price,
        exit_price=exit_price,
        pnl=pnl,
        exit_reason=exit_reason,
        entry_order_id=pos.entry_order_id,
        exit_order_id=exit_order_id,
    )


async def _get_latest_candle(session: AsyncSession, symbol: str, timeframe: str) -> Optional[Candle]:
    stmt = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def _ensure_account_row(session: AsyncSession, for_update: bool = False) -> Account:
    stmt = select(Account).limit(1)
    if for_update:
        stmt = _maybe_for_update(session, stmt)

    res = await session.execute(stmt)
    acct = res.scalar_one_or_none()
    if acct is not None:
        return acct

    # Singleton account row.
    acct = Account(
        id=1,
        balance=Config.INITIAL_BALANCE,
        equity=Config.INITIAL_BALANCE,
        margin_used=0.0,
        free_margin=Config.INITIAL_BALANCE,
        currency=Config.ACCOUNT_CURRENCY,
        leverage=Config.ACCOUNT_LEVERAGE,
    )
    # Use a savepoint so a concurrent insert conflict does not poison the outer transaction.
    try:
        async with session.begin_nested():
            session.add(acct)
            await session.flush()
        return acct
    except IntegrityError:
        res_retry = await session.execute(stmt)
        acct_retry = res_retry.scalar_one_or_none()
        if acct_retry is None:
            raise
        return acct_retry


async def ensure_account(session: AsyncSession) -> Account:
    async with _transaction_scope(session):
        return await _ensure_account_row(session)


async def place_market_order(
    session: AsyncSession,
    symbol: str,
    side: str,
    qty: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    reason: str = "",
    idempotency_key: Optional[str] = None,
    existing_order_id: Optional[int] = None,
) -> Tuple[Order, Fill]:
    """Place a market order and create a fill deterministically from latest candle.

    Returns (order, fill).
    """
    side_upper = side.upper()

    # Retry once if concurrent position creation causes an integrity race.
    for attempt in range(2):
        try:
            order: Optional[Order] = None
            fill: Optional[Fill] = None

            async with _transaction_scope(session):
                if idempotency_key:
                    stmt_existing_order = select(Order).where(Order.idempotency_key == idempotency_key)
                    res_existing_order = await session.execute(stmt_existing_order)
                    existing_order = res_existing_order.scalar_one_or_none()
                    if existing_order is not None:
                        stmt_existing_fill = select(Fill).where(Fill.order_id == existing_order.id)
                        res_existing_fill = await session.execute(stmt_existing_fill)
                        existing_fill = res_existing_fill.scalar_one_or_none()
                        if existing_fill is None:
                            raise RuntimeError("Idempotency key matched order without fill")
                        return existing_order, existing_fill

                candle = await _get_latest_candle(session, symbol, Config.TIMEFRAME)
                if candle is None:
                    raise RuntimeError(
                        "No market data available for fills: deterministic execution requires latest candle.open_time"
                    )

                bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)
                fill_price = ask if side_upper == "BUY" else bid

                stmt_pos = _maybe_for_update(session, select(Position).where(Position.symbol == symbol))
                res_pos = await session.execute(stmt_pos)
                pos = res_pos.scalar_one_or_none()
                qty_signed = qty if side_upper == "BUY" else -qty
                current_qty = pos.qty_signed if pos is not None else 0.0

                mtm_state = await compute_account_state(session, candle)
                acct_locked = await _ensure_account_row(session, for_update=True)
                additional_margin = compute_additional_margin_for_netting(
                    current_qty_signed=current_qty,
                    order_qty_signed=qty_signed,
                    fill_price=fill_price,
                    leverage=acct_locked.leverage,
                )
                free_margin = float(mtm_state["free_margin"])
                if free_margin < additional_margin:
                    raise RuntimeError(
                        f"Insufficient free margin: required={additional_margin:.6f}, free={free_margin:.6f}"
                    )

                if existing_order_id is not None:
                    stmt_order = _maybe_for_update(session, select(Order).where(Order.id == existing_order_id))
                    res_order = await session.execute(stmt_order)
                    order = res_order.scalar_one_or_none()
                    if order is None:
                        raise RuntimeError(f"existing_order_id {existing_order_id} not found")
                    if order.status.upper() == "FILLED":
                        stmt_existing_fill = select(Fill).where(Fill.order_id == order.id)
                        res_existing_fill = await session.execute(stmt_existing_fill)
                        existing_fill = res_existing_fill.scalar_one_or_none()
                        if existing_fill is None:
                            raise RuntimeError("FILLED order exists without fill row")
                        return order, existing_fill
                    order.symbol = symbol
                    order.side = side_upper
                    order.qty = qty
                    order.reason = reason
                    order.status = "FILLED"
                    order.ts = candle.open_time
                    if idempotency_key is not None:
                        order.idempotency_key = idempotency_key
                    await session.flush()
                else:
                    order = Order(
                        symbol=symbol,
                        side=side_upper,
                        qty=qty,
                        reason=reason,
                        status="filled",
                        ts=candle.open_time,
                        idempotency_key=idempotency_key,
                    )
                    session.add(order)
                    await session.flush()

                fill = Fill(
                    order_id=order.id,
                    symbol=symbol,
                    side=side_upper,
                    qty=qty,
                    price=fill_price,
                    fee=0.0,
                    slippage=0.0,
                    ts=candle.open_time,
                )
                session.add(fill)
                await session.flush()

                if pos is None:
                    pos = Position(
                        symbol=symbol,
                        qty_signed=qty_signed,
                        avg_price=fill_price,
                        stop_loss=sl,
                        take_profit=tp,
                        opened_at=candle.open_time,
                        entry_order_id=order.id,
                    )
                    session.add(pos)
                else:
                    existing = pos.qty_signed
                    if existing == 0 or (existing > 0 and qty_signed > 0) or (existing < 0 and qty_signed < 0):
                        new_qty = existing + qty_signed
                        if new_qty != 0:
                            avg = (existing * pos.avg_price + qty_signed * fill_price) / new_qty
                        else:
                            avg = fill_price
                        pos.qty_signed = new_qty
                        pos.avg_price = avg
                        pos.stop_loss = sl if sl is not None else pos.stop_loss
                        pos.take_profit = tp if tp is not None else pos.take_profit
                    else:
                        exit_reason = reason or "manual_close"
                        acct = await _ensure_account_row(session, for_update=True)
                        if abs(qty_signed) < abs(existing):
                            closed_qty = qty
                            if existing > 0:
                                pnl = (fill_price - pos.avg_price) * closed_qty
                            else:
                                pnl = (pos.avg_price - fill_price) * closed_qty
                            pos.qty_signed = existing + qty_signed
                            pos.realized_pnl = pos.realized_pnl + pnl
                            acct.balance = acct.balance + pnl
                            session.add(
                                _build_trade(
                                    pos=pos,
                                    candle_time=candle.open_time,
                                    qty=closed_qty,
                                    exit_price=fill_price,
                                    pnl=pnl,
                                    exit_reason=exit_reason,
                                    exit_order_id=order.id,
                                )
                            )
                        else:
                            closed_qty = abs(existing)
                            if existing > 0:
                                pnl = (fill_price - pos.avg_price) * closed_qty
                            else:
                                pnl = (pos.avg_price - fill_price) * closed_qty
                            pos.realized_pnl = pos.realized_pnl + pnl
                            acct.balance = acct.balance + pnl
                            session.add(
                                _build_trade(
                                    pos=pos,
                                    candle_time=candle.open_time,
                                    qty=closed_qty,
                                    exit_price=fill_price,
                                    pnl=pnl,
                                    exit_reason=exit_reason,
                                    exit_order_id=order.id,
                                )
                            )
                            remaining = qty_signed + existing
                            if remaining == 0:
                                await session.delete(pos)
                            else:
                                pos.qty_signed = remaining
                                pos.avg_price = fill_price
                                pos.opened_at = candle.open_time
                                pos.stop_loss = sl
                                pos.take_profit = tp
                                pos.entry_order_id = order.id

            return order, fill

        except IntegrityError:
            if attempt == 0:
                await session.rollback()
                continue
            raise

    raise RuntimeError("Failed to place order due to repeated integrity errors")


async def mark_to_market(session: AsyncSession, symbol: str, bid: float, ask: float) -> dict:
    """Compute account equity/unrealized pnl for symbol using provided bid/ask."""
    acct = await ensure_account(session)

    stmt = select(Position).where(Position.symbol == symbol)
    res = await session.execute(stmt)
    pos = res.scalar_one_or_none()

    unrealized = 0.0
    if pos is not None:
        if pos.qty_signed > 0:
            unrealized = (bid - pos.avg_price) * pos.qty_signed
        else:
            unrealized = (pos.avg_price - ask) * abs(pos.qty_signed)

    equity = acct.balance + unrealized
    return {"balance": acct.balance, "equity": equity, "unrealized": unrealized}


async def update_on_candle(session: AsyncSession, candle: Candle) -> list:
    """Check SL/TP for existing position on this candle and close if triggered.

    Returns list of executed trades (as dicts).
    """
    symbol = candle.symbol
    bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)

    executed = []
    async with _transaction_scope(session):
        stmt_pos = _maybe_for_update(session, select(Position).where(Position.symbol == symbol))
        res_pos = await session.execute(stmt_pos)
        pos = res_pos.scalar_one_or_none()
        if pos is None:
            return executed

        triggered = None
        exit_price = None
        exit_reason = None

        if pos.qty_signed > 0:
            if pos.stop_loss is not None and candle.low <= pos.stop_loss:
                triggered = "SL"
                exit_price = bid
                exit_reason = "stop_loss"
            elif pos.take_profit is not None and candle.high >= pos.take_profit:
                triggered = "TP"
                exit_price = bid
                exit_reason = "take_profit"
        else:
            if pos.stop_loss is not None and candle.high >= pos.stop_loss:
                triggered = "SL"
                exit_price = ask
                exit_reason = "stop_loss"
            elif pos.take_profit is not None and candle.low <= pos.take_profit:
                triggered = "TP"
                exit_price = ask
                exit_reason = "take_profit"

        if not triggered:
            return executed

        stmt_check = select(Trade).where(
            Trade.symbol == symbol,
            Trade.exit_ts == candle.open_time,
            Trade.exit_reason == exit_reason,
        )
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

        order = Order(
            symbol=symbol,
            side=("SELL" if pos.qty_signed > 0 else "BUY"),
            qty=qty,
            status="filled",
            reason=exit_reason,
            ts=candle.open_time,
        )
        session.add(order)
        await session.flush()

        fill = Fill(
            order_id=order.id,
            symbol=symbol,
            side=order.side,
            qty=qty,
            price=exit_price,
            fee=0.0,
            slippage=0.0,
            ts=candle.open_time,
        )
        session.add(fill)

        trade = Trade(
            entry_ts=pos.opened_at,
            exit_ts=candle.open_time,
            symbol=symbol,
            qty=qty,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            exit_reason=exit_reason,
            entry_order_id=pos.entry_order_id,
            exit_order_id=order.id,
        )
        session.add(trade)

        acct = await _ensure_account_row(session, for_update=True)
        acct.balance = acct.balance + pnl

        await session.delete(pos)

        executed.append(
            {
                "symbol": symbol,
                "qty": qty,
                "exit_price": exit_price,
                "pnl": pnl,
                "reason": exit_reason,
            }
        )

    return executed


async def process_new_orders_for_candle(
    session: AsyncSession,
    fill_candle_open_time: datetime,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> list[Fill]:
    """Process eligible NEW market orders using deterministic next-open rule.

    Orders created on candle t are filled on candle t+1 open.
    """
    symbol = (symbol or Config.SYMBOL).upper()
    timeframe = timeframe or Config.TIMEFRAME

    stmt_fill_candle = select(Candle).where(
        Candle.symbol == symbol,
        Candle.timeframe == timeframe,
        Candle.open_time == fill_candle_open_time,
    )
    res_fill_candle = await session.execute(stmt_fill_candle)
    fill_candle = res_fill_candle.scalar_one_or_none()
    if fill_candle is None:
        raise RuntimeError(
            "No market data available for fills: deterministic execution requires latest candle.open_time"
        )

    engine = ExecutionEngine(
        spread_pips=Config.SPREAD_PIPS,
        slippage_pips=Config.EXECUTION_SLIPPAGE_PIPS,
    )
    created_fills: list[Fill] = []

    async with _transaction_scope(session):
        stmt_orders = (
            select(Order)
            .where(
                Order.symbol == symbol,
                func.upper(Order.status) == "NEW",
                func.lower(Order.type) == "market",
            )
            .order_by(Order.ts.asc(), Order.id.asc())
        )
        res_orders = await session.execute(stmt_orders)
        orders = list(res_orders.scalars().all())

        for order in orders:
            # Idempotency: one fill per order.
            res_existing_fill = await session.execute(select(Fill).where(Fill.order_id == order.id))
            existing_fill = res_existing_fill.scalar_one_or_none()
            if existing_fill is not None:
                if (order.status or "").upper() != "FILLED":
                    order.status = "FILLED"
                created_fills.append(existing_fill)
                continue

            if order.qty <= 0:
                order.status = "REJECTED"
                order.reason = "Invalid qty for deterministic execution: qty must be > 0"
                continue

            if (order.side or "").upper() not in ("BUY", "SELL"):
                order.status = "REJECTED"
                order.reason = f"Unsupported side for deterministic execution: {order.side}"
                continue

            stmt_next_candle = (
                select(Candle)
                .where(
                    Candle.symbol == order.symbol,
                    Candle.timeframe == timeframe,
                    Candle.open_time > order.ts,
                )
                .order_by(Candle.open_time.asc())
                .limit(1)
            )
            res_next_candle = await session.execute(stmt_next_candle)
            next_candle = res_next_candle.scalar_one_or_none()

            if next_candle is None:
                stmt_any = select(Candle.id).where(
                    Candle.symbol == order.symbol,
                    Candle.timeframe == timeframe,
                ).limit(1)
                res_any = await session.execute(stmt_any)
                has_any_candle = res_any.scalar_one_or_none() is not None
                if has_any_candle:
                    order.reason = (
                        "No market data available for fills: deterministic execution requires latest candle.open_time"
                    )
                else:
                    order.reason = f"Unknown symbol for deterministic execution: {order.symbol}"
                order.status = "REJECTED"
                continue

            # Not due for this runner candle yet.
            if next_candle.open_time != fill_candle.open_time:
                continue

            fill_output = engine.execute_market_order(
                OrderInput(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    type=order.type,
                    qty=order.qty,
                    created_candle_time=order.ts,
                    status=order.status,
                ),
                CandleInput(
                    open_time=next_candle.open_time,
                    open=next_candle.open,
                    high=next_candle.high,
                    low=next_candle.low,
                    close=next_candle.close,
                ),
            )

            fill = Fill(
                order_id=order.id,
                ts=next_candle.open_time,
                symbol=order.symbol,
                side=order.side.upper(),
                qty=order.qty,
                price=fill_output.price,
                fee=0.0,
                slippage=Config.EXECUTION_SLIPPAGE_PIPS,
            )
            session.add(fill)
            await session.flush()

            order.status = "FILLED"
            order.reason = None
            created_fills.append(fill)

    return created_fills

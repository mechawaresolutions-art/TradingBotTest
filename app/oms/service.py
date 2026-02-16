"""Order management service (Macro 4 OMS)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.equity.service import compute_account_state, compute_additional_margin_for_netting
from app.execution.models import Fill, Order, Position
from app.execution.pricing import PIP_VALUE_EURUSD
from app.execution.service import derive_bid_ask, place_market_order
from app.marketdata.models import Candle
from app.oms.schemas import OMSPlaceOrderIn
from app.risk.service import RiskEngine


@asynccontextmanager
async def _transaction_scope(session: AsyncSession):
    if session.in_transaction():
        yield
    else:
        async with session.begin():
            yield


def _normalize_status(status: str | None) -> str:
    if not status:
        return "NEW"
    s = status.upper()
    if s == "FILLED":
        return "FILLED"
    if s == "REJECTED":
        return "REJECTED"
    if s == "CANCELED":
        return "CANCELED"
    if s == "NEW":
        return "NEW"
    return s


async def _latest_candle(session: AsyncSession, symbol: str) -> Candle | None:
    stmt = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == Config.TIMEFRAME)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def _order_fill_id(session: AsyncSession, order_id: int) -> int | None:
    stmt = select(Fill.id).where(Fill.order_id == order_id).limit(1)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


def _validate_payload(payload: OMSPlaceOrderIn) -> str | None:
    symbol = payload.symbol.upper()
    if payload.type != "market":
        return "Only market orders are supported"
    if payload.qty < Config.OMS_MIN_QTY:
        return f"qty below minimum {Config.OMS_MIN_QTY}"
    if symbol not in Config.OMS_ALLOWED_SYMBOLS:
        return f"symbol {symbol} is not allowed"
    return None


async def _validate_margin(
    session: AsyncSession,
    candle: Candle,
    *,
    symbol: str,
    side: str,
    qty: float,
    fill_price: float,
) -> str | None:
    state = await compute_account_state(session, candle)

    stmt_pos = select(Position).where(Position.symbol == symbol.upper())
    res_pos = await session.execute(stmt_pos)
    pos = res_pos.scalar_one_or_none()

    current_qty = pos.qty_signed if pos is not None else 0.0
    qty_signed = qty if side == "BUY" else -qty
    additional_margin = compute_additional_margin_for_netting(
        current_qty_signed=current_qty,
        order_qty_signed=qty_signed,
        fill_price=fill_price,
        leverage=Config.ACCOUNT_LEVERAGE,
    )
    if float(state["free_margin"]) < additional_margin:
        return (
            "Insufficient free margin: "
            f"required={additional_margin:.6f}, free={float(state['free_margin']):.6f}"
        )
    return None


async def place_order(session: AsyncSession, payload: OMSPlaceOrderIn) -> dict:
    symbol = payload.symbol.upper()

    if payload.idempotency_key:
        stmt_existing = select(Order).where(Order.idempotency_key == payload.idempotency_key)
        res_existing = await session.execute(stmt_existing)
        existing = res_existing.scalar_one_or_none()
        if existing is not None:
            fill_id = await _order_fill_id(session, existing.id)
            return {
                "order_id": existing.id,
                "status": _normalize_status(existing.status),
                "reason": existing.reason,
                "fill_id": fill_id,
            }

    precheck_reason = _validate_payload(payload)

    candle_symbol = symbol if precheck_reason is None else Config.SYMBOL
    candle = await _latest_candle(session, candle_symbol)
    if candle is None:
        raise RuntimeError(f"No candle available for symbol={candle_symbol} timeframe={Config.TIMEFRAME}")

    async with _transaction_scope(session):
        if precheck_reason is not None:
            order = Order(
                ts=candle.open_time,
                symbol=symbol,
                side=payload.side,
                type="market",
                qty=payload.qty,
                status="REJECTED",
                reason=precheck_reason,
                requested_price=None,
                idempotency_key=payload.idempotency_key,
            )
            session.add(order)
            await session.flush()
            return {
                "order_id": order.id,
                "status": "REJECTED",
                "reason": precheck_reason,
                "fill_id": None,
            }

        bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)
        expected_fill_price = ask if payload.side == "BUY" else bid

        stop_distance_pips = None
        if payload.stop_loss is not None:
            stop_distance_pips = abs(float(expected_fill_price) - float(payload.stop_loss)) / PIP_VALUE_EURUSD

        risk_decision = await RiskEngine.check_order(
            session,
            account_id=1,
            symbol=symbol,
            side=payload.side,
            qty=payload.qty,
            stop_distance_pips=stop_distance_pips,
            asof_open_time=candle.open_time,
        )
        if not risk_decision.allowed:
            order = Order(
                ts=candle.open_time,
                symbol=symbol,
                side=payload.side,
                type="market",
                qty=payload.qty,
                status="REJECTED",
                reason=risk_decision.reason or "Risk check rejected order",
                requested_price=None,
                idempotency_key=payload.idempotency_key,
            )
            session.add(order)
            await session.flush()
            return {
                "order_id": order.id,
                "status": "REJECTED",
                "reason": order.reason,
                "fill_id": None,
            }

        approved_qty = float(risk_decision.approved_qty)
        if approved_qty <= 0:
            order = Order(
                ts=candle.open_time,
                symbol=symbol,
                side=payload.side,
                type="market",
                qty=payload.qty,
                status="REJECTED",
                reason="Risk-per-trade sizing reduced qty to zero",
                requested_price=None,
                idempotency_key=payload.idempotency_key,
            )
            session.add(order)
            await session.flush()
            return {
                "order_id": order.id,
                "status": "REJECTED",
                "reason": order.reason,
                "fill_id": None,
            }

        order = Order(
            ts=candle.open_time,
            symbol=symbol,
            side=payload.side,
            type="market",
            qty=approved_qty,
            status="NEW",
            reason=None,
            requested_price=None,
            idempotency_key=payload.idempotency_key,
        )
        session.add(order)
        await session.flush()

        margin_reason = await _validate_margin(
            session,
            candle,
            symbol=symbol,
            side=payload.side,
            qty=approved_qty,
            fill_price=expected_fill_price,
        )
        if margin_reason is not None:
            order.status = "REJECTED"
            order.reason = margin_reason
            return {
                "order_id": order.id,
                "status": "REJECTED",
                "reason": margin_reason,
                "fill_id": None,
            }

        try:
            _, fill = await place_market_order(
                session=session,
                symbol=symbol,
                side=payload.side,
                qty=approved_qty,
                sl=payload.stop_loss,
                tp=payload.take_profit,
                reason="oms_market",
                idempotency_key=None,
                existing_order_id=order.id,
            )
            order.status = "FILLED"
            order.reason = None
            return {
                "order_id": order.id,
                "status": "FILLED",
                "reason": None,
                "fill_id": fill.id,
            }
        except RuntimeError as exc:
            order.status = "REJECTED"
            order.reason = str(exc)
            return {
                "order_id": order.id,
                "status": "REJECTED",
                "reason": str(exc),
                "fill_id": None,
            }


async def list_orders(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 100,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> list[dict]:
    stmt = select(Order)
    if symbol:
        stmt = stmt.where(Order.symbol == symbol.upper())
    if status:
        stmt = stmt.where(func.upper(Order.status) == status.upper())
    if from_ts:
        stmt = stmt.where(Order.ts >= from_ts)
    if to_ts:
        stmt = stmt.where(Order.ts <= to_ts)

    stmt = stmt.order_by(Order.ts.desc()).limit(limit)
    res = await session.execute(stmt)
    orders = list(res.scalars().all())

    rows: list[dict] = []
    for order in orders:
        fill_id = await _order_fill_id(session, order.id)
        rows.append(
            {
                "id": order.id,
                "ts": order.ts,
                "symbol": order.symbol,
                "side": order.side,
                "type": order.type,
                "qty": float(order.qty),
                "status": _normalize_status(order.status),
                "reason": order.reason,
                "requested_price": order.requested_price,
                "idempotency_key": order.idempotency_key,
                "fill_id": fill_id,
            }
        )

    return rows


async def get_order(session: AsyncSession, order_id: int) -> dict | None:
    stmt = select(Order).where(Order.id == order_id)
    res = await session.execute(stmt)
    order = res.scalar_one_or_none()
    if order is None:
        return None
    return {
        "order_id": order.id,
        "status": _normalize_status(order.status),
        "reason": order.reason,
        "fill_id": await _order_fill_id(session, order.id),
    }


async def cancel_order(session: AsyncSession, order_id: int) -> dict | None:
    async with _transaction_scope(session):
        stmt = select(Order).where(Order.id == order_id)
        res = await session.execute(stmt)
        order = res.scalar_one_or_none()
        if order is None:
            return None
        if _normalize_status(order.status) != "NEW":
            return {
                "order_id": order.id,
                "status": _normalize_status(order.status),
                "reason": "Only NEW orders can be canceled",
                "fill_id": await _order_fill_id(session, order.id),
            }

        order.status = "CANCELED"
        order.reason = "canceled_by_user"
        return {
            "order_id": order.id,
            "status": "CANCELED",
            "reason": order.reason,
            "fill_id": None,
        }

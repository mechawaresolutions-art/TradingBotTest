"""Equity and margin engine for paper broker account simulation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.execution.models import Account, AccountSnapshot, Position
from app.marketdata.models import Candle

PIP_VALUE = 0.0001


@dataclass(frozen=True)
class MarginCheckResult:
    ok: bool
    free_margin: float
    additional_margin_required: float


def derive_bid_ask(candle: Candle, spread_pips: float) -> tuple[float, float]:
    mid = float(candle.close)
    spread_price = spread_pips * PIP_VALUE
    return mid - spread_price / 2.0, mid + spread_price / 2.0


def _position_mark_price(qty_signed: float, bid: float, ask: float) -> float:
    return bid if qty_signed > 0 else ask


def _margin_for_qty(qty: float, price: float, leverage: float) -> float:
    notional = abs(qty) * float(price) * float(Config.CONTRACT_SIZE)
    return notional / float(leverage)


async def _ensure_account(session: AsyncSession, ts) -> Account:
    stmt = select(Account).limit(1)
    res = await session.execute(stmt)
    acct = res.scalar_one_or_none()
    if acct is not None:
        return acct

    acct = Account(
        id=1,
        balance=Config.INITIAL_BALANCE,
        equity=Config.INITIAL_BALANCE,
        margin_used=0.0,
        free_margin=Config.INITIAL_BALANCE,
        currency=Config.ACCOUNT_CURRENCY,
        leverage=Config.ACCOUNT_LEVERAGE,
        updated_at=ts,
    )
    session.add(acct)
    await session.flush()
    return acct


async def compute_unrealized_pnl(session: AsyncSession, symbol: str, candle: Candle) -> float:
    bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)
    stmt = select(Position).where(Position.symbol == symbol)
    res = await session.execute(stmt)
    pos = res.scalar_one_or_none()
    if pos is None:
        return 0.0

    if pos.qty_signed > 0:
        return (bid - pos.avg_price) * pos.qty_signed
    return (pos.avg_price - ask) * abs(pos.qty_signed)


async def compute_margin_used(session: AsyncSession, candle: Candle) -> float:
    bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)
    stmt = select(Position)
    res = await session.execute(stmt)
    positions = list(res.scalars().all())

    margin_used = 0.0
    for pos in positions:
        if pos.qty_signed == 0:
            continue
        mark_price = _position_mark_price(pos.qty_signed, bid, ask)
        margin_used += _margin_for_qty(pos.qty_signed, mark_price, Config.ACCOUNT_LEVERAGE)
    return margin_used


async def compute_account_state(session: AsyncSession, candle: Candle) -> dict:
    """Compute account state for a candle without persisting snapshots."""
    acct = await _ensure_account(session, candle.open_time)
    bid, ask = derive_bid_ask(candle, Config.SPREAD_PIPS)

    stmt_pos = select(Position)
    res_pos = await session.execute(stmt_pos)
    positions = list(res_pos.scalars().all())

    unrealized = 0.0
    margin_used = 0.0
    for pos in positions:
        if pos.qty_signed == 0:
            continue
        if pos.qty_signed > 0:
            unrealized += (bid - pos.avg_price) * pos.qty_signed
        else:
            unrealized += (pos.avg_price - ask) * abs(pos.qty_signed)

        mark_price = _position_mark_price(pos.qty_signed, bid, ask)
        margin_used += _margin_for_qty(pos.qty_signed, mark_price, acct.leverage)

    equity = float(acct.balance) + unrealized
    free_margin = equity - margin_used

    return {
        "account_id": acct.id,
        "ts": candle.open_time,
        "balance": float(acct.balance),
        "equity": equity,
        "margin_used": margin_used,
        "free_margin": free_margin,
        "unrealized_pnl": unrealized,
    }


async def mark_to_market_account(session: AsyncSession, candle: Candle) -> dict:
    """Compute and persist account MTM snapshot deterministically for candle.open_time.

    Idempotent per (account_id, candle.open_time).
    """
    ts = candle.open_time

    stmt_existing_snapshot = select(AccountSnapshot).where(AccountSnapshot.ts == ts).limit(1)
    res_existing = await session.execute(stmt_existing_snapshot)
    existing_snapshot = res_existing.scalar_one_or_none()
    if existing_snapshot is not None:
        return {
            "account_id": existing_snapshot.account_id,
            "ts": existing_snapshot.ts,
            "balance": existing_snapshot.balance,
            "equity": existing_snapshot.equity,
            "margin_used": existing_snapshot.margin_used,
            "free_margin": existing_snapshot.free_margin,
            "unrealized_pnl": existing_snapshot.unrealized_pnl,
            "snapshot_id": existing_snapshot.id,
            "idempotent": True,
        }

    state = await compute_account_state(session, candle)
    acct = await _ensure_account(session, ts)

    acct.equity = state["equity"]
    acct.margin_used = state["margin_used"]
    acct.free_margin = state["free_margin"]
    acct.updated_at = ts

    snapshot = AccountSnapshot(
        account_id=acct.id,
        ts=ts,
        balance=state["balance"],
        equity=state["equity"],
        margin_used=state["margin_used"],
        free_margin=state["free_margin"],
        unrealized_pnl=state["unrealized_pnl"],
    )
    session.add(snapshot)
    await session.flush()

    return {
        "account_id": acct.id,
        "ts": ts,
        "balance": state["balance"],
        "equity": state["equity"],
        "margin_used": state["margin_used"],
        "free_margin": state["free_margin"],
        "unrealized_pnl": state["unrealized_pnl"],
        "snapshot_id": snapshot.id,
        "idempotent": False,
    }


def compute_margin_required_for_order(qty: float, fill_price: float, leverage: float) -> float:
    return _margin_for_qty(qty, fill_price, leverage)


def compute_additional_margin_for_netting(
    current_qty_signed: float,
    order_qty_signed: float,
    fill_price: float,
    leverage: float,
) -> float:
    """Compute incremental margin needed after applying netting effect."""
    after_qty = current_qty_signed + order_qty_signed
    current_margin = _margin_for_qty(current_qty_signed, fill_price, leverage) if current_qty_signed != 0 else 0.0
    after_margin = _margin_for_qty(after_qty, fill_price, leverage) if after_qty != 0 else 0.0
    return max(0.0, after_margin - current_margin)

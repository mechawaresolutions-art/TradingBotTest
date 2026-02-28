"""Macro 7 accounting API."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.models import AccountingPosition, AccountingSnapshot, RealizedTrade
from app.accounting.schemas import AccountStatusOut, PositionOut, RealizedTradeOut, RecomputeIn, RecomputeOut, SnapshotOut
from app.accounting.service import AccountingEngine
from app.config import Config
from app.marketdata.db import get_session
from app.marketdata.models import Candle

router = APIRouter(prefix="/v7/account", tags=["accounting"])


async def _resolve_asof(session: AsyncSession, symbol: str, timeframe: str, asof_open_time: datetime | None) -> datetime:
    if asof_open_time is not None:
        return asof_open_time
    res = await session.execute(
        select(Candle.open_time)
        .where(Candle.symbol == symbol.upper(), Candle.timeframe == timeframe)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    latest = res.scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="No market data available for accounting: deterministic accounting requires candle.open_time",
        )
    return latest


@router.get("/status", response_model=AccountStatusOut)
async def account_status(
    account_id: int = Query(...),
    symbol: str = Query(default=Config.SYMBOL),
    timeframe: str = Query(default=Config.TIMEFRAME),
    asof_open_time: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> AccountStatusOut:
    asof = await _resolve_asof(session, symbol, timeframe, asof_open_time)

    try:
        snap = await AccountingEngine.process_accounting_for_candle(
            session,
            account_id=account_id,
            symbol=symbol,
            timeframe=timeframe,
            asof_open_time=asof,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    pos = (
        await session.execute(
            select(AccountingPosition).where(
                AccountingPosition.account_id == account_id,
                AccountingPosition.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()

    trades = (
        await session.execute(
            select(RealizedTrade)
            .where(RealizedTrade.account_id == account_id, RealizedTrade.symbol == symbol.upper())
            .order_by(RealizedTrade.open_time.desc(), RealizedTrade.id.desc())
            .limit(20)
        )
    ).scalars().all()

    return AccountStatusOut(
        snapshot=SnapshotOut(
            account_id=snap.account_id,
            asof_open_time=snap.asof_open_time,
            balance=float(snap.balance),
            equity=float(snap.equity),
            unrealized_pnl=float(snap.unrealized_pnl),
            margin_used=float(snap.margin_used),
            free_margin=float(snap.free_margin),
        ),
        position=(
            PositionOut(
                account_id=pos.account_id,
                symbol=pos.symbol,
                net_qty=float(pos.net_qty),
                avg_entry_price=float(pos.avg_entry_price),
                updated_open_time=pos.updated_open_time,
            )
            if pos is not None
            else None
        ),
        realized_trades=[
            RealizedTradeOut(
                id=t.id,
                account_id=t.account_id,
                symbol=t.symbol,
                open_time=t.open_time,
                closed_qty=float(t.closed_qty),
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price),
                realized_pnl=float(t.realized_pnl),
                fill_id=t.fill_id,
                order_id=t.order_id,
            )
            for t in trades
        ],
    )


@router.post("/recompute", response_model=RecomputeOut)
async def recompute(payload: RecomputeIn, session: AsyncSession = Depends(get_session)) -> RecomputeOut:
    res = await session.execute(
        select(Candle)
        .where(
            Candle.symbol == payload.symbol.upper(),
            Candle.timeframe == payload.timeframe,
            Candle.open_time >= payload.from_open_time,
            Candle.open_time <= payload.to_open_time,
        )
        .order_by(Candle.open_time.asc())
    )
    candles = list(res.scalars().all())


    last = None
    try:
        for c in candles:
            last = await AccountingEngine.process_accounting_for_candle(
                session,
                account_id=payload.account_id,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                asof_open_time=c.open_time,
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise





    return RecomputeOut(
        processed_candles=len(candles),
        final_snapshot=(
            SnapshotOut(
                account_id=last.account_id,
                asof_open_time=last.asof_open_time,
                balance=float(last.balance),
                equity=float(last.equity),
                unrealized_pnl=float(last.unrealized_pnl),
                margin_used=float(last.margin_used),
                free_margin=float(last.free_margin),
            )
            if last is not None
            else None
        ),
    )

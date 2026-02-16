"""Macro 6 risk endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.marketdata.db import get_session
from app.marketdata.models import Candle
from app.risk.schemas import RiskCheckIn, RiskDecisionOut, RiskSnapshotOut, RiskStatusOut
from app.risk.service import RiskEngine
from sqlalchemy import select

router = APIRouter(prefix="/v6/risk", tags=["risk"])


async def _resolve_asof(
    session: AsyncSession,
    symbol: str,
    asof_open_time: datetime | None,
) -> datetime:
    if asof_open_time is not None:
        return asof_open_time

    stmt = (
        select(Candle.open_time)
        .where(Candle.symbol == symbol.upper(), Candle.timeframe == Config.TIMEFRAME)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    latest = res.scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="No market data available for risk checks: deterministic risk requires candle.open_time",
        )
    return latest


@router.post("/check", response_model=RiskDecisionOut)
async def risk_check(payload: RiskCheckIn, session: AsyncSession = Depends(get_session)) -> RiskDecisionOut:
    asof = await _resolve_asof(session, payload.symbol, payload.asof_open_time)
    async with session.begin():
        decision = await RiskEngine.check_order(
            session,
            account_id=payload.account_id,
            symbol=payload.symbol,
            side=payload.side,
            qty=payload.qty,
            stop_distance_pips=payload.stop_distance_pips,
            asof_open_time=asof,
        )
    return RiskDecisionOut(
        allowed=decision.allowed,
        approved_qty=float(decision.approved_qty),
        reason=decision.reason,
        metrics=RiskSnapshotOut(**decision.metrics),
    )


@router.get("/status", response_model=RiskStatusOut)
async def risk_status(
    account_id: int = Query(default=1),
    symbol: str = Query(default=Config.SYMBOL),
    asof_open_time: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RiskStatusOut:
    asof = await _resolve_asof(session, symbol, asof_open_time)
    async with session.begin():
        limits = await RiskEngine._ensure_limits(session, account_id)
        snapshot = await RiskEngine.compute_snapshot(session, account_id, asof, symbol=symbol)

    return RiskStatusOut(
        account_id=account_id,
        limits={
            "max_open_positions": int(limits.max_open_positions),
            "max_open_positions_per_symbol": int(limits.max_open_positions_per_symbol),
            "max_total_notional": float(limits.max_total_notional),
            "max_symbol_notional": float(limits.max_symbol_notional),
            "risk_per_trade_pct": float(limits.risk_per_trade_pct),
            "daily_loss_limit_pct": float(limits.daily_loss_limit_pct),
            "daily_loss_limit_amount": float(limits.daily_loss_limit_amount),
            "leverage": float(limits.leverage),
        },
        snapshot=RiskSnapshotOut(**snapshot),
    )

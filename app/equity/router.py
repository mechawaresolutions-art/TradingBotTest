"""Account equity/margin API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Account, AccountSnapshot
from app.equity.service import mark_to_market_account
from app.marketdata.db import get_session
from app.marketdata.models import Candle
from app.config import Config

router = APIRouter(prefix="/v3/account", tags=["equity"])


@router.get("")
async def get_account(session: AsyncSession = Depends(get_session)) -> dict:
    stmt = select(Account).limit(1)
    res = await session.execute(stmt)
    acct = res.scalar_one_or_none()
    if acct is None:
        return {
            "balance": float(Config.INITIAL_BALANCE),
            "equity": float(Config.INITIAL_BALANCE),
            "margin_used": 0.0,
            "free_margin": float(Config.INITIAL_BALANCE),
            "currency": Config.ACCOUNT_CURRENCY,
            "leverage": float(Config.ACCOUNT_LEVERAGE),
            "updated_at": None,
        }

    return {
        "balance": float(acct.balance),
        "equity": float(acct.equity),
        "margin_used": float(acct.margin_used),
        "free_margin": float(acct.free_margin),
        "currency": acct.currency,
        "leverage": float(acct.leverage),
        "updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
    }


@router.get("/snapshots")
async def get_account_snapshots(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(AccountSnapshot).order_by(AccountSnapshot.ts.desc()).limit(limit)
    res = await session.execute(stmt)
    snapshots = list(res.scalars().all())

    return {
        "count": len(snapshots),
        "snapshots": [
            {
                "id": s.id,
                "account_id": s.account_id,
                "ts": s.ts.isoformat(),
                "balance": float(s.balance),
                "equity": float(s.equity),
                "margin_used": float(s.margin_used),
                "free_margin": float(s.free_margin),
                "unrealized_pnl": float(s.unrealized_pnl),
            }
            for s in snapshots
        ],
    }


@router.post("/mtm")
async def force_mark_to_market(session: AsyncSession = Depends(get_session)) -> dict:
    stmt = (
        select(Candle)
        .where(Candle.symbol == Config.SYMBOL, Candle.timeframe == Config.TIMEFRAME)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    candle = res.scalar_one_or_none()
    if candle is None:
        raise HTTPException(status_code=404, detail="No candle available for mark-to-market")

    async with session.begin():
        result = await mark_to_market_account(session, candle)
    return result

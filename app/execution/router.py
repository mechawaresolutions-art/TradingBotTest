"""FastAPI routes for execution service (paper broker)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.marketdata import get_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.execution.service import place_market_order, ensure_account, mark_to_market, update_on_candle
from pydantic import BaseModel, Field
from app.execution.models import Position, Order

router = APIRouter(prefix="/v2")


class AccountOut(BaseModel):
    balance: float
    equity: float
    unrealized: float


class OrderIn(BaseModel):
    symbol: str = Field(...)
    side: str = Field(...)
    qty: float = Field(...)
    sl: float | None = None
    tp: float | None = None
    reason: str | None = ""


@router.get("/account", response_model=AccountOut)
async def get_account(session: AsyncSession = Depends(get_session)) -> AccountOut:
    acct = await ensure_account(session)
    # need latest candle for mark_to_market
    from app.marketdata import get_session as _get  # avoid circular
    # Use symbol/timeframe from config via service
    from app.config import Config
    candle_stmt = await mark_to_market(session, Config.SYMBOL, 0.0, 0.0)  # placeholder will be replaced
    # The caller should call /v2/execution/step to update MTM
    return AccountOut(balance=acct.balance, equity=acct.balance, unrealized=0.0)


@router.get("/positions")
async def get_positions(session: AsyncSession = Depends(get_session)):
    stmt = await session.execute("SELECT * FROM positions")
    rows = stmt.fetchall()
    return [dict(row) for row in rows]


@router.post("/orders/market")
async def post_market_order(payload: OrderIn, session: AsyncSession = Depends(get_session)):
    try:
        order, fill = await place_market_order(session, payload.symbol, payload.side, payload.qty, sl=payload.sl, tp=payload.tp, reason=payload.reason or "")
        return {"order_id": order.id, "fill": {"price": fill.price, "qty": fill.qty}}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


class StepIn(BaseModel):
    symbol: str | None = None


@router.post("/execution/step")
async def execution_step(payload: StepIn, session: AsyncSession = Depends(get_session)):
    # pick symbol from payload or config
    from app.config import Config
    symbol = payload.symbol or Config.SYMBOL
    # fetch latest candle
    from app.marketdata.models import Candle
    stmt = await session.execute("SELECT * FROM candles WHERE symbol=:sym AND timeframe=:tf ORDER BY open_time DESC LIMIT 1", {"sym": symbol, "tf": Config.TIMEFRAME})
    row = stmt.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No candle available")
    # map row to an object with attributes used by service
    class C:
        pass
    c = C()
    c.symbol = row["symbol"]
    c.timeframe = row["timeframe"]
    c.open_time = row["open_time"]
    c.open = row["open"]
    c.high = row["high"]
    c.low = row["low"]
    c.close = row["close"]
    executed = await update_on_candle(session, c)
    # compute MTM
    from app.config import Config as cfg
    mid = float(c.close)
    half = (cfg.SPREAD_PIPS * 0.0001) / 2.0
    bid = mid - half
    ask = mid + half
    mtm = await mark_to_market(session, symbol, bid, ask)
    return {"executed": executed, "mtm": mtm}

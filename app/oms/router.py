"""OMS API routes mounted under /paper."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.db import get_session
from app.oms.schemas import OMSOrderOut, OMSOrderRowOut, OMSPlaceOrderIn
from app.oms.service import cancel_order, get_order, list_orders, place_order

router = APIRouter(prefix="/paper", tags=["oms"])


@router.post("/order", response_model=OMSOrderOut)
async def post_order(payload: OMSPlaceOrderIn, session: AsyncSession = Depends(get_session)) -> OMSOrderOut:
    try:
        result = await place_order(session, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return OMSOrderOut(**result)


@router.get("/orders", response_model=list[OMSOrderRowOut])
async def get_orders(
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[OMSOrderRowOut]:
    rows = await list_orders(
        session,
        symbol=symbol,
        status=status,
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return [OMSOrderRowOut(**row) for row in rows]


@router.get("/orders/{order_id}", response_model=OMSOrderOut)
async def get_order_by_id(order_id: int, session: AsyncSession = Depends(get_session)) -> OMSOrderOut:
    row = await get_order(session, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OMSOrderOut(**row)


@router.post("/orders/{order_id}/cancel", response_model=OMSOrderOut)
async def cancel_order_by_id(order_id: int, session: AsyncSession = Depends(get_session)) -> OMSOrderOut:
    row = await cancel_order(session, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OMSOrderOut(**row)

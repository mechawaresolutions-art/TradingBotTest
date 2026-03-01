"""FastAPI routes for MACRO 8 strategy engine."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.db import get_session
from app.strategy_engine.schemas import StrategyCatalogOut, StrategyIntent, StrategyRunRequest
from app.strategy_engine.service import StrategyRunner

router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.get("/strategies", response_model=StrategyCatalogOut)
async def list_strategies() -> StrategyCatalogOut:
    return StrategyCatalogOut(strategies=StrategyRunner.list_strategies())


@router.post("/run", response_model=StrategyIntent)
async def run_strategy(payload: StrategyRunRequest, session: AsyncSession = Depends(get_session)) -> StrategyIntent:
    runner = StrategyRunner(session=session, warmup_limit=200)
    try:
        return await runner.run(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            strategy_name=payload.strategy,
            params=payload.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

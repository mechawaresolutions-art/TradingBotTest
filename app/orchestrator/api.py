"""FastAPI API for Macro 9 orchestrator."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketdata.db import get_session
from app.orchestrator.schemas import OrchestratorRunRequest, OrchestratorRunResult, RunReportModel
from app.orchestrator.service import OrchestratorService

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post("/run", response_model=OrchestratorRunResult)
async def run_orchestration(
    payload: OrchestratorRunRequest,
    session: AsyncSession = Depends(get_session),
) -> OrchestratorRunResult:
    service = OrchestratorService(session)
    return await service.run_cycle(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        candle_ts=payload.candle_ts,
        mode=payload.mode,
    )


@router.get("/runs", response_model=list[RunReportModel])
async def list_runs(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[RunReportModel]:
    service = OrchestratorService(session)
    rows = await service.list_runs(limit=limit)
    return [
        RunReportModel(
            run_id=r.run_id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            candle_ts=r.candle_ts,
            status=r.status,
            intent_json=r.intent_json,
            risk_json=r.risk_json,
            order_json=r.order_json,
            fill_json=r.fill_json,
            positions_json=r.positions_json,
            account_json=r.account_json,
            summary_text=r.summary_text,
            telegram_text=r.telegram_text,
            error_text=r.error_text,
            mode=r.mode,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=RunReportModel)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> RunReportModel:
    service = OrchestratorService(session)
    row = await service.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run report not found")
    return RunReportModel(
        run_id=row.run_id,
        symbol=row.symbol,
        timeframe=row.timeframe,
        candle_ts=row.candle_ts,
        status=row.status,
        intent_json=row.intent_json,
        risk_json=row.risk_json,
        order_json=row.order_json,
        fill_json=row.fill_json,
        positions_json=row.positions_json,
        account_json=row.account_json,
        summary_text=row.summary_text,
        telegram_text=row.telegram_text,
        error_text=row.error_text,
        mode=row.mode,
    )

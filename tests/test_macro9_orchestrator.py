from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.orchestrator.models import RunReport
from app.orchestrator.schemas import OrderPlan
from app.orchestrator.service import OrchestratorService
from app.strategy_engine.schemas import StrategyIndicators, StrategyIntent, StrategyRiskHints


@dataclass
class CandleStub:
    open_time: datetime
    open: float


@dataclass
class SnapStub:
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    asof_open_time: datetime


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(RunReport.__table__.create)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotency_same_candle_no_second_trade(session: AsyncSession, monkeypatch):
    candle_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    service = OrchestratorService(session)

    async def fake_get_exact(symbol: str, timeframe: str, ts: datetime):
        return CandleStub(open_time=ts, open=1.1000)

    async def fake_mtm(_session: AsyncSession, candle: CandleStub):
        return {
            "account_id": 1,
            "ts": candle.open_time.isoformat(),
            "balance": 10000.0,
            "equity": 10000.0,
            "margin_used": 0.0,
            "free_margin": 10000.0,
            "unrealized_pnl": 0.0,
        }

    async def fake_intent(symbol: str, timeframe: str, ts: datetime):
        return StrategyIntent(
            action="BUY",
            reason="cross_up",
            symbol=symbol,
            timeframe=timeframe,
            ts=ts,
            indicators=StrategyIndicators(ema_fast=1.101, ema_slow=1.1, atr=0.001),
            risk_hints=StrategyRiskHints(stop_loss_price=1.0985, take_profit_price=1.102),
            summary="buy signal",
        )

    async def fake_plan(**kwargs):
        return (
            OrderPlan(
                symbol="EURUSD",
                side="BUY",
                qty=1.0,
                stop_loss=1.0985,
                take_profit=1.1020,
                reason="macro9_cross_up",
            ),
            {"allowed": True, "approved_qty": 1.0},
        )

    calls = {"place_order": 0}

    async def fake_place_order(_session: AsyncSession, payload):
        calls["place_order"] += 1
        return {
            "order_id": 101,
            "status": "FILLED",
            "reason": None,
            "fill_id": 201,
        }

    async def fake_get_fill(_fill_id: int):
        return {"id": 201, "price": 1.1002, "qty": 1.0, "side": "BUY"}

    async def fake_get_order(_order_id: int):
        return {"id": 101, "status": "FILLED", "side": "BUY", "qty": 1.0}

    async def fake_process_accounting(*args, **kwargs):
        return SnapStub(
            balance=10000.0,
            equity=10000.0,
            margin_used=0.0,
            free_margin=10000.0,
            asof_open_time=candle_ts,
        )

    async def fake_positions(symbol: str):
        return {"position": {"symbol": symbol, "qty_signed": 1.0, "avg_price": 1.1002}}

    monkeypatch.setattr(service, "_get_exact_candle", fake_get_exact)
    monkeypatch.setattr("app.orchestrator.service.mark_to_market_account", fake_mtm)
    monkeypatch.setattr(service, "_compute_intent_for_candle", fake_intent)
    monkeypatch.setattr(service, "_build_order_plan", fake_plan)
    monkeypatch.setattr("app.orchestrator.service.place_order", fake_place_order)
    monkeypatch.setattr(service, "_get_fill", fake_get_fill)
    monkeypatch.setattr(service, "_get_order", fake_get_order)
    monkeypatch.setattr("app.orchestrator.service.AccountingEngine.process_accounting_for_candle", fake_process_accounting)
    monkeypatch.setattr(service, "_positions_snapshot", fake_positions)

    first = await service.run_cycle(symbol="EURUSD", timeframe="M5", candle_ts=candle_ts, mode="execute")
    second = await service.run_cycle(symbol="EURUSD", timeframe="M5", candle_ts=candle_ts, mode="execute")

    assert first.status == "OK"
    assert second.status == "OK"
    assert calls["place_order"] == 1

    rows = (await session.execute(select(RunReport))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_hold_intent_persists_noop(session: AsyncSession, monkeypatch):
    candle_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    service = OrchestratorService(session)

    async def fake_get_exact(symbol: str, timeframe: str, ts: datetime):
        return CandleStub(open_time=ts, open=1.1000)

    async def fake_mtm(_session: AsyncSession, candle: CandleStub):
        return {"equity": 10000.0, "ts": candle.open_time.isoformat()}

    async def fake_intent(symbol: str, timeframe: str, ts: datetime):
        return StrategyIntent(
            action="HOLD",
            reason="no_cross",
            symbol=symbol,
            timeframe=timeframe,
            ts=ts,
            indicators=StrategyIndicators(ema_fast=1.1, ema_slow=1.1, atr=0.001),
            risk_hints=StrategyRiskHints(stop_loss_price=None, take_profit_price=None),
            summary="hold signal",
        )

    monkeypatch.setattr(service, "_get_exact_candle", fake_get_exact)
    monkeypatch.setattr("app.orchestrator.service.mark_to_market_account", fake_mtm)
    monkeypatch.setattr(service, "_compute_intent_for_candle", fake_intent)

    result = await service.run_cycle(symbol="EURUSD", timeframe="M5", candle_ts=candle_ts, mode="execute")

    assert result.status == "NOOP"
    row = (await session.execute(select(RunReport))).scalar_one()
    assert row.status == "NOOP"
    assert "hold" in row.summary_text.lower()


@pytest.mark.asyncio
async def test_error_persists_run_report_with_error_text(session: AsyncSession, monkeypatch):
    candle_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    service = OrchestratorService(session)

    async def fake_get_exact(symbol: str, timeframe: str, ts: datetime):
        return CandleStub(open_time=ts, open=1.1000)

    async def fake_mtm(_session: AsyncSession, candle: CandleStub):
        raise RuntimeError("forced_failure")

    monkeypatch.setattr(service, "_get_exact_candle", fake_get_exact)
    monkeypatch.setattr("app.orchestrator.service.mark_to_market_account", fake_mtm)

    result = await service.run_cycle(symbol="EURUSD", timeframe="M5", candle_ts=candle_ts, mode="execute")

    assert result.status == "ERROR"
    row = (await session.execute(select(RunReport))).scalar_one()
    assert row.status == "ERROR"
    assert row.error_text is not None
    assert "forced_failure" in row.error_text

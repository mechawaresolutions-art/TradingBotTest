"""Macro 9 orchestration service."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.service import AccountingEngine
from app.equity.service import mark_to_market_account
from app.execution.models import Fill, Order, Position
from app.marketdata.models import Candle
from app.oms.schemas import OMSPlaceOrderIn
from app.oms.service import place_order
from app.orchestrator.models import RunReport
from app.orchestrator.schemas import OrderPlan, OrchestratorRunResult, RunMode, RunStatus
from app.risk.service import RiskEngine
from app.strategy_engine.service import StrategyRunner
from app.strategy_engine.schemas import StrategyIntent


PIP_SIZE = 0.0001


@asynccontextmanager
async def _transaction_scope(session: AsyncSession):
    if session.in_transaction():
        yield
    else:
        async with session.begin():
            yield


class OrchestratorService:
    """Runs deterministic end-to-end trading orchestration for one candle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run_cycle(
        self,
        *,
        symbol: str,
        timeframe: str,
        candle_ts: datetime,
        mode: RunMode,
    ) -> OrchestratorRunResult:
        symbol_norm = symbol.upper()
        timeframe_norm = timeframe.upper()
        run_id = self._deterministic_run_id(symbol_norm, timeframe_norm, candle_ts)

        # A) Validate candle exists
        candle = await self._get_exact_candle(symbol_norm, timeframe_norm, candle_ts)
        if candle is None:
            report = await self._upsert_report(
                run_id=run_id,
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                candle_ts=candle_ts,
                status="NOOP",
                summary_text=f"{symbol_norm} {timeframe_norm} {candle_ts.isoformat()} => NOOP (missing_candle)",
                telegram_text=self._format_telegram(
                    run_id=run_id,
                    status="NOOP",
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    summary="missing_candle",
                ),
                error_text="missing_candle",
                mode=mode,
            )
            return self._to_result(report)

        # B) Idempotency check
        existing = await self._find_existing_terminal(symbol_norm, timeframe_norm, candle_ts)
        if existing is not None:
            return self._to_result(existing)

        try:
            # C) Mark-to-market / account update
            account_mtm = await mark_to_market_account(self.session, candle)

            # D) Compute StrategyIntent deterministically at candle_ts
            intent = await self._compute_intent_for_candle(symbol_norm, timeframe_norm, candle_ts)
            intent_json = intent.model_dump(mode="json")

            # E) HOLD => NOOP
            if intent.action == "HOLD":
                report = await self._upsert_report(
                    run_id=run_id,
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    status="NOOP",
                    intent_json=intent_json,
                    account_json=account_mtm,
                    summary_text=intent.summary,
                    telegram_text=self._format_telegram(
                        run_id=run_id,
                        status="NOOP",
                        symbol=symbol_norm,
                        timeframe=timeframe_norm,
                        candle_ts=candle_ts,
                        summary=intent.summary,
                    ),
                    mode=mode,
                )
                return self._to_result(report)

            # F) Risk + OrderPlan
            order_plan, risk_json = await self._build_order_plan(
                symbol=symbol_norm,
                candle=candle,
                intent=intent,
            )

            if order_plan is None:
                summary = f"{intent.summary} => NOOP (risk_rejected)"
                report = await self._upsert_report(
                    run_id=run_id,
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    status="NOOP",
                    intent_json=intent_json,
                    risk_json=risk_json,
                    account_json=account_mtm,
                    summary_text=summary,
                    telegram_text=self._format_telegram(
                        run_id=run_id,
                        status="NOOP",
                        symbol=symbol_norm,
                        timeframe=timeframe_norm,
                        candle_ts=candle_ts,
                        summary=summary,
                    ),
                    mode=mode,
                )
                return self._to_result(report)

            if mode == "dry_run":
                summary = f"{intent.summary} => NOOP (dry_run)"
                report = await self._upsert_report(
                    run_id=run_id,
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    status="NOOP",
                    intent_json=intent_json,
                    risk_json=risk_json,
                    account_json=account_mtm,
                    summary_text=summary,
                    telegram_text=self._format_telegram(
                        run_id=run_id,
                        status="NOOP",
                        symbol=symbol_norm,
                        timeframe=timeframe_norm,
                        candle_ts=candle_ts,
                        summary=summary,
                    ),
                    mode=mode,
                )
                return self._to_result(report)

            # G) Create market order via OMS
            oms_out = await place_order(
                self.session,
                OMSPlaceOrderIn(
                    symbol=symbol_norm,
                    side=order_plan.side,
                    qty=order_plan.qty,
                    type="market",
                    stop_loss=order_plan.stop_loss,
                    take_profit=order_plan.take_profit,
                    idempotency_key=self._order_idempotency_key(symbol_norm, timeframe_norm, candle_ts, order_plan.side),
                ),
            )

            if oms_out["status"] != "FILLED":
                summary = f"{intent.summary} => NOOP (order_{oms_out['status'].lower()})"
                report = await self._upsert_report(
                    run_id=run_id,
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    status="NOOP",
                    intent_json=intent_json,
                    risk_json=risk_json,
                    order_json=oms_out,
                    account_json=account_mtm,
                    summary_text=summary,
                    telegram_text=self._format_telegram(
                        run_id=run_id,
                        status="NOOP",
                        symbol=symbol_norm,
                        timeframe=timeframe_norm,
                        candle_ts=candle_ts,
                        summary=summary,
                    ),
                    mode=mode,
                )
                return self._to_result(report)

            # H/I) Fill + positions/pnl/account update
            fill_row = await self._get_fill(oms_out.get("fill_id"))
            order_row = await self._get_order(oms_out.get("order_id"))

            acct_snap = await AccountingEngine.process_accounting_for_candle(
                self.session,
                account_id=1,
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                asof_open_time=candle_ts,
            )

            positions_json = await self._positions_snapshot(symbol_norm)
            account_json = {
                "balance": float(acct_snap.balance),
                "equity": float(acct_snap.equity),
                "margin_used": float(acct_snap.margin_used),
                "free_margin": float(acct_snap.free_margin),
                "asof_open_time": acct_snap.asof_open_time.isoformat(),
            }

            summary = self._format_summary(symbol_norm, timeframe_norm, intent_json, order_plan, order_row, fill_row)
            telegram_text = self._format_telegram(
                run_id=run_id,
                status="OK",
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                candle_ts=candle_ts,
                summary=summary,
            )

            report = await self._upsert_report(
                run_id=run_id,
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                candle_ts=candle_ts,
                status="OK",
                intent_json=intent_json,
                risk_json=risk_json,
                order_json=order_row,
                fill_json=fill_row,
                positions_json=positions_json,
                account_json=account_json,
                summary_text=summary,
                telegram_text=telegram_text,
                mode=mode,
            )
            return self._to_result(report)

        except Exception as exc:
            report = await self._upsert_report(
                run_id=run_id,
                symbol=symbol_norm,
                timeframe=timeframe_norm,
                candle_ts=candle_ts,
                status="ERROR",
                summary_text=f"{symbol_norm} {timeframe_norm} {candle_ts.isoformat()} => ERROR",
                telegram_text=self._format_telegram(
                    run_id=run_id,
                    status="ERROR",
                    symbol=symbol_norm,
                    timeframe=timeframe_norm,
                    candle_ts=candle_ts,
                    summary=str(exc),
                ),
                error_text=str(exc),
                mode=mode,
            )
            return self._to_result(report)

    async def list_runs(self, *, limit: int = 100) -> list[RunReport]:
        res = await self.session.execute(select(RunReport).order_by(RunReport.candle_ts.desc()).limit(limit))
        return list(res.scalars().all())

    async def get_run(self, run_id: str) -> RunReport | None:
        res = await self.session.execute(select(RunReport).where(RunReport.run_id == run_id))
        return res.scalar_one_or_none()

    async def _compute_intent_for_candle(self, symbol: str, timeframe: str, candle_ts: datetime) -> StrategyIntent:
        strategy = StrategyRunner.create_strategy("ema_atr", None)
        candles = await self._fetch_candles_upto(symbol, timeframe, candle_ts, limit=200)
        return strategy.compute_intent(candles)

    async def _build_order_plan(
        self,
        *,
        symbol: str,
        candle: Candle,
        intent: StrategyIntent,
    ) -> tuple[OrderPlan | None, dict[str, Any]]:
        side = intent.action
        if side not in ("BUY", "SELL"):
            raise RuntimeError(f"Unsupported trade action for order plan: {side}")

        stop_loss = intent.risk_hints.stop_loss_price
        take_profit = intent.risk_hints.take_profit_price

        stop_distance_pips = None
        if stop_loss is not None:
            stop_distance_pips = abs(float(candle.open) - float(stop_loss)) / PIP_SIZE

        risk_decision = await RiskEngine.check_order(
            self.session,
            account_id=1,
            symbol=symbol,
            side=side,
            qty=1.0,
            stop_distance_pips=stop_distance_pips,
            asof_open_time=candle.open_time,
        )

        risk_json = {
            "allowed": bool(risk_decision.allowed),
            "approved_qty": float(risk_decision.approved_qty),
            "reason": risk_decision.reason,
            "metrics": risk_decision.metrics,
        }

        if not risk_decision.allowed or float(risk_decision.approved_qty) <= 0:
            return None, risk_json

        order_plan = OrderPlan(
            symbol=symbol,
            side=side,
            qty=float(risk_decision.approved_qty),
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=f"macro9_{intent.reason}",
        )
        risk_json["order_plan"] = order_plan.model_dump(mode="json")
        return order_plan, risk_json

    async def _find_existing_terminal(self, symbol: str, timeframe: str, candle_ts: datetime) -> RunReport | None:
        res = await self.session.execute(
            select(RunReport).where(
                RunReport.symbol == symbol,
                RunReport.timeframe == timeframe,
                RunReport.candle_ts == candle_ts,
                RunReport.status.in_(["OK", "NOOP"]),
            )
        )
        return res.scalar_one_or_none()

    async def _get_exact_candle(self, symbol: str, timeframe: str, candle_ts: datetime) -> Candle | None:
        res = await self.session.execute(
            select(Candle).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time == candle_ts,
            )
        )
        return res.scalar_one_or_none()

    async def _fetch_candles_upto(self, symbol: str, timeframe: str, candle_ts: datetime, *, limit: int) -> list[Candle]:
        res = await self.session.execute(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time <= candle_ts,
            )
            .order_by(Candle.open_time.desc())
            .limit(limit)
        )
        out = list(res.scalars().all())
        out.reverse()
        return out

    async def _positions_snapshot(self, symbol: str) -> dict[str, Any]:
        res = await self.session.execute(select(Position).where(Position.symbol == symbol))
        pos = res.scalar_one_or_none()
        if pos is None:
            return {"position": None}
        return {
            "position": {
                "symbol": pos.symbol,
                "qty_signed": float(pos.qty_signed),
                "avg_price": float(pos.avg_price),
                "stop_loss": float(pos.stop_loss) if pos.stop_loss is not None else None,
                "take_profit": float(pos.take_profit) if pos.take_profit is not None else None,
            }
        }

    async def _get_fill(self, fill_id: int | None) -> dict[str, Any] | None:
        if fill_id is None:
            return None
        res = await self.session.execute(select(Fill).where(Fill.id == fill_id))
        fill = res.scalar_one_or_none()
        if fill is None:
            return None
        return {
            "id": fill.id,
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "qty": float(fill.qty),
            "price": float(fill.price),
            "ts": fill.ts.isoformat(),
        }

    async def _get_order(self, order_id: int | None) -> dict[str, Any] | None:
        if order_id is None:
            return None
        res = await self.session.execute(select(Order).where(Order.id == order_id))
        order = res.scalar_one_or_none()
        if order is None:
            return None
        return {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": float(order.qty),
            "status": order.status,
            "reason": order.reason,
            "ts": order.ts.isoformat(),
        }

    async def _upsert_report(
        self,
        *,
        run_id: str,
        symbol: str,
        timeframe: str,
        candle_ts: datetime,
        status: RunStatus,
        intent_json: dict[str, Any] | None = None,
        risk_json: dict[str, Any] | None = None,
        order_json: dict[str, Any] | None = None,
        fill_json: dict[str, Any] | None = None,
        positions_json: dict[str, Any] | None = None,
        account_json: dict[str, Any] | None = None,
        summary_text: str,
        telegram_text: str,
        error_text: str | None = None,
        mode: RunMode,
    ) -> RunReport:
        async with _transaction_scope(self.session):
            res = await self.session.execute(
                select(RunReport).where(
                    RunReport.symbol == symbol,
                    RunReport.timeframe == timeframe,
                    RunReport.candle_ts == candle_ts,
                )
            )
            row = res.scalar_one_or_none()
            if row is None:
                row = RunReport(
                    run_id=run_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_ts=candle_ts,
                    status=status,
                    intent_json=intent_json,
                    risk_json=risk_json,
                    order_json=order_json,
                    fill_json=fill_json,
                    positions_json=positions_json,
                    account_json=account_json,
                    summary_text=summary_text,
                    telegram_text=telegram_text,
                    error_text=error_text,
                    mode=mode,
                )
                self.session.add(row)
            else:
                row.run_id = run_id
                row.status = status
                row.intent_json = intent_json
                row.risk_json = risk_json
                row.order_json = order_json
                row.fill_json = fill_json
                row.positions_json = positions_json
                row.account_json = account_json
                row.summary_text = summary_text
                row.telegram_text = telegram_text
                row.error_text = error_text
                row.mode = mode

            await self.session.flush()
            return row

    @staticmethod
    def _to_result(row: RunReport) -> OrchestratorRunResult:
        return OrchestratorRunResult(
            run_id=row.run_id,
            status=row.status,
            candle_ts=row.candle_ts,
            summary=row.summary_text,
            telegram_text=row.telegram_text,
            details={
                "intent": row.intent_json,
                "risk": row.risk_json,
                "order": row.order_json,
                "fill": row.fill_json,
                "positions": row.positions_json,
                "account": row.account_json,
                "error": row.error_text,
                "mode": row.mode,
            },
        )

    @staticmethod
    def _deterministic_run_id(symbol: str, timeframe: str, candle_ts: datetime) -> str:
        seed = f"macro9:{symbol}:{timeframe}:{candle_ts.isoformat()}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

    @staticmethod
    def _order_idempotency_key(symbol: str, timeframe: str, candle_ts: datetime, side: str) -> str:
        return f"macro9:{symbol}:{timeframe}:{candle_ts.isoformat()}:{side}"

    @staticmethod
    def _format_summary(
        symbol: str,
        timeframe: str,
        intent_json: dict[str, Any],
        order_plan: OrderPlan,
        order_row: dict[str, Any] | None,
        fill_row: dict[str, Any] | None,
    ) -> str:
        indicators = intent_json.get("indicators") or {}
        ema_fast = indicators.get("ema_fast")
        ema_slow = indicators.get("ema_slow")
        atr = indicators.get("atr")
        fill_price = fill_row.get("price") if fill_row else None
        return (
            f"{symbol} {timeframe} ema_fast={ema_fast} ema_slow={ema_slow} atr={atr} "
            f"=> {intent_json.get('action')} ({intent_json.get('reason')}), "
            f"qty={order_plan.qty}, fill={fill_price}, order_status={(order_row or {}).get('status')}"
        )

    @staticmethod
    def _format_telegram(
        *,
        run_id: str,
        status: str,
        symbol: str,
        timeframe: str,
        candle_ts: datetime,
        summary: str,
    ) -> str:
        return "\n".join(
            [
                f"run_id: {run_id}",
                f"status: {status}",
                f"symbol: {symbol}",
                f"timeframe: {timeframe}",
                f"candle_ts: {candle_ts.isoformat()}",
                f"summary: {summary}",
            ]
        )

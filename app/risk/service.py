"""Deterministic Macro 6 risk and portfolio checks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.equity.service import compute_account_state
from app.execution.models import Account, Position
from app.marketdata.models import Candle
from app.risk.models import DailyEquity, RiskLimits


PIP_VALUE_PER_UNIT = 0.0001


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    approved_qty: float
    reason: str | None
    metrics: dict


class RiskEngine:
    @staticmethod
    async def _ensure_limits(session: AsyncSession, account_id: int) -> RiskLimits:
        stmt = select(RiskLimits).where(RiskLimits.account_id == account_id)
        res = await session.execute(stmt)
        limits = res.scalar_one_or_none()
        if limits is not None:
            return limits

        limits = RiskLimits(
            account_id=account_id,
            max_open_positions=Config.RISK_MAX_OPEN_POSITIONS,
            max_open_positions_per_symbol=Config.RISK_MAX_OPEN_POSITIONS_PER_SYMBOL,
            max_total_notional=Config.RISK_MAX_TOTAL_NOTIONAL,
            max_symbol_notional=Config.RISK_MAX_SYMBOL_NOTIONAL,
            risk_per_trade_pct=Config.RISK_PER_TRADE_PCT,
            daily_loss_limit_pct=Config.RISK_DAILY_LOSS_LIMIT_PCT,
            daily_loss_limit_amount=Config.RISK_DAILY_LOSS_LIMIT_AMOUNT,
            leverage=Config.ACCOUNT_LEVERAGE,
        )
        session.add(limits)
        await session.flush()
        return limits

    @staticmethod
    async def _get_account(session: AsyncSession, account_id: int, asof_open_time: datetime) -> Account:
        stmt = select(Account).where(Account.id == account_id)
        res = await session.execute(stmt)
        account = res.scalar_one_or_none()
        if account is not None:
            return account

        account = Account(
            id=account_id,
            balance=Config.INITIAL_BALANCE,
            equity=Config.INITIAL_BALANCE,
            margin_used=0.0,
            free_margin=Config.INITIAL_BALANCE,
            currency=Config.ACCOUNT_CURRENCY,
            leverage=Config.ACCOUNT_LEVERAGE,
            updated_at=asof_open_time,
        )
        session.add(account)
        await session.flush()
        return account

    @staticmethod
    async def _latest_candle_at_or_before(
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        asof_open_time: datetime,
    ) -> Candle | None:
        stmt = (
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time <= asof_open_time,
            )
            .order_by(Candle.open_time.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def _get_reference_candle(
        session: AsyncSession,
        symbol: str,
        asof_open_time: datetime,
    ) -> Candle:
        candle = await RiskEngine._latest_candle_at_or_before(session, symbol, Config.TIMEFRAME, asof_open_time)
        if candle is None:
            raise RuntimeError(
                "No market data available for risk checks: deterministic risk requires candle.open_time"
            )
        return candle

    @staticmethod
    async def _ensure_daily_equity(
        session: AsyncSession,
        account_id: int,
        day,
        equity: float,
    ) -> DailyEquity:
        stmt = select(DailyEquity).where(DailyEquity.account_id == account_id, DailyEquity.day == day)
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()
        if row is None:
            row = DailyEquity(
                account_id=account_id,
                day=day,
                day_start_equity=float(equity),
                min_equity=float(equity),
            )
            session.add(row)
            await session.flush()
            return row

        if float(equity) < float(row.min_equity):
            row.min_equity = float(equity)
        return row

    @staticmethod
    async def compute_snapshot(
        session: AsyncSession,
        account_id: int,
        asof_open_time: datetime,
        symbol: str | None = None,
    ) -> dict:
        symbol = (symbol or Config.SYMBOL).upper()

        await RiskEngine._get_account(session, account_id, asof_open_time)
        limits = await RiskEngine._ensure_limits(session, account_id)
        ref_candle = await RiskEngine._get_reference_candle(session, symbol, asof_open_time)

        acct_state = await compute_account_state(session, ref_candle)

        stmt_pos = select(Position)
        res_pos = await session.execute(stmt_pos)
        positions = [p for p in res_pos.scalars().all() if p.qty_signed != 0]

        total_notional = 0.0
        symbol_notional = 0.0
        open_positions_per_symbol = 0

        for pos in positions:
            pos_candle = await RiskEngine._latest_candle_at_or_before(
                session,
                pos.symbol,
                Config.TIMEFRAME,
                asof_open_time,
            )
            if pos_candle is None:
                continue
            mid = float(pos_candle.open)
            pos_notional = abs(float(pos.qty_signed)) * mid
            total_notional += pos_notional
            if pos.symbol.upper() == symbol:
                open_positions_per_symbol += 1
                symbol_notional += pos_notional

        day = ref_candle.open_time.date()
        daily = await RiskEngine._ensure_daily_equity(
            session,
            account_id=account_id,
            day=day,
            equity=float(acct_state["equity"]),
        )

        daily_loss_breached = False
        if float(limits.daily_loss_limit_pct) > 0:
            pct_threshold = float(daily.day_start_equity) * (1 - float(limits.daily_loss_limit_pct))
            if float(acct_state["equity"]) <= pct_threshold:
                daily_loss_breached = True

        if float(limits.daily_loss_limit_amount) > 0:
            amt_threshold = float(daily.day_start_equity) - float(limits.daily_loss_limit_amount)
            if float(acct_state["equity"]) <= amt_threshold:
                daily_loss_breached = True

        return {
            "account_id": account_id,
            "asof_open_time": ref_candle.open_time,
            "day": day,
            "balance": float(acct_state["balance"]),
            "equity": float(acct_state["equity"]),
            "margin_used": float(acct_state["margin_used"]),
            "free_margin": float(acct_state["free_margin"]),
            "open_positions_count": len(positions),
            "open_positions_per_symbol": open_positions_per_symbol,
            "notional_per_symbol": float(symbol_notional),
            "total_notional": float(total_notional),
            "day_start_equity": float(daily.day_start_equity),
            "min_equity": float(daily.min_equity),
            "daily_loss_breached": daily_loss_breached,
        }

    @staticmethod
    def _floor_to_step(value: float, step: float) -> float:
        units = math.floor(value / step)
        return round(units * step, 10)

    @staticmethod
    async def check_order(
        session: AsyncSession,
        *,
        account_id: int,
        symbol: str,
        side: str,
        qty: float,
        stop_distance_pips: float | None,
        asof_open_time: datetime,
    ) -> RiskDecision:
        symbol = symbol.upper()
        side = side.upper()

        if side not in ("BUY", "SELL"):
            return RiskDecision(False, 0.0, f"Unsupported side: {side}", metrics={})
        if qty <= 0:
            return RiskDecision(False, 0.0, "qty must be > 0", metrics={})

        limits = await RiskEngine._ensure_limits(session, account_id)
        snapshot = await RiskEngine.compute_snapshot(session, account_id, asof_open_time, symbol=symbol)

        if snapshot["daily_loss_breached"]:
            return RiskDecision(False, 0.0, "Daily loss limit breached", metrics=snapshot)

        if snapshot["open_positions_count"] >= int(limits.max_open_positions):
            return RiskDecision(False, 0.0, "Max open positions limit reached", metrics=snapshot)

        if snapshot["open_positions_per_symbol"] >= int(limits.max_open_positions_per_symbol):
            return RiskDecision(False, 0.0, "Max open positions per symbol limit reached", metrics=snapshot)

        candle = await RiskEngine._get_reference_candle(session, symbol, asof_open_time)
        mid_price = float(candle.open)

        approved_qty = float(qty)
        if stop_distance_pips is not None and stop_distance_pips > 0 and float(limits.risk_per_trade_pct) > 0:
            risk_amount = float(snapshot["equity"]) * float(limits.risk_per_trade_pct)
            max_units = risk_amount / (PIP_VALUE_PER_UNIT * float(stop_distance_pips))
            approved_qty = min(approved_qty, RiskEngine._floor_to_step(max_units, Config.RISK_LOT_STEP))
            if approved_qty <= 0:
                return RiskDecision(False, 0.0, "Risk-per-trade sizing reduced qty to zero", metrics=snapshot)

        new_notional = abs(float(approved_qty)) * mid_price
        if snapshot["notional_per_symbol"] + new_notional > float(limits.max_symbol_notional):
            return RiskDecision(False, 0.0, "Max symbol notional limit exceeded", metrics=snapshot)

        if snapshot["total_notional"] + new_notional > float(limits.max_total_notional):
            return RiskDecision(False, 0.0, "Max total notional limit exceeded", metrics=snapshot)

        leverage = float(limits.leverage)
        required_margin = new_notional / leverage
        if float(snapshot["free_margin"]) < required_margin:
            return RiskDecision(False, 0.0, "Insufficient free margin", metrics=snapshot)

        return RiskDecision(True, approved_qty, None, metrics=snapshot)

"""Deterministic Macro 7 accounting engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.models import AccountingPosition, AccountingSnapshot, RealizedTrade
from app.config import Config
from app.execution.models import Account, Fill, Order
from app.marketdata.models import Candle


@dataclass(frozen=True)
class ApplyResult:
    applied_fills: int
    realized_pnl: float


class AccountingEngine:
    @staticmethod
    async def _ensure_account(session: AsyncSession, account_id: int, asof_open_time: datetime) -> Account:
        res = await session.execute(select(Account).where(Account.id == account_id))
        acct = res.scalar_one_or_none()
        if acct is not None:
            return acct

        acct = Account(
            id=account_id,
            balance=Config.INITIAL_BALANCE,
            equity=Config.INITIAL_BALANCE,
            margin_used=0.0,
            free_margin=Config.INITIAL_BALANCE,
            currency=Config.ACCOUNT_CURRENCY,
            leverage=Config.ACCOUNT_LEVERAGE,
            updated_at=asof_open_time,
        )
        session.add(acct)
        await session.flush()
        return acct

    @staticmethod
    async def _get_position(session: AsyncSession, account_id: int, symbol: str) -> AccountingPosition | None:
        res = await session.execute(
            select(AccountingPosition).where(
                AccountingPosition.account_id == account_id,
                AccountingPosition.symbol == symbol,
            )
        )
        return res.scalar_one_or_none()

    @staticmethod
    async def _get_candle(session: AsyncSession, symbol: str, timeframe: str, asof_open_time: datetime) -> Candle:
        res = await session.execute(
            select(Candle).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time == asof_open_time,
            )
        )
        candle = res.scalar_one_or_none()
        if candle is None:
            raise RuntimeError(
                "No market data available for accounting: deterministic accounting requires candle.open_time"
            )
        return candle

    @staticmethod
    async def _latest_candle_at_or_before(
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        asof_open_time: datetime,
    ) -> Candle:
        res = await session.execute(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time <= asof_open_time,
            )
            .order_by(Candle.open_time.desc())
            .limit(1)
        )
        candle = res.scalar_one_or_none()
        if candle is None:
            raise RuntimeError(
                "No market data available for accounting: deterministic accounting requires candle.open_time"
            )
        return candle

    @staticmethod
    async def apply_new_fills(
        session: AsyncSession,
        *,
        account_id: int,
        symbol: str,
        timeframe: str,
        asof_open_time: datetime,
    ) -> ApplyResult:
        symbol = symbol.upper()
        await AccountingEngine._ensure_account(session, account_id, asof_open_time)

        res_fills = await session.execute(
            select(Fill)
            .where(
                Fill.symbol == symbol,
                Fill.ts <= asof_open_time,
                Fill.accounted_at_open_time.is_(None),
            )
            .order_by(Fill.ts.asc(), Fill.id.asc())
        )
        fills = list(res_fills.scalars().all())

        if not fills:
            return ApplyResult(applied_fills=0, realized_pnl=0.0)

        acct = (await session.execute(select(Account).where(Account.id == account_id))).scalar_one()
        pos = await AccountingEngine._get_position(session, account_id, symbol)

        if pos is None:
            pos = AccountingPosition(
                account_id=account_id,
                symbol=symbol,
                net_qty=0.0,
                avg_entry_price=0.0,
                updated_open_time=asof_open_time,
            )
            session.add(pos)
            await session.flush()

        realized_total = 0.0

        for fill in fills:
            fill_qty_signed = float(fill.qty) if fill.side.upper() == "BUY" else -float(fill.qty)
            existing = float(pos.net_qty)

            if existing == 0 or (existing > 0 and fill_qty_signed > 0) or (existing < 0 and fill_qty_signed < 0):
                new_qty = existing + fill_qty_signed
                if existing == 0:
                    new_avg = float(fill.price)
                else:
                    new_avg = (abs(existing) * float(pos.avg_entry_price) + abs(fill_qty_signed) * float(fill.price)) / abs(
                        new_qty
                    )
                pos.net_qty = new_qty
                pos.avg_entry_price = new_avg
                pos.updated_open_time = fill.ts
            else:
                close_qty = min(abs(existing), abs(fill_qty_signed))
                if existing > 0:
                    realized = (float(fill.price) - float(pos.avg_entry_price)) * close_qty
                else:
                    realized = (float(pos.avg_entry_price) - float(fill.price)) * close_qty

                realized_total += realized
                acct.balance = float(acct.balance) + realized

                res_order = await session.execute(select(Order.id).where(Order.id == fill.order_id))
                order_id = res_order.scalar_one_or_none()
                session.add(
                    RealizedTrade(
                        account_id=account_id,
                        symbol=symbol,
                        open_time=fill.ts,
                        closed_qty=close_qty,
                        entry_price=float(pos.avg_entry_price),
                        exit_price=float(fill.price),
                        realized_pnl=realized,
                        fill_id=fill.id,
                        order_id=order_id,
                    )
                )

                new_qty = existing + fill_qty_signed
                if new_qty == 0:
                    pos.net_qty = 0.0
                    pos.avg_entry_price = 0.0
                    pos.updated_open_time = fill.ts
                elif (existing > 0 > new_qty) or (existing < 0 < new_qty):
                    pos.net_qty = new_qty
                    pos.avg_entry_price = float(fill.price)
                    pos.updated_open_time = fill.ts
                else:
                    pos.net_qty = new_qty
                    pos.updated_open_time = fill.ts

            fill.accounted_at_open_time = asof_open_time

        acct.updated_at = asof_open_time
        await session.flush()
        return ApplyResult(applied_fills=len(fills), realized_pnl=realized_total)

    @staticmethod
    async def mark_to_market(
        session: AsyncSession,
        *,
        account_id: int,
        symbol: str,
        timeframe: str,
        asof_open_time: datetime,
    ) -> AccountingSnapshot:
        symbol = symbol.upper()
        acct = await AccountingEngine._ensure_account(session, account_id, asof_open_time)

        res_positions = await session.execute(select(AccountingPosition).where(AccountingPosition.account_id == account_id))
        positions = [p for p in res_positions.scalars().all() if float(p.net_qty) != 0]

        unrealized = 0.0
        margin_used = 0.0

        for p in positions:
            c = await AccountingEngine._latest_candle_at_or_before(session, p.symbol, timeframe, asof_open_time)
            mid = float(c.open)
            qty = float(p.net_qty)
            if qty > 0:
                unrealized += (mid - float(p.avg_entry_price)) * qty
            else:
                unrealized += (float(p.avg_entry_price) - mid) * abs(qty)
            margin_used += abs(qty) * mid / float(acct.leverage)

        equity = float(acct.balance) + unrealized
        free_margin = equity - margin_used

        acct.equity = equity
        acct.margin_used = margin_used
        acct.free_margin = free_margin
        acct.updated_at = asof_open_time

        res_snap = await session.execute(
            select(AccountingSnapshot).where(
                AccountingSnapshot.account_id == account_id,
                AccountingSnapshot.asof_open_time == asof_open_time,
            )
        )
        snap = res_snap.scalar_one_or_none()
        if snap is None:
            snap = AccountingSnapshot(
                account_id=account_id,
                asof_open_time=asof_open_time,
                balance=float(acct.balance),
                equity=equity,
                unrealized_pnl=unrealized,
                margin_used=margin_used,
                free_margin=free_margin,
            )
            session.add(snap)
        else:
            snap.balance = float(acct.balance)
            snap.equity = equity
            snap.unrealized_pnl = unrealized
            snap.margin_used = margin_used
            snap.free_margin = free_margin

        await session.flush()
        return snap

    @staticmethod
    async def process_accounting_for_candle(
        session: AsyncSession,
        *,
        account_id: int,
        symbol: str,
        timeframe: str,
        asof_open_time: datetime,
    ) -> AccountingSnapshot:
        await AccountingEngine._get_candle(session, symbol.upper(), timeframe, asof_open_time)
        await AccountingEngine.apply_new_fills(
            session,
            account_id=account_id,
            symbol=symbol,
            timeframe=timeframe,
            asof_open_time=asof_open_time,
        )
        return await AccountingEngine.mark_to_market(
            session,
            account_id=account_id,
            symbol=symbol,
            timeframe=timeframe,
            asof_open_time=asof_open_time,
        )

"""Trading bot controller with DB-backed strategy loop."""
import asyncio
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import select

from app.config import Config
from app.execution.models import Position, Order
from app.execution.service import place_market_order
from app.marketdata.db import AsyncSessionLocal
from app.marketdata.models import Candle
from app.notifier import Notifier
from app.strategy_v1 import StrategySignal, generate_signal

logger = logging.getLogger(__name__)


class BotState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


def _timeframe_to_minutes(timeframe: str) -> int:
    tf = timeframe.upper()
    if tf.startswith("M"):
        return int(tf[1:])
    raise ValueError(f"Unsupported timeframe: {timeframe}")


class TradingBot:
    """Main trading bot controller running in background thread."""

    def __init__(self, webhook_url: str, initial_balance: float = 10000.0) -> None:
        self.notifier = Notifier(webhook_url)

        self.state = BotState.STOPPED
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self._lock = threading.Lock()

        self.stats = {
            "iterations": 0,
            "last_heartbeat": None,
            "started_at": None,
            "balance": initial_balance,
            "equity": initial_balance,
            "positions_count": 0,
        }

        self._last_signal: Optional[dict] = None
        self._last_candle_time: Optional[datetime] = None
        self._cooldown_active: bool = False
        self._cooldown_until: Optional[datetime] = None

        logger.info("TradingBot initialized")

    def start(self) -> bool:
        with self._lock:
            if self.running:
                logger.warning("Bot already running")
                return False
            try:
                self.running = True
                self.state = BotState.RUNNING
                self.stats["started_at"] = datetime.now(timezone.utc)
                self.stats["iterations"] = 0

                self.thread = threading.Thread(target=self._trading_loop, daemon=False)
                self.thread.start()

                self.notifier.send_started()
                logger.info("Trading bot started")
                return True
            except Exception as e:
                logger.error(f"Error starting bot: {e}", exc_info=True)
                self.state = BotState.ERROR
                self.running = False
                return False

    def stop(self) -> bool:
        with self._lock:
            if not self.running:
                logger.warning("Bot not running")
                return False
            self.running = False

        try:
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5)
            self.state = BotState.STOPPED
            self.notifier.send_stopped()
            logger.info("Trading bot stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping bot: {e}", exc_info=True)
            self.state = BotState.ERROR
            return False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self.state.value,
                "running": self.running,
                "balance": round(float(self.stats["balance"]), 5),
                "equity": round(float(self.stats["equity"]), 5),
                "positions_count": int(self.stats["positions_count"]),
                "iterations": int(self.stats["iterations"]),
                "started_at": self.stats["started_at"].isoformat() if self.stats["started_at"] else None,
            }

    def get_strategy_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "last_candle_time": self._last_candle_time.isoformat() if self._last_candle_time else None,
                "last_signal": self._last_signal,
                "cooldown_active": self._cooldown_active,
                "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
                "open_position": self._current_position_snapshot(),
            }

    def _current_position_snapshot(self) -> dict | None:
        pos = self.stats.get("open_position")
        return pos if isinstance(pos, dict) else None

    async def _fetch_recent_candles(self, session, limit: int) -> list[Candle]:
        stmt = (
            select(Candle)
            .where(Candle.symbol == Config.SYMBOL, Candle.timeframe == Config.TIMEFRAME)
            .order_by(Candle.open_time.asc())
        )
        res = await session.execute(stmt)
        candles = list(res.scalars().all())
        if len(candles) > limit:
            candles = candles[-limit:]
        return candles

    async def _fetch_position(self, session) -> Optional[Position]:
        stmt = select(Position).where(Position.symbol == Config.SYMBOL)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def _get_last_strategy_entry_ts(self, session) -> Optional[datetime]:
        stmt = (
            select(Order.ts)
            .where(Order.symbol == Config.SYMBOL, Order.reason == "strategy_v1_entry")
            .order_by(Order.ts.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def run_strategy_iteration(self, session) -> Dict[str, Any]:
        """Execute one deterministic strategy iteration on latest closed candle."""
        window = max(Config.STRAT_SMA_SLOW + 2, Config.STRAT_ATR_PERIOD + 2)
        candles = await self._fetch_recent_candles(session, window)
        if not candles:
            return {"action": "no_candles"}

        latest_candle = candles[-1]
        self._last_candle_time = latest_candle.open_time

        signal = generate_signal(
            candles,
            symbol=Config.SYMBOL,
            timeframe=Config.TIMEFRAME,
            qty=Config.STRAT_QTY,
            sma_fast=Config.STRAT_SMA_FAST,
            sma_slow=Config.STRAT_SMA_SLOW,
            atr_period=Config.STRAT_ATR_PERIOD,
            atr_sl_mult=Config.STRAT_ATR_SL_MULT,
            atr_tp_mult=Config.STRAT_ATR_TP_MULT,
        )

        if signal is None:
            self._last_signal = None
            return {"action": "no_signal", "last_candle_time": latest_candle.open_time.isoformat()}

        last_entry_ts = await self._get_last_strategy_entry_ts(session)
        cooldown_minutes = _timeframe_to_minutes(Config.TIMEFRAME) * Config.STRAT_COOLDOWN_CANDLES
        cooldown_until = None
        cooldown_active = False
        if last_entry_ts is not None:
            cooldown_until = last_entry_ts + timedelta(minutes=cooldown_minutes)
            cooldown_active = latest_candle.open_time < cooldown_until

        self._cooldown_active = cooldown_active
        self._cooldown_until = cooldown_until

        sig_payload = {
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "side": signal.side,
            "qty": signal.qty,
            "sl": signal.sl,
            "tp": signal.tp,
            "idempotency_key": signal.idempotency_key,
            "candle_open_time": signal.candle_open_time.isoformat(),
        }
        self._last_signal = sig_payload

        if cooldown_active:
            return {"action": "cooldown", "signal": sig_payload}

        pos = await self._fetch_position(session)
        if pos is not None:
            if (pos.qty_signed > 0 and signal.side == "BUY") or (pos.qty_signed < 0 and signal.side == "SELL"):
                return {"action": "same_direction_skip", "signal": sig_payload}

        order, fill = await place_market_order(
            session,
            signal.symbol,
            signal.side,
            signal.qty,
            sl=signal.sl,
            tp=signal.tp,
            reason="strategy_v1_entry",
            idempotency_key=signal.idempotency_key,
        )

        self.notifier.send_event(
            "strategy_order",
            {
                "symbol": signal.symbol,
                "side": signal.side,
                "qty": signal.qty,
                "price": fill.price,
                "order_id": order.id,
                "idempotency_key": signal.idempotency_key,
                "candle_open_time": signal.candle_open_time.isoformat(),
            },
        )

        return {
            "action": "ordered",
            "signal": sig_payload,
            "order_id": order.id,
            "fill_price": float(fill.price),
        }

    async def _refresh_stats_from_db(self, session) -> None:
        stmt_pos = select(Position).where(Position.symbol == Config.SYMBOL)
        res_pos = await session.execute(stmt_pos)
        pos = res_pos.scalar_one_or_none()

        open_pos = None
        if pos is not None:
            open_pos = {
                "symbol": pos.symbol,
                "qty_signed": pos.qty_signed,
                "avg_price": pos.avg_price,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
            }

        # Balance/equity are maintained by execution service; we keep them from last known account snapshot.
        # Account table has singleton row; avoid importing service helper to keep loop simple.
        from app.execution.models import Account

        stmt_acct = select(Account).limit(1)
        res_acct = await session.execute(stmt_acct)
        acct = res_acct.scalar_one_or_none()
        balance = float(acct.balance) if acct is not None else float(Config.INITIAL_BALANCE)

        with self._lock:
            self.stats["balance"] = balance
            self.stats["equity"] = balance
            self.stats["positions_count"] = 1 if pos is not None else 0
            self.stats["open_position"] = open_pos

    def _trading_loop(self) -> None:
        try:
            asyncio.run(self._async_trading_loop())
        except Exception as e:
            logger.error(f"Unexpected error in trading loop: {e}", exc_info=True)
            self.state = BotState.ERROR
            self.running = False

    async def _async_trading_loop(self) -> None:
        if AsyncSessionLocal is None:
            raise RuntimeError("AsyncSessionLocal unavailable; DB not initialized")

        heartbeat_deadline = asyncio.get_event_loop().time()
        while self.running:
            try:
                async with AsyncSessionLocal() as session:
                    await self.run_strategy_iteration(session)
                    await self._refresh_stats_from_db(session)

                with self._lock:
                    self.stats["iterations"] += 1

                now = asyncio.get_event_loop().time()
                if now >= heartbeat_deadline:
                    heartbeat_deadline = now + float(Config.HEARTBEAT_INTERVAL)
                    self.notifier.send_heartbeat(self.get_status())
                    with self._lock:
                        self.stats["last_heartbeat"] = datetime.now(timezone.utc)

                await asyncio.sleep(float(Config.BOT_LOOP_INTERVAL_SEC))
            except Exception as e:
                logger.error(f"Error in trading loop iteration: {e}", exc_info=True)
                self.state = BotState.ERROR
                self.running = False
                self.notifier.send_event("error", {"message": f"Trading loop error: {str(e)[:200]}"})

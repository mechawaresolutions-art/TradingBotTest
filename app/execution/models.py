"""SQLAlchemy models for execution/paper broker."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, PrimaryKeyConstraint
)
from sqlalchemy.orm import relationship
from app.marketdata.models import Base
from sqlalchemy.sql import func


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    balance = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="USD")
    leverage = Column(Float, nullable=False, default=1.0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), nullable=False, default=func.now())
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)  # 'BUY' or 'SELL'
    type = Column(String(20), nullable=False, default="market")
    qty = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="filled")
    reason = Column(String(255), nullable=True)
    requested_price = Column(Float, nullable=True)


class Fill(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False, default=func.now())
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False, default=0.0)
    slippage = Column(Float, nullable=False, default=0.0)


class Position(Base):
    __tablename__ = "positions"

    # Only one symbol supported (symbol as PK)
    symbol = Column(String(20), primary_key=True)
    qty_signed = Column(Float, nullable=False)  # positive for long, negative for short
    avg_price = Column(Float, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    entry_order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_ts = Column(DateTime(timezone=True), nullable=False)
    exit_ts = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String(20), nullable=False)
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    exit_reason = Column(String(50), nullable=True)
    entry_order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    exit_order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)


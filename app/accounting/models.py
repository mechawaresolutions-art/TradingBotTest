"""Macro 7 accounting persistence models."""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, Index

from app.marketdata.models import Base


class AccountingPosition(Base):
    __tablename__ = "accounting_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_accounting_position_account_symbol"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String(20), nullable=False)
    net_qty = Column(Float, nullable=False, default=0.0)
    avg_entry_price = Column(Float, nullable=False, default=0.0)
    updated_open_time = Column(DateTime(timezone=True), nullable=False)


class AccountingSnapshot(Base):
    __tablename__ = "accounting_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "asof_open_time", name="uq_accounting_snapshot_account_asof"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    asof_open_time = Column(DateTime(timezone=True), nullable=False)
    balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, nullable=False)
    margin_used = Column(Float, nullable=False)
    free_margin = Column(Float, nullable=False)


class RealizedTrade(Base):
    __tablename__ = "realized_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String(20), nullable=False)
    open_time = Column(DateTime(timezone=True), nullable=False)
    closed_qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    fill_id = Column(Integer, ForeignKey("fills.id", ondelete="SET NULL"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)


Index("ix_accounting_snapshot_asof", AccountingSnapshot.asof_open_time)
Index("ix_realized_trades_account_time", RealizedTrade.account_id, RealizedTrade.open_time)

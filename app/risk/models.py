"""Risk engine persistence models."""
from sqlalchemy import Column, Integer, Float, Date, ForeignKey, UniqueConstraint

from app.marketdata.models import Base


class RiskLimits(Base):
    __tablename__ = "risk_limits"

    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    max_open_positions = Column(Integer, nullable=False)
    max_open_positions_per_symbol = Column(Integer, nullable=False)
    max_total_notional = Column(Float, nullable=False)
    max_symbol_notional = Column(Float, nullable=False)
    risk_per_trade_pct = Column(Float, nullable=False)
    daily_loss_limit_pct = Column(Float, nullable=False)
    daily_loss_limit_amount = Column(Float, nullable=False)
    leverage = Column(Float, nullable=False)


class DailyEquity(Base):
    __tablename__ = "daily_equity"
    __table_args__ = (
        UniqueConstraint("account_id", "day", name="uq_daily_equity_account_day"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    day = Column(Date, nullable=False)
    day_start_equity = Column(Float, nullable=False)
    min_equity = Column(Float, nullable=False)

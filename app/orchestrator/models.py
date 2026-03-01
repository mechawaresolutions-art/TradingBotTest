"""Macro 9 orchestration persistence models."""
from sqlalchemy import Column, DateTime, Index, JSON, String, Text, UniqueConstraint

from app.marketdata.models import Base


class RunReport(Base):
    __tablename__ = "run_reports"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "candle_ts", name="uq_run_reports_symbol_tf_ts"),
    )

    run_id = Column(String(36), primary_key=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    candle_ts = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(10), nullable=False)

    intent_json = Column(JSON, nullable=True)
    risk_json = Column(JSON, nullable=True)
    order_json = Column(JSON, nullable=True)
    fill_json = Column(JSON, nullable=True)
    positions_json = Column(JSON, nullable=True)
    account_json = Column(JSON, nullable=True)

    summary_text = Column(Text, nullable=False, default="")
    telegram_text = Column(Text, nullable=False, default="")
    error_text = Column(Text, nullable=True)
    mode = Column(String(20), nullable=False, default="execute")


Index("ix_run_reports_candle_ts", RunReport.candle_ts)
Index("ix_run_reports_status", RunReport.status)

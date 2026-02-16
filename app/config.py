"""Configuration management for the trading bot."""
import os
from dotenv import load_dotenv


load_dotenv()


class Config:
    """Load and validate environment configuration."""

    # Required
    N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")
    
    # Optional with defaults
    HEARTBEAT_INTERVAL: int = 60
    INITIAL_BALANCE: float = 10000.0
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    BOT_NAME: str = os.getenv("BOT_NAME", "ForexBot")
    
    # Database configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tradingbot:tradingbot_pass@localhost:5432/tradingbot"
    )
    
    # Market data configuration
    SYMBOL: str = os.getenv("SYMBOL", "EURUSD")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "M5")
    INGEST_OVERLAP_CANDLES: int = 10
    INITIAL_BACKFILL_DAYS: int = 7
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "mock")
    CANDLE_RETENTION_DAYS: int = 180
    # Execution parameters
    SPREAD_PIPS: float = float(os.getenv("SPREAD_PIPS", "1.0"))
    EXECUTION_SLIPPAGE_PIPS: float = float(os.getenv("EXECUTION_SLIPPAGE_PIPS", "0.0"))
    ACCOUNT_CURRENCY: str = os.getenv("ACCOUNT_CURRENCY", "USD")
    ACCOUNT_LEVERAGE: float = float(os.getenv("ACCOUNT_LEVERAGE", "30"))
    CONTRACT_SIZE: float = float(os.getenv("CONTRACT_SIZE", "100000"))
    MARGIN_MODE: str = os.getenv("MARGIN_MODE", "simple")
    OMS_MIN_QTY: float = float(os.getenv("OMS_MIN_QTY", "0.01"))
    OMS_ALLOWED_SYMBOLS: list[str] = [
        s.strip().upper()
        for s in os.getenv("OMS_ALLOWED_SYMBOLS", "EURUSD").split(",")
        if s.strip()
    ]
    RISK_MAX_OPEN_POSITIONS: int = int(os.getenv("RISK_MAX_OPEN_POSITIONS", "5"))
    RISK_MAX_OPEN_POSITIONS_PER_SYMBOL: int = int(os.getenv("RISK_MAX_OPEN_POSITIONS_PER_SYMBOL", "1"))
    RISK_MAX_TOTAL_NOTIONAL: float = float(os.getenv("RISK_MAX_TOTAL_NOTIONAL", "1000000"))
    RISK_MAX_SYMBOL_NOTIONAL: float = float(os.getenv("RISK_MAX_SYMBOL_NOTIONAL", "500000"))
    RISK_PER_TRADE_PCT: float = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
    RISK_DAILY_LOSS_LIMIT_PCT: float = float(os.getenv("RISK_DAILY_LOSS_LIMIT_PCT", "0.05"))
    RISK_DAILY_LOSS_LIMIT_AMOUNT: float = float(os.getenv("RISK_DAILY_LOSS_LIMIT_AMOUNT", "0"))
    RISK_LOT_STEP: float = float(os.getenv("RISK_LOT_STEP", "0.01"))
    # Bot loop
    BOT_LOOP_INTERVAL_SEC: float = float(os.getenv("BOT_LOOP_INTERVAL_SEC", "1.0"))
    # Strategy v1 parameters
    STRAT_QTY: float = float(os.getenv("STRAT_QTY", "1.0"))
    STRAT_SMA_FAST: int = int(os.getenv("STRAT_SMA_FAST", "20"))
    STRAT_SMA_SLOW: int = int(os.getenv("STRAT_SMA_SLOW", "50"))
    STRAT_ATR_PERIOD: int = int(os.getenv("STRAT_ATR_PERIOD", "14"))
    STRAT_ATR_SL_MULT: float = float(os.getenv("STRAT_ATR_SL_MULT", "2.0"))
    STRAT_ATR_TP_MULT: float = float(os.getenv("STRAT_ATR_TP_MULT", "3.0"))
    STRAT_COOLDOWN_CANDLES: int = int(os.getenv("STRAT_COOLDOWN_CANDLES", "1"))
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.N8N_WEBHOOK_URL:
            raise ValueError("N8N_WEBHOOK_URL environment variable is required")
        
        # Parse and validate heartbeat interval
        try:
            heartbeat = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
            if heartbeat <= 0:
                raise ValueError("HEARTBEAT_INTERVAL must be a positive integer")
            cls.HEARTBEAT_INTERVAL = heartbeat
        except ValueError as e:
            raise ValueError(f"Invalid HEARTBEAT_INTERVAL: {e}")
        
        # Parse and validate initial balance
        try:
            balance = float(os.getenv("INITIAL_BALANCE", "10000.0"))
            if balance <= 0:
                raise ValueError("INITIAL_BALANCE must be a positive number")
            cls.INITIAL_BALANCE = balance
        except ValueError as e:
            raise ValueError(f"Invalid INITIAL_BALANCE: {e}")
        
        # Parse and validate market data config
        try:
            overlap = int(os.getenv("INGEST_OVERLAP_CANDLES", "10"))
            if overlap < 0:
                raise ValueError("INGEST_OVERLAP_CANDLES must be non-negative")
            cls.INGEST_OVERLAP_CANDLES = overlap
        except ValueError as e:
            raise ValueError(f"Invalid INGEST_OVERLAP_CANDLES: {e}")
        
        try:
            backfill = int(os.getenv("INITIAL_BACKFILL_DAYS", "7"))
            if backfill < 1:
                raise ValueError("INITIAL_BACKFILL_DAYS must be at least 1")
            cls.INITIAL_BACKFILL_DAYS = backfill
        except ValueError as e:
            raise ValueError(f"Invalid INITIAL_BACKFILL_DAYS: {e}")
        
        # Validate provider
        if cls.MARKET_DATA_PROVIDER not in ("mock", "real"):
            raise ValueError(f"Invalid MARKET_DATA_PROVIDER: {cls.MARKET_DATA_PROVIDER}")
        # Parse spread
        try:
            spread = float(os.getenv("SPREAD_PIPS", "1.0"))
            if spread < 0:
                raise ValueError("SPREAD_PIPS must be non-negative")
            cls.SPREAD_PIPS = spread
        except ValueError as e:
            raise ValueError(f"Invalid SPREAD_PIPS: {e}")
        try:
            slippage = float(os.getenv("EXECUTION_SLIPPAGE_PIPS", "0.0"))
            if slippage < 0:
                raise ValueError("EXECUTION_SLIPPAGE_PIPS must be non-negative")
            cls.EXECUTION_SLIPPAGE_PIPS = slippage
        except ValueError as e:
            raise ValueError(f"Invalid EXECUTION_SLIPPAGE_PIPS: {e}")

        try:
            loop_interval = float(os.getenv("BOT_LOOP_INTERVAL_SEC", "1.0"))
            if loop_interval <= 0:
                raise ValueError("BOT_LOOP_INTERVAL_SEC must be positive")
            cls.BOT_LOOP_INTERVAL_SEC = loop_interval
        except ValueError as e:
            raise ValueError(f"Invalid BOT_LOOP_INTERVAL_SEC: {e}")

        try:
            qty = float(os.getenv("STRAT_QTY", "1.0"))
            if qty <= 0:
                raise ValueError("STRAT_QTY must be positive")
            cls.STRAT_QTY = qty
        except ValueError as e:
            raise ValueError(f"Invalid STRAT_QTY: {e}")

        try:
            sma_fast = int(os.getenv("STRAT_SMA_FAST", "20"))
            sma_slow = int(os.getenv("STRAT_SMA_SLOW", "50"))
            if sma_fast <= 0 or sma_slow <= 0:
                raise ValueError("STRAT_SMA_FAST/STRAT_SMA_SLOW must be positive")
            if sma_fast >= sma_slow:
                raise ValueError("STRAT_SMA_FAST must be less than STRAT_SMA_SLOW")
            cls.STRAT_SMA_FAST = sma_fast
            cls.STRAT_SMA_SLOW = sma_slow
        except ValueError as e:
            raise ValueError(f"Invalid SMA config: {e}")

        try:
            atr_period = int(os.getenv("STRAT_ATR_PERIOD", "14"))
            if atr_period <= 0:
                raise ValueError("STRAT_ATR_PERIOD must be positive")
            cls.STRAT_ATR_PERIOD = atr_period
        except ValueError as e:
            raise ValueError(f"Invalid STRAT_ATR_PERIOD: {e}")

        try:
            sl_mult = float(os.getenv("STRAT_ATR_SL_MULT", "2.0"))
            tp_mult = float(os.getenv("STRAT_ATR_TP_MULT", "3.0"))
            if sl_mult <= 0 or tp_mult <= 0:
                raise ValueError("STRAT_ATR_SL_MULT/STRAT_ATR_TP_MULT must be positive")
            cls.STRAT_ATR_SL_MULT = sl_mult
            cls.STRAT_ATR_TP_MULT = tp_mult
        except ValueError as e:
            raise ValueError(f"Invalid ATR multiplier config: {e}")

        try:
            cooldown = int(os.getenv("STRAT_COOLDOWN_CANDLES", "1"))
            if cooldown < 0:
                raise ValueError("STRAT_COOLDOWN_CANDLES must be >= 0")
            cls.STRAT_COOLDOWN_CANDLES = cooldown
        except ValueError as e:
            raise ValueError(f"Invalid STRAT_COOLDOWN_CANDLES: {e}")
        
        # Validate database URL
        if not cls.DATABASE_URL.startswith(("postgresql", "sqlite")):
            raise ValueError("DATABASE_URL must be postgresql or sqlite")

        if not cls.ACCOUNT_CURRENCY:
            raise ValueError("ACCOUNT_CURRENCY must be set")

        try:
            leverage = float(os.getenv("ACCOUNT_LEVERAGE", str(cls.ACCOUNT_LEVERAGE)))
            if leverage <= 0:
                raise ValueError("ACCOUNT_LEVERAGE must be > 0")
            cls.ACCOUNT_LEVERAGE = leverage
        except ValueError as e:
            raise ValueError(f"Invalid ACCOUNT_LEVERAGE: {e}")

        try:
            contract_size = float(os.getenv("CONTRACT_SIZE", str(cls.CONTRACT_SIZE)))
            if contract_size <= 0:
                raise ValueError("CONTRACT_SIZE must be > 0")
            cls.CONTRACT_SIZE = contract_size
        except ValueError as e:
            raise ValueError(f"Invalid CONTRACT_SIZE: {e}")

        if cls.MARGIN_MODE != "simple":
            raise ValueError("MARGIN_MODE must be 'simple'")

        try:
            oms_min_qty = float(os.getenv("OMS_MIN_QTY", str(cls.OMS_MIN_QTY)))
            if oms_min_qty <= 0:
                raise ValueError("OMS_MIN_QTY must be > 0")
            cls.OMS_MIN_QTY = oms_min_qty
        except ValueError as e:
            raise ValueError(f"Invalid OMS_MIN_QTY: {e}")

        allowed_symbols_raw = os.getenv("OMS_ALLOWED_SYMBOLS", ",".join(cls.OMS_ALLOWED_SYMBOLS))
        parsed_symbols = [s.strip().upper() for s in allowed_symbols_raw.split(",") if s.strip()]
        if not parsed_symbols:
            raise ValueError("OMS_ALLOWED_SYMBOLS must contain at least one symbol")
        cls.OMS_ALLOWED_SYMBOLS = parsed_symbols

        try:
            max_open_positions = int(os.getenv("RISK_MAX_OPEN_POSITIONS", str(cls.RISK_MAX_OPEN_POSITIONS)))
            max_open_per_symbol = int(
                os.getenv("RISK_MAX_OPEN_POSITIONS_PER_SYMBOL", str(cls.RISK_MAX_OPEN_POSITIONS_PER_SYMBOL))
            )
            if max_open_positions < 1 or max_open_per_symbol < 1:
                raise ValueError("RISK_MAX_OPEN_POSITIONS and RISK_MAX_OPEN_POSITIONS_PER_SYMBOL must be >= 1")
            cls.RISK_MAX_OPEN_POSITIONS = max_open_positions
            cls.RISK_MAX_OPEN_POSITIONS_PER_SYMBOL = max_open_per_symbol
        except ValueError as e:
            raise ValueError(f"Invalid open position risk limits: {e}")

        try:
            max_total_notional = float(os.getenv("RISK_MAX_TOTAL_NOTIONAL", str(cls.RISK_MAX_TOTAL_NOTIONAL)))
            max_symbol_notional = float(os.getenv("RISK_MAX_SYMBOL_NOTIONAL", str(cls.RISK_MAX_SYMBOL_NOTIONAL)))
            if max_total_notional <= 0 or max_symbol_notional <= 0:
                raise ValueError("RISK_MAX_TOTAL_NOTIONAL and RISK_MAX_SYMBOL_NOTIONAL must be > 0")
            cls.RISK_MAX_TOTAL_NOTIONAL = max_total_notional
            cls.RISK_MAX_SYMBOL_NOTIONAL = max_symbol_notional
        except ValueError as e:
            raise ValueError(f"Invalid notional risk limits: {e}")

        try:
            risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", str(cls.RISK_PER_TRADE_PCT)))
            daily_loss_pct = float(os.getenv("RISK_DAILY_LOSS_LIMIT_PCT", str(cls.RISK_DAILY_LOSS_LIMIT_PCT)))
            daily_loss_amount = float(
                os.getenv("RISK_DAILY_LOSS_LIMIT_AMOUNT", str(cls.RISK_DAILY_LOSS_LIMIT_AMOUNT))
            )
            if risk_per_trade_pct < 0 or risk_per_trade_pct > 1:
                raise ValueError("RISK_PER_TRADE_PCT must be between 0 and 1")
            if daily_loss_pct < 0 or daily_loss_pct > 1:
                raise ValueError("RISK_DAILY_LOSS_LIMIT_PCT must be between 0 and 1")
            if daily_loss_amount < 0:
                raise ValueError("RISK_DAILY_LOSS_LIMIT_AMOUNT must be >= 0")
            cls.RISK_PER_TRADE_PCT = risk_per_trade_pct
            cls.RISK_DAILY_LOSS_LIMIT_PCT = daily_loss_pct
            cls.RISK_DAILY_LOSS_LIMIT_AMOUNT = daily_loss_amount
        except ValueError as e:
            raise ValueError(f"Invalid pct/amount risk limits: {e}")

        try:
            lot_step = float(os.getenv("RISK_LOT_STEP", str(cls.RISK_LOT_STEP)))
            if lot_step <= 0:
                raise ValueError("RISK_LOT_STEP must be > 0")
            cls.RISK_LOT_STEP = lot_step
        except ValueError as e:
            raise ValueError(f"Invalid RISK_LOT_STEP: {e}")

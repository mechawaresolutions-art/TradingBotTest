"""FastAPI application entrypoint."""
import logging
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from app.config import Config
from app.bot import TradingBot
from app.marketdata import get_session, init_db, close_db, router as marketdata_router
from app import execution as execution_pkg
from app.equity import router as equity_router
from app.oms import router as oms_router
from app.risk import router as risk_router

# Configure logging
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Validate config on startup
try:
    Config.validate()
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    sys.exit(1)

# Initialize FastAPI and bot
app = FastAPI(title="Forex Trading Bot", version="2.0.0")
bot = TradingBot(webhook_url=Config.N8N_WEBHOOK_URL, initial_balance=Config.INITIAL_BALANCE)


class MessageResponse(BaseModel):
    """Standard response model."""
    message: str


class StatusResponse(BaseModel):
    """Status response model."""
    state: str
    running: bool
    balance: float
    equity: float
    positions_count: int
    iterations: int
    started_at: str | None


class StrategyStatusResponse(BaseModel):
    last_candle_time: str | None
    last_signal: Dict[str, Any] | None
    cooldown_active: bool
    cooldown_until: str | None
    open_position: Dict[str, Any] | None


# Include market data router
app.include_router(marketdata_router)
# Include execution router
try:
    from app.execution import router as execution_router
    app.include_router(execution_router)
except Exception:
    logger.debug("Execution router not available at import time")
app.include_router(equity_router)
app.include_router(oms_router)
app.include_router(risk_router)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database on startup."""
    logger.info("Initializing market data pipeline...")
    try:
        # Import execution models to ensure they are registered on Base.metadata
        try:
            import app.execution.models  # noqa: F401
        except Exception:
            logger.debug("No execution models to import yet")
        try:
            import app.risk.models  # noqa: F401
        except Exception:
            logger.debug("No risk models to import yet")
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Cleanup on shutdown."""
    logger.info("Shutting down...")
    
    if bot.running:
        logger.info("Stopping bot...")
        bot.stop()
    
    logger.info("Closing database connections...")
    try:
        await close_db()
    except Exception as e:
        logger.warning(f"Error closing database: {e}")


@app.post("/start", response_model=MessageResponse)
async def start_bot() -> MessageResponse:
    """Start the trading bot."""
    if bot.start():
        return MessageResponse(message="Trading bot started successfully")
    else:
        raise HTTPException(status_code=400, detail="Failed to start bot")


@app.post("/stop", response_model=MessageResponse)
async def stop_bot() -> MessageResponse:
    """Stop the trading bot."""
    if bot.stop():
        return MessageResponse(message="Trading bot stopped successfully")
    else:
        raise HTTPException(status_code=400, detail="Failed to stop bot")


@app.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get bot status and metrics."""
    status = bot.get_status()
    return StatusResponse(**status)


@app.get("/v3/strategy/status", response_model=StrategyStatusResponse)
async def get_strategy_status() -> StrategyStatusResponse:
    """Get latest strategy loop state."""
    return StrategyStatusResponse(**bot.get_strategy_status())


@app.get("/health")
async def health_check() -> MessageResponse:
    """Health check endpoint."""
    return MessageResponse(message="OK")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting {Config.BOT_NAME} v2.0.0 on 0.0.0.0:8000")
    logger.info(f"Market Data Provider: {Config.MARKET_DATA_PROVIDER}")
    logger.info(f"N8N webhook: {Config.N8N_WEBHOOK_URL}")
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )

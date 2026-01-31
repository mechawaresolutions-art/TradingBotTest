"""FastAPI application entrypoint."""
import logging
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from app.config import Config
from app.bot import TradingBot

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
app = FastAPI(title="Forex Trading Bot", version="1.0.0")
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


@app.get("/health")
async def health_check() -> MessageResponse:
    """Health check endpoint."""
    return MessageResponse(message="OK")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Cleanup on shutdown."""
    if bot.running:
        logger.info("Shutting down - stopping bot...")
        bot.stop()


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting {Config.BOT_NAME} on 0.0.0.0:8000")
    logger.info(f"N8N webhook: {Config.N8N_WEBHOOK_URL}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )

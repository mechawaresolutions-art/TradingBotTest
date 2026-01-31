<<<<<<< HEAD
# TradingBotTest
=======
# Forex Trading Bot

A minimal, production-oriented forex trading bot skeleton with FastAPI control interface and n8n webhook integration.

## Features

- **FastAPI Control**: Start/stop/status endpoints for bot management
- **Background Trading Loop**: Runs trading logic in dedicated thread
- **n8n Integration**: Send events via HTTP webhooks (started, stopped, heartbeat, errors)
- **Paper Broker**: Placeholder for position management and P&L tracking
- **Risk Management**: Extensible risk management system
- **Strategy Stub**: Ready for your trading logic implementation
- **Type Hints**: Production-ready code with type annotations
- **Error Handling**: Robust error handling that never crashes the bot

## Project Structure

```
forex_bot/
├── app/
│   ├── main.py           # FastAPI entrypoint
│   ├── bot.py            # Trading loop controller
│   ├── strategy.py       # Trading strategy (stub)
│   ├── broker.py         # Paper broker implementation
│   ├── risk.py           # Risk management module
│   ├── notifier.py       # n8n webhook sender
│   └── config.py         # Configuration management
├── requirements.txt
└── README.md
```

## Installation

### Prerequisites
- Python 3.10+
- pip

### Setup

1. Clone the repository and navigate to the project:
```bash
cd forex_bot
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create `.env` file:
```env
N8N_WEBHOOK_URL=http://your-n8n-instance/webhook/your-webhook-id
HEARTBEAT_INTERVAL=60
LOG_LEVEL=INFO
BOT_NAME=ForexBot
INITIAL_BALANCE=10000.0
```

## Running the Bot

### Production (VPS)

Use a process manager like `supervisor` or `systemd`:

```bash
# systemd service file example (/etc/systemd/system/forex-bot.service)
[Unit]
Description=Forex Trading Bot
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/path/to/forex_bot
Environment="PATH=/path/to/forex_bot/venv/bin"
ExecStart=/path/to/forex_bot/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable forex-bot
sudo systemctl start forex-bot
```

### Development

```bash
cd app
python main.py
```

Or using uvicorn directly:
```bash
cd app
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Start Bot
```bash
curl -X POST http://localhost:8000/start
```

Response:
```json
{
  "message": "Trading bot started successfully"
}
```

### Stop Bot
```bash
curl -X POST http://localhost:8000/stop
```

Response:
```json
{
  "message": "Trading bot stopped successfully"
}
```

### Get Status
```bash
curl -X GET http://localhost:8000/status
```

Response:
```json
{
  "state": "running",
  "running": true,
  "balance": 10000.0,
  "equity": 10000.0,
  "positions_count": 0,
  "iterations": 120,
  "started_at": "2024-01-31T12:30:45.123456"
}
```

### Health Check
```bash
curl -X GET http://localhost:8000/health
```

## n8n Integration

The bot sends events to n8n via POST requests to your webhook URL. Event structure:

```json
{
  "timestamp": "2024-01-31T12:30:45.123456",
  "event_type": "heartbeat",
  "bot_name": "ForexBot",
  "data": {
    "state": "running",
    "running": true,
    "balance": 10000.0,
    "equity": 10000.0,
    "positions_count": 0,
    "iterations": 120,
    "started_at": "2024-01-31T12:30:45.123456"
  }
}
```

### Event Types
- **started**: Bot started
- **stopped**: Bot stopped
- **heartbeat**: Periodic status update (default: every 60 seconds)
- **error**: Bot encountered an error

## Extending the Bot

### Add a Trading Strategy

Edit `app/strategy.py`:

```python
def generate_signals(self, market_data: Dict[str, Any]) -> list[TradeSignal]:
    """Your trading logic here."""
    signals = []
    
    # Example: Generate buy signal
    if market_data.get("price") > 100:
        signals.append(TradeSignal(
            symbol="EURUSD",
            side="BUY",
            quantity=0.1,
            entry_price=market_data["price"]
        ))
    
    return signals
```

### Add Broker Integration

Replace `app/broker.py` with your broker API (MT5, OANDA, etc.). The interface is:
- `open_position(symbol, quantity, entry_price, side) -> Position`
- `close_position(symbol, exit_price) -> float`
- `get_balance() -> float`
- `get_positions() -> Dict[str, Position]`
- `get_equity(current_prices) -> float`

### Add Risk Management Rules

Edit `app/risk.py` to implement:
- Position sizing logic
- Portfolio heat limits
- Drawdown controls
- Trade frequency limits

## Architecture Notes

- **Thread Safety**: All bot operations are guarded by locks to prevent race conditions
- **Webhook Resilience**: n8n notification failures never crash the bot; errors are logged
- **State Management**: Clear state machine (STOPPED → RUNNING → ERROR)
- **Metrics**: Track iterations, P&L, positions, and timestamps for monitoring
- **Logging**: All operations logged at appropriate levels (INFO, WARNING, ERROR)

## Configuration

All settings come from environment variables (`.env` file):

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| N8N_WEBHOOK_URL | - | Yes | n8n webhook endpoint |
| HEARTBEAT_INTERVAL | 60 | No | Seconds between status updates |
| LOG_LEVEL | INFO | No | Python logging level |
| BOT_NAME | ForexBot | No | Bot identifier for webhooks |
| INITIAL_BALANCE | 10000.0 | No | Paper trading starting balance |

## Monitoring

### Check logs (systemd)
```bash
sudo journalctl -u forex-bot -f
```

### Monitor with n8n
- Create an n8n webhook trigger
- Use the webhook URL in `N8N_WEBHOOK_URL`
- Set up notifications/actions based on event types

## Troubleshooting

### Bot won't start
- Check `.env` file exists and `N8N_WEBHOOK_URL` is set
- Verify network connectivity to n8n instance
- Check logs for configuration errors

### n8n webhook calls failing
- Bot continues operating (graceful degradation)
- Check n8n webhook URL is correct and accessible
- Review webhook logs in n8n UI

### High CPU usage
- Increase `HEARTBEAT_INTERVAL` in `.env`
- Check strategy logic for spinlocks
- Reduce trading loop frequency if needed

## License

MIT

## Support

For issues or questions, check the code comments and architecture patterns in `app/bot.py` and `app/notifier.py`.
>>>>>>> c393ecb (Initial commit: Production-ready forex trading bot with FastAPI and n8n integration)

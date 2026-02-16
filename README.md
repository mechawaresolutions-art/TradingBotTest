# Forex Trading Bot v2.0

A production-oriented forex trading bot with:
- **FastAPI REST control interface** (start/stop/status)
- **Market Data Pipeline** (database-backed candles, gap detection, backfill)
- **Background Trading Loop** (thread-safe, graceful shutdown)
- **n8n Webhook Integration** (events, monitoring)
- **Paper Trading Broker** (position management, P&L)
- **Risk Management** (extensible rules engine)

## Quick Start

### 1. Start Dependencies (Docker)

```bash
docker-compose up -d postgres adminer
```

Check Postgres at `localhost:5432` or Adminer at `http://localhost:8080`

### 2. Install & Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env  # Configure N8N_WEBHOOK_URL, DATABASE_URL
```

### 3. Run Bot

```bash
cd app
python main.py
```

Bot runs at `http://localhost:8000`

---

## Market Data API (MACRO 1)

### Endpoints - Public

#### Get Latest Candle
```bash
curl "http://localhost:8000/v1/candles/latest?symbol=EURUSD&timeframe=M5"
```

#### Get Candle History
```bash
curl "http://localhost:8000/v1/candles?symbol=EURUSD&timeframe=M5&limit=100"
```

Parameters: `symbol`, `timeframe`, `start` (ISO-8601), `end` (ISO-8601), `limit`

#### Check Data Integrity
```bash
curl "http://localhost:8000/v1/candles/integrity?symbol=EURUSD&timeframe=M5&days=7"
```

Returns: earliest, latest, expected count, actual count, missing ranges, is_complete

### Endpoints - Admin

#### Ingest Candles
```bash
curl -X POST "http://localhost:8000/v1/candles/admin/ingest?symbol=EURUSD&timeframe=M5"
```

**Logic:**
1. Find latest candle in DB
2. If empty: fetch last 7 days
3. If exists: fetch from (latest - overlap) with 10 candle overlap
4. Validate OHLC constraints
5. Upsert (no duplicates via UNIQUE constraint)
6. Run integrity check

#### Backfill Range
```bash
curl -X POST "http://localhost:8000/v1/candles/admin/backfill" \
  -G -d "symbol=EURUSD" -d "timeframe=M5" \
  -d "start=2024-01-24T00:00:00Z" \
  -d "end=2024-01-25T00:00:00Z"
```

---

## Trading Bot API (MACRO 2)

### Control Endpoints

```bash
POST   /start          # Start trading bot
POST   /stop           # Stop trading bot
GET    /status         # Bot metrics
GET    /health         # Health check
```

### Execution Endpoints

```bash
GET    /v2/account
GET    /v2/positions
POST   /v2/orders/market
POST   /v2/execution/step
POST   /v1/candles/admin/prune
```

`POST /v2/orders/market` request body supports:
- `symbol`, `side`, `qty`
- optional `sl`, `tp`, `reason`
- optional `idempotency_key` (retry-safe order submission)

## Strategy v1 + Live Loop (MACRO 3)

Implemented strategy:
- SMA crossover (`STRAT_SMA_FAST`, `STRAT_SMA_SLOW`)
- ATR-based SL/TP (`STRAT_ATR_PERIOD`, `STRAT_ATR_SL_MULT`, `STRAT_ATR_TP_MULT`)
- deterministic idempotency key per candle signal
- cooldown via orders table (`STRAT_COOLDOWN_CANDLES`)

Strategy status endpoint:

```bash
GET /v3/strategy/status
```

Example flow:

```bash
# start bot loop
curl -X POST http://localhost:8000/start

# inspect strategy state
curl http://localhost:8000/v3/strategy/status

# stop bot loop
curl -X POST http://localhost:8000/stop
```

---

## Configuration

Create `.env` file (see `.env.example`):

```env
# Bot
N8N_WEBHOOK_URL=http://localhost:5678/webhook/forex-bot
HEARTBEAT_INTERVAL=60
BOT_NAME=ForexBot
INITIAL_BALANCE=10000.0

# Database
DATABASE_URL=postgresql+asyncpg://tradingbot:pass@localhost:5432/tradingbot

# Market Data
SYMBOL=EURUSD
TIMEFRAME=M5
INGEST_OVERLAP_CANDLES=10
INITIAL_BACKFILL_DAYS=7
MARKET_DATA_PROVIDER=mock  # or 'real' when implemented
```

---

## Project Structure

```
forex_bot/
├── app/
│   ├── main.py                  # FastAPI entrypoint
│   ├── config.py                # Env configuration
│   ├── bot.py                   # Trading loop
│   ├── broker.py                # Paper broker
│   ├── strategy.py              # Strategy stub
│   ├── risk.py                  # Risk rules
│   ├── notifier.py              # n8n notifications
│   └── marketdata/              # MACRO 1: Market Data Pipeline
│       ├── models.py            # Candle ORM
│       ├── schemas.py           # Pydantic schemas
│       ├── db.py                # Async DB engine
│       ├── provider_base.py     # Provider interface
│       ├── provider_mock.py     # Deterministic mock
│       ├── provider_real.py     # Real broker (stub)
│       ├── ingest.py           # Ingestion logic
│       ├── integrity.py        # Gap detection
│       ├── router.py           # FastAPI routes
│       └── __init__.py
├── tests/
│   ├── test_marketdata.py       # Pytest suite
│   └── __init__.py
├── n8n/
│   ├── ingest_cron_workflow.json   # Cron every 5 min
│   └── backfill_workflow.json      # Manual backfill
├── docker-compose.yml           # Postgres + Bot
├── requirements.txt
├── .env.example
├── README.md
├── DEPLOYMENT.md
└── PROJECT_REPORT.md
```

---

## Testing

```bash
pytest tests/ -v
```

Tests verify:
- ✅ MockProvider determinism
- ✅ Ingestion idempotency
- ✅ Gap detection
- ✅ Backfill
- ✅ OHLC validation
- ✅ Candle alignment

Additional execution hardening tests:
- ✅ Atomic rollback on mid-operation failure
- ✅ Deterministic replay and idempotent execution step
- ✅ Restart recovery with new engine/session lifecycle
- ✅ Manual/flip close audit trail (`Order -> Fill -> Trade`)
- ✅ Retry-safe order idempotency key
- ✅ Strategy v1 indicators + deterministic signal + 200-candle replay idempotency

Run SQLite-focused execution tests:

```bash
pytest -v \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py \
  tests/test_strategy_v1.py
```

Run Postgres concurrency integration test (requires DSN):

```bash
export TEST_POSTGRES_DSN="postgresql+asyncpg://user:pass@localhost:5432/forex_bot_test"
pytest -v tests/test_postgres_concurrency.py
```

---

## Providers

### MockProvider (Default)

Deterministic, no dependencies. Perfect for testing/demos.

### RealProvider (TODO)

To integrate real data:

1. **MetaTrader5**: `pip install MetaTrader5`
2. **OANDA**: REST API
3. **Other brokers**: Extend `provider_base.MarketDataProvider`

---

## Monitoring

```bash
# Health
curl http://localhost:8000/health

# Adminer (DB browser)
http://localhost:8080

# Logs
docker-compose logs -f forex-bot
```

---

## n8n Integration

Import workflows from `n8n/`:

1. **Ingest Cron** - Fetches new candles every 5 minutes
2. **Backfill Manual** - Webhook-triggered backfill for missing ranges

---

## Extending

### Add Strategy
Edit `app/strategy.py` - implement `generate_signals()`

### Add Real Provider
Create `RealProvider` in `app/marketdata/provider_real.py`

### Add Risk Rules
Edit `app/risk.py` - implement `validate_trade()`

---

## License

MIT

## Support

See `PROJECT_REPORT.md` for detailed architecture and development guide.

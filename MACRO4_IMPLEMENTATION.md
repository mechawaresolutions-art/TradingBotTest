# MACRO 4: Order Management System (OMS) Implementation

## Overview
Macro 4 adds an OMS layer on top of Macro 2/3. It manages order lifecycle and validations while delegating execution to the existing deterministic execution engine.

## Implemented Features
- New OMS API namespace under `/paper`
- Lifecycle handling:
  - create `Order` as `NEW` first
  - validate request (min qty, allowed symbol, market-only)
  - validate free margin before execution
  - transition to `FILLED` on success
  - transition to `REJECTED` with reason on failure
  - cancel `NEW` orders via endpoint
- Idempotent placement by `idempotency_key`:
  - existing order is returned, no duplicate fill
- Deterministic timestamp policy:
  - OMS order timestamps derived from latest candle `open_time`
  - execution continues to use candle-based timestamps only
- No execution reimplementation:
  - OMS calls Macro 2 `place_market_order(...)`
  - execution service extended to fill a pre-created OMS order (`existing_order_id`)

## New Endpoints
- `POST /paper/order`
- `GET /paper/orders`
- `GET /paper/orders/{order_id}`
- `POST /paper/orders/{order_id}/cancel`

## Configuration Added
In `app/config.py`:
- `OMS_MIN_QTY` (default `0.01`)
- `OMS_ALLOWED_SYMBOLS` (default `EURUSD`, comma-separated env list)

## Files Added
- `app/oms/__init__.py`
- `app/oms/schemas.py`
- `app/oms/service.py`
- `app/oms/router.py`
- `tests/test_oms.py`
- `MACRO4_IMPLEMENTATION.md`
- `MACRO4_STATUS.md`

## Files Modified
- `app/execution/service.py`
  - Added optional `existing_order_id` path for OMS lifecycle (`NEW` -> fill on same order row)
  - Ensured fill row gets flushed so `fill.id` is immediately available
- `app/config.py`
  - Added OMS config fields and validation
- `app/main.py`
  - Mounted OMS router

## Tests Added
`tests/test_oms.py`:
- `test_place_order_filled_creates_fill`
- `test_place_order_rejected_no_fill_no_position_change`
- `test_idempotency_key_returns_same_order`
- `test_list_orders_filters_work`
- `test_cancel_new_order`

## Run Commands

### OMS tests
```bash
./.venv/bin/pytest -q tests/test_oms.py
```

### Full SQLite Macro suite used during validation
```bash
./.venv/bin/pytest -q \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py \
  tests/test_execution_no_wall_clock.py \
  tests/test_equity_engine.py \
  tests/test_strategy_v1.py \
  tests/test_oms.py
```

### Optional Postgres concurrency test
```bash
export TEST_POSTGRES_DSN="postgresql+asyncpg://user:pass@localhost:5432/forex_bot_test"
./.venv/bin/pytest -q tests/test_postgres_concurrency.py
```

## Example cURL
```bash
curl -X POST http://localhost:8000/paper/order \
  -H 'Content-Type: application/json' \
  -d '{
    "symbol": "EURUSD",
    "side": "BUY",
    "qty": 0.10,
    "type": "market",
    "stop_loss": 1.0950,
    "take_profit": 1.1050,
    "idempotency_key": "oms-demo-001"
  }'
```

```bash
curl "http://localhost:8000/paper/orders?symbol=EURUSD&status=FILLED&limit=50"
```

```bash
curl -X POST http://localhost:8000/paper/orders/1/cancel
```

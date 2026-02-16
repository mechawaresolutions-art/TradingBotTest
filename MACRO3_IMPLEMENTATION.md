# MACRO 3: Strategy v1 + Equity/Margin Engine (Current Implementation)

## Overview

Macro 3 now includes two major components on top of Macro 2:

1. **Strategy v1 live integration** (EURUSD/M5)
2. **Broker-style account & margin engine** (equity, margin used, free margin, snapshots)

Both are deterministic and persistence-aware.

---

## 1) Strategy v1 (Live Loop)

Implemented strategy: **SMA crossover + ATR SL/TP**

- BUY when `SMA_fast` crosses above `SMA_slow`
- SELL when `SMA_fast` crosses below `SMA_slow`
- SL/TP derived from ATR multipliers
- Signal idempotency key is deterministic and candle-based

Key files:
- `app/strategy_v1.py`
- `app/bot.py`
- `app/main.py` (`GET /v3/strategy/status`)

Determinism:
- Signal generation depends only on candle history.
- Order retries are safe using deterministic `idempotency_key`.

---

## 2) Equity & Margin Engine

### Account Model Extensions

`Account` now includes cached broker-like state:
- `balance`
- `equity`
- `margin_used`
- `free_margin`
- `currency`
- `leverage`

Model file:
- `app/execution/models.py`

### Account Snapshots

Added `AccountSnapshot` for deterministic MTM traceability:
- `account_id`
- `ts` (from `candle.open_time`)
- `balance`
- `equity`
- `margin_used`
- `free_margin`
- `unrealized_pnl`

Uniqueness:
- `UNIQUE(account_id, ts)` for idempotent per-candle snapshots.

Migration:
- `alembic/versions/004_add_account_equity_and_snapshots.py`

### Equity Service

Added `app/equity/service.py`:
- `compute_unrealized_pnl(session, symbol, candle)`
- `compute_margin_used(session, candle)`
- `compute_account_state(session, candle)`
- `mark_to_market_account(session, candle)`
- margin helpers for netting-aware additional margin checks

Pricing rules used for MTM:
- Long positions marked on **BID**
- Short positions marked on **ASK**

### Margin Validation in Order Placement

Integrated into `place_market_order` (`app/execution/service.py`):
- Computes current account state for latest candle
- Computes incremental margin required for the requested order under netting
- Rejects if `free_margin < additional_margin_required`
- Rejection is fail-fast and creates no `Order`/`Fill`
- Executed atomically in the same DB transaction scope

---

## 3) API Endpoints

### Strategy
- `GET /v3/strategy/status`
  - last candle time
  - last signal
  - cooldown state
  - open position summary

### Account / Margin
- `GET /v3/account`
- `GET /v3/account/snapshots?limit=...`
- `POST /v3/account/mtm`

Router files:
- `app/equity/router.py`
- `app/main.py` (router registration)

---

## 4) Configuration

Added in `app/config.py`:
- `ACCOUNT_CURRENCY` (default `USD`)
- `ACCOUNT_LEVERAGE` (default `30`)
- `CONTRACT_SIZE` (default `100000`)
- `MARGIN_MODE` (default `simple`)

Validation rules included for all above fields.

---

## 5) Determinism & Persistence Notes

- Execution timestamps (`Order.ts`, `Fill.ts`, `Trade.exit_ts`) use candle-derived time.
- MTM snapshot timestamp is `candle.open_time`.
- No wall-clock timestamp is used in execution/equity logic paths for event timing.
- State is persisted in DB and restart-safe.

---

## 6) Tests

### New Macro 3 Equity Tests
- `tests/test_equity_engine.py`
  1. MTM correctness (long BID / short ASK)
  2. Margin used correctness
  3. Trade blocking when free margin insufficient
  4. MTM idempotency for same candle
  5. Restart safety across engine/session reopen

### Existing Macro 2 + Strategy tests still passing
- `tests/test_execution_no_wall_clock.py`
- `tests/test_execution.py`
- `tests/test_deterministic_replay.py`
- `tests/test_macro2_2_hardening.py`
- `tests/test_macro2_completion.py`
- `tests/test_postgres_concurrency.py` (env-gated)
- `tests/test_strategy_v1.py`

---

## 7) How to Run

SQLite suite (Macro 2 + Macro 3):

```bash
./.venv/bin/pytest -q \
  tests/test_equity_engine.py \
  tests/test_execution_no_wall_clock.py \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py \
  tests/test_strategy_v1.py
```

Optional Postgres concurrency test:

```bash
export TEST_POSTGRES_DSN="postgresql+asyncpg://user:pass@localhost:5432/forex_bot_test"
./.venv/bin/pytest -q tests/test_postgres_concurrency.py
```

---

## Current Status

Macro 3 is implemented with:
- deterministic Strategy v1 live loop integration,
- broker-style equity/margin engine,
- netting-aware margin guardrails in order placement,
- account snapshot persistence and idempotent MTM,
- API visibility endpoints for strategy/account state.

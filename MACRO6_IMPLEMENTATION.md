# MACRO 6: Risk & Portfolio Engine Implementation

## Overview
Macro 6 is implemented as a deterministic pre-trade risk gate that runs before OMS creates executable orders.

## Implemented Modules
- `app/risk/models.py`
  - `RiskLimits` table (one row per account)
  - `DailyEquity` table with deterministic per-day baseline (`UNIQUE(account_id, day)`)

- `app/risk/schemas.py`
  - request/response contracts for risk status and risk check

- `app/risk/service.py`
  - `RiskEngine.compute_snapshot(...)`
  - `RiskEngine.check_order(...)`
  - deterministic day handling from `asof_open_time`
  - idempotent daily baseline creation

- `app/risk/api.py`
  - `GET /v6/risk/status`
  - `POST /v6/risk/check`

- `app/risk/__init__.py`
  - package exports + router
  - compatibility export for legacy `RiskManager`

## Migration
- `alembic/versions/005_add_risk_tables.py`
  - creates `risk_limits`
  - creates `daily_equity`
  - adds indexes for daily equity lookups

## OMS Integration
Updated `app/oms/service.py` so Macro 6 runs before `NEW` creation:
1. Validate payload deterministically
2. Resolve deterministic candle
3. Compute stop distance in pips from expected fill side/price
4. Call `RiskEngine.check_order(...)`
5. If rejected: persist `REJECTED` order with clear reason
6. If allowed: create order with `approved_qty` and continue existing flow

This preserves idempotency-key behavior and deterministic timestamping (`order.ts = candle.open_time`).

## Risk Rules Implemented
- Max open positions (global)
- Max open positions per symbol
- Max symbol notional
- Max total notional
- Risk-per-trade sizing (based on `stop_distance_pips` and equity)
- Daily loss limit check (pct and/or amount)
- Margin/leverage check (`required_margin` vs `free_margin`)

## Deterministic Guarantees
- No wall-clock for business decisions
- Day is derived from `asof_open_time` UTC date
- Snapshot and checks depend only on DB state + candle data + config
- Daily baseline row creation is idempotent

## Tests Added
- `tests/test_macro6_risk_engine.py`
  1. max open positions rejection
  2. per-symbol position cap rejection
  3. symbol notional cap rejection
  4. total notional cap rejection
  5. risk sizing approved quantity
  6. daily loss limit breach blocks new orders
  7. margin check rejection when free margin insufficient
  8. idempotent daily_equity creation (single row per day)

## Command Evidence
- `./.venv/bin/pytest -q tests/test_macro6_risk_engine.py` -> **8 passed**
- `./.venv/bin/pytest -q tests/test_oms.py tests/test_macro6_risk_engine.py tests/test_macro5_execution_engine.py` -> **19 passed**

## Note on Full Suite
Running full `pytest -q` currently reports two failures in `tests/test_marketdata.py` (`test_ingestion_idempotent`, `test_integrity_detects_gaps`) unrelated to Macro 6 changes.

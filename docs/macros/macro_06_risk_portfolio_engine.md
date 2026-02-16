# Macro 06: Risk & Portfolio Engine (Deterministic)

## Scope
Macro 6 adds deterministic pre-trade risk gating before OMS creates executable orders.

## Deterministic Invariants
- No wall-clock dependencies.
- No randomness.
- Risk checks depend only on DB state, config, and `asof_open_time` / candle data.
- Trading day is `UTC date(asof_open_time)`.

## Core Formulas
- `notional = abs(qty) * mid_price`
- `required_margin = notional / leverage`
- `free_margin = equity - margin_used`
- Risk sizing:
  - `risk_amount = equity * risk_per_trade_pct`
  - `pip_value_per_unit = 0.0001`
  - `max_units = risk_amount / (pip_value_per_unit * stop_distance_pips)`
  - `approved_qty = min(requested_qty, floor_to_step(max_units, RISK_LOT_STEP))`

## Daily Loss
- `day = date(asof_open_time UTC)`
- baseline from `daily_equity.day_start_equity`
- breach if either:
  - `equity <= day_start_equity * (1 - daily_loss_limit_pct)`
  - `equity <= day_start_equity - daily_loss_limit_amount`

## Data Model
- `risk_limits(account_id PK, max_open_positions, max_open_positions_per_symbol, max_total_notional, max_symbol_notional, risk_per_trade_pct, daily_loss_limit_pct, daily_loss_limit_amount, leverage)`
- `daily_equity(id PK, account_id, day, day_start_equity, min_equity, UNIQUE(account_id, day))`

## API
- `GET /v6/risk/status`
- `POST /v6/risk/check`

## OMS Integration
OMS calls `RiskEngine.check_order(...)` before creating a `NEW` order.
- reject path: persisted `REJECTED` order with deterministic reason
- allow path: creates order using `approved_qty`

## Definition Of Done
- [x] deterministic risk snapshot from candle time
- [x] max open positions checks
- [x] per-symbol position cap checks
- [x] symbol and total notional cap checks
- [x] risk-per-trade sizing
- [x] daily loss limit enforcement
- [x] margin/leverage enforcement
- [x] idempotent daily equity row creation
- [x] `/v6/risk/check` and `/v6/risk/status` endpoints
- [x] OMS pre-check integration before `NEW` order creation
- [x] migration and tests added

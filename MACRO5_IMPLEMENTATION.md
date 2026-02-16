# MACRO 5: Execution & Fill Engine Implementation

## Overview
Macro 5 introduces a deterministic execution runner that converts OMS `NEW` market orders into exactly one fill per order using a strict replay-safe model.

## Implemented Components
- `app/execution/pricing.py`
  - `PricingModel.quote(candle, spread_pips) -> (bid, ask)` using `candle.open` as mid.
  - `apply_slippage(side, bid, ask, slippage_pips)` deterministic side-aware slippage.

- `app/execution/engine.py`
  - `ExecutionEngine.execute_market_order(order, fill_candle) -> FillOutput`
  - typed contracts: `OrderInput`, `CandleInput`, `FillOutput`, `ExecutionError`.

- `app/execution/service.py`
  - `process_new_orders_for_candle(session, fill_candle_open_time, symbol, timeframe) -> list[Fill]`
  - fills only eligible `NEW` market orders at next-open candle.
  - idempotent fill handling (one fill per `order_id`).
  - deterministic rejections for invalid qty/side or missing deterministic candle.

- `app/config.py`
  - added `EXECUTION_SLIPPAGE_PIPS` (validated, non-negative).

- `docs/macros/macro_05_execution_fill_engine.md`
  - full spec, formulas, invariants, worked numeric example, definition of done checklist.

## Fill Model
- Next-open rule: order at candle `t` fills only at first candle with `open_time > order.ts`.
- Price model:
  - `mid = candle.open`
  - `bid = mid - spread/2`
  - `ask = mid + spread/2`
  - `BUY = ask + slippage`
  - `SELL = bid - slippage`

## Safety Rules Enforced
- No wall-clock timestamp used by Macro 5 decision logic.
- No randomness.
- Missing fill candle fails fast with deterministic-safety message.
- Duplicate execution attempt does not create duplicate fills.

## Tests
`tests/test_macro5_execution_engine.py` includes:
1. determinism across runs
2. bid/ask correctness
3. spread effect on price
4. slippage effect on price
5. fail-fast missing candle
6. idempotency (no duplicate fill)

## Validation Commands
```bash
./.venv/bin/pytest -q tests/test_macro5_execution_engine.py
```

```bash
./.venv/bin/pytest -q \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py \
  tests/test_execution_no_wall_clock.py \
  tests/test_equity_engine.py \
  tests/test_strategy_v1.py \
  tests/test_oms.py \
  tests/test_macro5_execution_engine.py
```

# Macro 05: Execution & Fill Engine (Deterministic Broker Simulator)

## Purpose
Macro 5 converts OMS `NEW` market orders into deterministic fills using only persisted state and candle data.

## Responsibilities
- Enforce next-open fill rule: order at candle `t` fills at candle `t+1 open`.
- Price fills with deterministic bid/ask + fixed slippage.
- Persist exactly one fill per order (`fills.order_id` unique).
- Transition order status:
  - `NEW -> FILLED` when executed
  - `NEW -> REJECTED` for deterministic-safety errors only
- Expose fill outputs for Macro 6 consumption.

## Deterministic Invariants
- No wall-clock time (`datetime.now`, `utcnow`, etc.) in execution decisions.
- No randomness.
- Decisions depend only on:
  - persisted order state
  - candle open/open_time
  - configured spread/slippage
- Processing same order twice must not create a second fill.

## Pricing Formulas
- `mid = candle.open`
- `bid = mid - (spread_pips * pip_value) / 2`
- `ask = mid + (spread_pips * pip_value) / 2`
- `BUY fill = ask + slippage_pips * pip_value`
- `SELL fill = bid - slippage_pips * pip_value`

For EURUSD:
- `pip_value = 0.00010`

## Worked Example
Inputs:
- `candle.open = 1.10000`
- `spread = 1.0 pip`
- `slippage = 0.5 pip`

Steps:
- spread price = `1.0 * 0.00010 = 0.00010`
- half spread = `0.00005`
- `bid = 1.10000 - 0.00005 = 1.09995`
- `ask = 1.10000 + 0.00005 = 1.10005`
- slippage price = `0.5 * 0.00010 = 0.00005`
- `BUY fill = 1.10005 + 0.00005 = 1.10010`
- `SELL fill = 1.09995 - 0.00005 = 1.09990`

## Flow
1. Runner receives `fill_candle_open_time`.
2. Loads fill candle for symbol/timeframe.
3. Loads `NEW` market orders.
4. For each order:
   - if fill exists: return existing fill (idempotent)
   - validate qty/side/type
   - find first candle strictly after `order.ts`
   - execute only if that next candle equals runner candle
   - persist fill and mark order `FILLED`
5. Return list of fills.

## Interfaces
- `app/execution/pricing.py`
  - `PricingModel.quote(candle, spread_pips) -> (bid, ask)`
- `app/execution/engine.py`
  - `ExecutionEngine.execute_market_order(order, fill_candle) -> FillOutput`
- `app/execution/service.py`
  - `process_new_orders_for_candle(session, fill_candle_open_time, symbol, timeframe) -> list[Fill]`

## Definition Of Done
- [x] Next-open fill rule implemented
- [x] Deterministic bid/ask from candle open
- [x] Deterministic fixed slippage model
- [x] No wall-clock dependency in Macro 5 decisions
- [x] Missing fill candle fails fast with deterministic-safety error
- [x] One fill per order (idempotent)
- [x] Order status transitions are persisted
- [x] Fill output is returned for Macro 6
- [x] Tests for determinism and pricing behavior exist
- [x] Tests for fail-fast and idempotency exist

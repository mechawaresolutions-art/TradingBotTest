# Macro 07: Deterministic Equity & PnL Accounting Engine

## Purpose
Macro 7 is the authoritative accounting source for:
- fill application to net positions
- realized PnL and balance updates
- unrealized PnL and equity snapshots
- margin_used and free_margin snapshots

## Netting Model (per account + symbol)
- Single net position row per `(account_id, symbol)`.
- Fields:
  - `net_qty` (signed)
  - `avg_entry_price`
  - `updated_open_time`

Fill application outcomes:
1. Same-side increase: weighted average update
2. Opposite-side partial/full close: realized PnL on closed qty
3. Cross-through: close existing side then open opposite side with leftover qty at fill price

## Formulas
Realized PnL:
- Closing long qty: `(exit_price - avg_entry_price) * close_qty`
- Closing short qty: `(avg_entry_price - exit_price) * close_qty`

Unrealized PnL (MTM at candle open mid):
- Long: `(mid - avg_entry_price) * qty`
- Short: `(avg_entry_price - mid) * abs(qty)`

Snapshot:
- `equity = balance + unrealized_pnl`
- `margin_used = sum(abs(net_qty) * mid / leverage)`
- `free_margin = equity - margin_used`

## Idempotency Mechanism
- `fills.accounted_at_open_time` is nullable.
- `apply_new_fills` only consumes fills with `accounted_at_open_time IS NULL` and `fill.ts <= asof_open_time`.
- After apply, sets marker deterministically.
- Re-running on same state does not double-count balance/PnL.

## Snapshot Schema
Table: `accounting_snapshots`
- `account_id`
- `asof_open_time`
- `balance`
- `equity`
- `unrealized_pnl`
- `margin_used`
- `free_margin`
- unique `(account_id, asof_open_time)`

## Example Walkthrough
1. Fill BUY 2 @ 1.1000 -> position `+2 @ 1.1000`
2. Fill SELL 1 @ 1.1010 -> close 1, realized `+0.0010`, remaining `+1 @ 1.1000`
3. MTM candle open 1.1020 -> unrealized `(1.1020 - 1.1000) * 1 = +0.0020`
4. Equity = `balance + 0.0020`

## API
- `GET /v7/account/status`
- `POST /v7/account/recompute`

## Definition Of Done
- [x] deterministic fill->position accounting
- [x] realized pnl updates account balance
- [x] mark-to-market snapshots per candle
- [x] one snapshot row per account+asof time
- [x] idempotent fill application via fill marker
- [x] deterministic fill ordering by `(fill.ts, fill.id)`
- [x] margin/free_margin computed from deterministic prices
- [x] `/v7/account/status` endpoint
- [x] `/v7/account/recompute` endpoint
- [x] dedicated Macro 7 tests

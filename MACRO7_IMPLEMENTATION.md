# MACRO 7: Deterministic Equity & PnL Accounting Engine

## Implemented
- New package `app/accounting/`:
  - `models.py`
  - `schemas.py`
  - `service.py`
  - `api.py`
  - `__init__.py`
- New migration:
  - `alembic/versions/006_add_macro7_accounting_tables.py`
- New docs:
  - `docs/macros/macro_07_accounting_engine.md`
- New tests:
  - `tests/test_macro7_accounting_engine.py`

## Data Model
- `accounting_positions`
  - netting position by `(account_id, symbol)`
  - fields: `net_qty`, `avg_entry_price`, `updated_open_time`
- `accounting_snapshots`
  - deterministic snapshot by `(account_id, asof_open_time)`
  - fields: `balance`, `equity`, `unrealized_pnl`, `margin_used`, `free_margin`
- `realized_trades`
  - realized PnL ledger linked to `fill_id` / `order_id`
- `fills.accounted_at_open_time`
  - idempotency marker for fill application

## Engine Functions
- `AccountingEngine.apply_new_fills(...)`
  - applies unaccounted fills in deterministic order `(fill.ts, fill.id)`
  - updates netting position
  - realizes PnL on closes
  - updates `accounts.balance`
  - writes `realized_trades`
  - marks fills as accounted (idempotent)

- `AccountingEngine.mark_to_market(...)`
  - computes unrealized PnL from deterministic candle open
  - computes equity, margin_used, free_margin
  - upserts deterministic snapshot for `asof_open_time`

- `AccountingEngine.process_accounting_for_candle(...)`
  - applies fills then MTM for a candle

## API
- `GET /v7/account/status`
- `POST /v7/account/recompute`

Mounted in `app/main.py`.

## Macro Compatibility
- Macro 4/5/6 behavior remains intact.
- Macro 7 is additive and authoritative for accounting snapshots.

## Test Coverage (Macro 7)
- open position
- increase same side weighted average
- partial close realized pnl
- full close reset behavior
- cross-through reversal
- idempotent apply_new_fills
- MTM snapshot correctness
- snapshot uniqueness/upsert
- deterministic fill ordering
- margin/free_margin sanity

## Commands
```bash
./.venv/bin/pytest -q tests/test_macro7_accounting_engine.py
```

```bash
./.venv/bin/pytest -q tests/test_oms.py tests/test_macro5_execution_engine.py tests/test_macro6_risk_engine.py tests/test_macro7_accounting_engine.py
```

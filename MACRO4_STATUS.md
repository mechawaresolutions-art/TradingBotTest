# MACRO 4 Status

## Completion
- Status: ✅ Implemented
- Scope delivered: OMS API + lifecycle manager integrated with Macro 2/3

## New Features
- `/paper` OMS endpoints added:
  - `POST /paper/order`
  - `GET /paper/orders`
  - `GET /paper/orders/{order_id}`
  - `POST /paper/orders/{order_id}/cancel`
- Order lifecycle implemented:
  - `NEW` creation first
  - validation-driven `REJECTED`
  - execution-driven `FILLED`
  - user cancel for `NEW` -> `CANCELED`
- Idempotency supported via `idempotency_key`
- Margin and symbol/qty validation integrated before execution
- Execution reused (no duplicate execution engine)
- Deterministic timestamps preserved from candle `open_time`

## Tests Passed
- `tests/test_oms.py`: **5 passed**
- Full SQLite macro suite: **31 passed**
- Postgres concurrency suite: **1 skipped** (env-gated by `TEST_POSTGRES_DSN`)

## Notes
- No new Alembic revision required for Macro 4 (reused existing `orders` schema + idempotency column).

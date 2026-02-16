# MACRO 2: Paper Broker & Execution Engine (Current State)

## Completion Verdict

**YES — Macro 2 is completed.**

### Why

1. Core schema is in place and versioned with Alembic (`001`, `002`, `003`), including unique fill protection and order idempotency key support.
2. Execution correctness is implemented: BUY at ask, SELL at bid, and mark-to-market uses bid/ask by position side.
3. Safety requirements are implemented: explicit transaction scopes, Postgres row-lock aware updates, and SQLite fallback behavior.
4. Reliability requirements are covered: idempotent candle execution, retry-safe order placement, strict restart recovery test, and deterministic replay coverage.
5. Auditability and retention are enforced: manual/flip closes create `Trade` rows and candle pruning is based on `open_time` with reported cutoff/deleted count.

## Status

MACRO 2 implementation has been hardened with:
- deterministic bid/ask pricing
- explicit transaction scopes for write paths
- Postgres row-lock aware mutation logic
- strict fill uniqueness (`UNIQUE(order_id)`)
- retention pruning by `candle.open_time`
- idempotent execution step (no duplicate close on same candle)
- retry-safe order placement with optional `idempotency_key`
- audit trail for manual/opposite-side netting closes (trade rows now created)

## Key Behaviors

1. Pricing correctness
- BUY fills at ask, SELL fills at bid
- mark-to-market: long uses bid, short uses ask

2. Atomicity
- `place_market_order` and `update_on_candle` execute in explicit transaction scopes

3. Concurrency safety
- Postgres: `FOR UPDATE` used on mutable rows (positions/accounts)
- SQLite: fallback behavior supported by tests

4. Auditability
- Realized PnL from manual partial/full/flip closes creates `Trade` rows
- Entry/exit order linkage is persisted

5. Retention
- Pruning uses `Candle.open_time` and returns `deleted_count` + `cutoff_time`

## Migrations

- `001_initial_schema`
- `002_add_unique_fill_order_id`
- `003_add_order_idempotency_key`

## Test Coverage

SQLite execution/hardening suite:

```bash
pytest -v \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py
```

Postgres concurrency integration (requires env var):

```bash
export TEST_POSTGRES_DSN="postgresql+asyncpg://user:pass@localhost:5432/forex_bot_test"
pytest -v tests/test_postgres_concurrency.py
```

Notes:
- If `TEST_POSTGRES_DSN` is not set, the Postgres test is skipped by design.

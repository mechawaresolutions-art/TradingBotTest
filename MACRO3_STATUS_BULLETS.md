# MACRO 3 Status (Bullets)

## New Features

- Deterministic Strategy v1 integrated in live loop (`EURUSD`, `M5`)
- SMA crossover signals with ATR-based SL/TP
- Deterministic signal idempotency key (derived from candle context)
- Cooldown enforcement to reduce overtrading
- Skip same-direction re-entry when position already matches signal
- Broker-style equity engine added:
  - `balance`
  - `equity`
  - `margin_used`
  - `free_margin`
  - `leverage`
- Netting-aware margin check integrated into order placement (atomic with trade creation)
- Order rejection on insufficient free margin with no `Order`/`Fill` side effects
- Account snapshots persisted per candle (`AccountSnapshot`) for replay/debugging
- Idempotent mark-to-market per candle timestamp
- New account API endpoints:
  - `GET /v3/account`
  - `GET /v3/account/snapshots`
  - `POST /v3/account/mtm`
- Strategy status endpoint:
  - `GET /v3/strategy/status`

## Passed Tests

Latest combined run:
- `26 passed`
- `1 skipped` (Postgres env-gated test)
- `0 failed`

Command used:

```bash
./.venv/bin/pytest -q \
  tests/test_equity_engine.py \
  tests/test_execution_no_wall_clock.py \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py \
  tests/test_postgres_concurrency.py \
  tests/test_strategy_v1.py
```

## Test Files Covered

- `tests/test_equity_engine.py`
- `tests/test_execution_no_wall_clock.py`
- `tests/test_execution.py`
- `tests/test_deterministic_replay.py`
- `tests/test_macro2_2_hardening.py`
- `tests/test_macro2_completion.py`
- `tests/test_postgres_concurrency.py`
- `tests/test_strategy_v1.py`

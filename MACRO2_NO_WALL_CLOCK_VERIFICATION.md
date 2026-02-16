# Macro 2 No-Wall-Clock Verification

## 1) PASS/FAIL Verdict

**PASS** for the specific patch claim.

What is verified:
- `place_market_order` no-candle branch no longer uses wall-clock timestamps.
- No-candle branch fails fast with `RuntimeError`.
- No-candle branch does not persist `Order` rows.
- Execution write timestamps for `Order.ts`, `Fill.ts`, `Trade.exit_ts`, and flipped `Position.opened_at` are derived from `candle.open_time`.

---

## 2) Wall-Clock Match Inventory (execution + related paths)

Search patterns:
- `datetime.now`, `datetime.utcnow`, `time.time`, `func.now`, `CURRENT_TIMESTAMP`, `timezone.now`, `pendulum.now`, `arrow.now`

Matches found:
1. `app/execution/models.py:18` -> `func.now()` on `Account.updated_at`
   - Critical execution write path timestamp? **No** (metadata/update field, not order/fill/trade event ts source)
   - Determinism violation? **No (for Macro 2 execution replay invariant)**

2. `app/execution/models.py:28` -> `func.now()` default for `Order.ts`
   - Critical? **Potential fallback only**; service currently sets explicit `ts=candle.open_time` for execution writes.
   - Determinism violation? **Not currently**, but a future caller could omit `ts`.

3. `app/execution/models.py:47` -> `func.now()` default for `Fill.ts`
   - Critical? **Potential fallback only**; service currently sets explicit `ts=candle.open_time`.
   - Determinism violation? **Not currently**, same caveat.

4. `app/execution/models.py:63` -> `func.now()` default for `Position.opened_at`
   - Critical? **Potential fallback only**; service explicitly sets `opened_at=candle.open_time` for opens/flips.
   - Determinism violation? **Not currently**, same caveat.

5. `app/execution/models.py:64` -> `func.now()` on `Position.updated_at`
   - Critical execution timestamp? **No** (bookkeeping field)
   - Determinism violation? **No** for replay invariants.

6. `app/marketdata/retention.py:18` -> `datetime.now(timezone.utc)`
   - Critical execution write path? **No** (admin retention cutoff logic)
   - Determinism violation? **No** for order/fill/trade timestamp invariant.

No wall-clock matches remain in `app/execution/service.py` execution timestamp assignment paths.

---

## 3) Determinism Source for Timestamps

### `Order.ts`
- `app/execution/service.py` `place_market_order`:
  - `ts=candle.open_time` at `app/execution/service.py:166`
- `app/execution/service.py` `update_on_candle`:
  - `ts=candle.open_time` at `app/execution/service.py:361`

### `Fill.ts`
- `app/execution/service.py` `place_market_order`:
  - `ts=candle.open_time` at `app/execution/service.py:180`
- `app/execution/service.py` `update_on_candle`:
  - `ts=candle.open_time` at `app/execution/service.py:374`

### `Trade.entry_ts` / `Trade.exit_ts`
- `app/execution/service.py` `_build_trade` and calls in manual/netting paths:
  - `entry_ts=pos.opened_at`, `exit_ts=candle_time` at `app/execution/service.py:61-62`
  - `candle_time` passed as `candle.open_time` at `app/execution/service.py:228`, `app/execution/service.py:247`
- `app/execution/service.py` `update_on_candle`:
  - `entry_ts=pos.opened_at`, `exit_ts=candle.open_time` at `app/execution/service.py:379-380`

### Account timestamps used for logic
- `Account.updated_at` has model-level `func.now()` (`app/execution/models.py:18`) but **is not used as execution decision timestamp source**.
- Account PnL logic updates balance numerically (`acct.balance = acct.balance + pnl`) in execution service.

---

## 4) No-Candle Branch Verification (`place_market_order`)

Location: `app/execution/service.py:151-155`

Verified behavior:
- Raises immediately:
  - `RuntimeError("No market data available for fills: deterministic execution requires latest candle.open_time")`
- Does **not** call `session.add(Order(...))` in this branch.
- Does **not** commit.
- Does **not** create rejected orders.
- Does **not** create fill/trade artifacts.

---

## 5) Regression Test Strictness Review

File: `tests/test_execution_no_wall_clock.py`

Current checks:
- Uses async SQLAlchemy fixture and fresh in-memory DB.
- Calls `place_market_order` with no candles.
- Asserts `RuntimeError` is raised.
- Asserts `Order` count remains zero.

Strictness gap:
- It does not assert `Fill` and `Trade` counts remain zero.

### Suggested patch diff (strictness improvement)

```diff
diff --git a/tests/test_execution_no_wall_clock.py b/tests/test_execution_no_wall_clock.py
index cb2f60a..f5c3f1d 100644
--- a/tests/test_execution_no_wall_clock.py
+++ b/tests/test_execution_no_wall_clock.py
@@ -4,10 +4,10 @@ from sqlalchemy import func, select
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
 
 from app.marketdata.models import Base
-from app.execution.models import Order
+from app.execution.models import Order, Fill, Trade
 from app.execution.service import place_market_order
@@
 async def test_place_market_order_requires_candle_and_never_uses_wall_clock(session):
@@
     order_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
+    fill_count = (await session.execute(select(func.count(Fill.id)))).scalar() or 0
+    trade_count = (await session.execute(select(func.count(Trade.id)))).scalar() or 0
     assert order_count == 0
+    assert fill_count == 0
+    assert trade_count == 0
```

---

## 6) Run Plan

Single regression test:

```bash
./.venv/bin/pytest -q tests/test_execution_no_wall_clock.py
```

Full Macro 2 suite (SQLite):

```bash
./.venv/bin/pytest -q \
  tests/test_execution_no_wall_clock.py \
  tests/test_execution.py \
  tests/test_deterministic_replay.py \
  tests/test_macro2_2_hardening.py \
  tests/test_macro2_completion.py
```

Optional Postgres suite:

```bash
export TEST_POSTGRES_DSN="postgresql+asyncpg://user:pass@localhost:5432/forex_bot_test"
./.venv/bin/pytest -q tests/test_postgres_concurrency.py
```

---

## 7) Remaining Risks

- Model defaults still contain `func.now()` for some columns (`Order.ts`, `Fill.ts`, `Position.opened_at`). Current execution service always overrides these with candle-derived timestamps, but future write paths could regress if they omit explicit timestamps.
- Retention logic uses wall-clock time by design (`app/marketdata/retention.py`), which is acceptable because it is not part of deterministic execution event timestamping.

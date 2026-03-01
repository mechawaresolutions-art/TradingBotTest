# MACRO 9: Orchestration & Reporting Implementation

## Overview
Macro 9 is implemented as a deterministic orchestration layer that runs a full trading cycle for a specific candle timestamp and persists a run report.

## Implemented Modules
- New package `app/orchestrator/`
  - `models.py`
    - `RunReport` table model (`run_reports`)
    - unique key: `(symbol, timeframe, candle_ts)`
  - `schemas.py`
    - `OrchestratorRunRequest`
    - `OrchestratorRunResult`
    - `RunReportModel`
    - `OrderPlan`
  - `service.py`
    - `OrchestratorService.run_cycle(...)`
    - deterministic `run_id` generation (`uuid5`)
    - deterministic order idempotency key per candle/side
    - run report persistence for `OK`, `NOOP`, `ERROR`
  - `api.py`
    - `POST /orchestrator/run`
    - `GET /orchestrator/runs`
    - `GET /orchestrator/runs/{run_id}`
  - `__init__.py`

## DB Migration
- `alembic/versions/007_add_macro9_run_reports.py`
  - creates `run_reports`
  - adds indexes:
    - `ix_run_reports_candle_ts`
    - `ix_run_reports_status`

## Main App Wiring
- `app/main.py`
  - mounts orchestrator router
  - imports orchestrator models during startup for metadata registration

## Orchestration Flow (Deterministic Order)
1. Validate candle exists for `(symbol, timeframe, candle_ts)`.
2. Idempotency check for existing `OK/NOOP` run report.
3. Mark-to-market account update.
4. Compute StrategyIntent for the target candle.
5. If HOLD -> persist `NOOP`.
6. Run risk sizing and build `OrderPlan`.
7. Place market order via OMS.
8. Resolve order/fill details.
9. Update accounting/positions/PnL snapshot.
10. Compose summary + telegram text.
11. Persist `run_report` with status `OK`.
12. On exception: persist `ERROR` with `error_text`.

## Persistence Contract
Stored per run:
- `run_id`, `status`, `symbol`, `timeframe`, `candle_ts`, `mode`
- `intent_json`, `risk_json`, `order_json`, `fill_json`
- `positions_json`, `account_json`
- `summary_text`, `telegram_text`, `error_text`

## Telegram Text
- Stable multiline format
- Always includes:
  - `run_id`
  - `status`
  - symbol/timeframe/candle_ts
  - summary

## Tests Added
- `tests/test_macro9_orchestrator.py`
  1. idempotency: second run on same candle does not place a second order
  2. HOLD intent persists `NOOP` run report
  3. exception path persists `ERROR` run report with `error_text`

## Command Evidence
- `./.venv/bin/pytest -q tests/test_macro9_orchestrator.py` -> **3 passed**

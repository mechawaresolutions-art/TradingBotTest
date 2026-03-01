# MACRO 8: Strategy Macro (Signal Generator) Implementation

## Overview
Macro 8 is implemented as a pure, deterministic strategy layer that outputs `StrategyIntent` (not orders).

## Implemented Modules
- New package `app/strategy_engine/`
  - `base.py`
    - `BaseStrategy` abstraction
    - `compute_intent(candles: list[Candle]) -> StrategyIntent`
    - `name`, `default_params`, `reset()`, `get_state()`
  - `indicators.py`
    - `compute_ema(...)`
    - `compute_atr(...)` (Wilder smoothing)
  - `ema_atr.py`
    - `EmaAtrStrategy`:
      - BUY on EMA fast cross above EMA slow
      - SELL on EMA fast cross below EMA slow
      - HOLD otherwise
      - ATR-based risk hints:
        - `SL = 1.5 * ATR`
        - `TP = 2.0 * ATR`
  - `service.py`
    - `StrategyRunner`
      - fetches last N candles (default warmup `200`)
      - runs pure strategy
      - returns HOLD with `insufficient_data` when candles are not enough
      - optional gap detection appends `data_gap_detected` in reason
      - strategy registry + strategy catalog support
  - `schemas.py`
    - `StrategyRunRequest`
    - `StrategyIntent`
    - `StrategyIndicators`
    - `StrategyRiskHints`
    - `StrategyCatalogOut`
  - `api.py`
    - `GET /strategy/strategies`
    - `POST /strategy/run`
  - `__init__.py`

## API Integration
- Router mounted in `app/main.py`:
  - `app.include_router(strategy_router)`

## Intent Contract (MVP)
- `action`: `BUY | SELL | HOLD | CLOSE`
- `reason`: string (`cross_up`, `cross_down`, `no_cross`, `insufficient_data`, optional `data_gap_detected`)
- `symbol`, `timeframe`
- `ts`: candle `open_time` from market data
- `indicators`: `ema_fast`, `ema_slow`, `atr`
- `risk_hints`: `stop_loss_price`, `take_profit_price`
- `summary`: single-line deterministic summary string

## Determinism and Architecture Constraints
- No wall-clock time used by Macro 8 business logic.
- No randomness.
- Strategy logic is pure and does not mutate account/positions.
- Strategy does not call OMS/execution and does not place orders.
- DB access is confined to `StrategyRunner` service layer.
- FastAPI routes are thin and delegate to services.

## Tests Added
- `tests/test_macro8_strategy_engine.py`
  1. cross up -> BUY
  2. cross down -> SELL
  3. insufficient candles -> HOLD
  4. ATR SL/TP distance sanity

## Command Evidence
- `./.venv/bin/pytest -q tests/test_macro8_strategy_engine.py` -> **4 passed**

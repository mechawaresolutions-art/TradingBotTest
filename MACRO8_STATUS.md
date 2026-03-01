# MACRO 8 Status

## Completion
- Status: ✅ Implemented (Macro 8 scope delivered)

## Delivered
- Pure strategy abstractions (`BaseStrategy`)
- EMA/ATR in-code indicators (no heavy TA dependency)
- `EmaAtrStrategy` with EMA cross logic and ATR-based SL/TP hints
- `StrategyRunner` service with deterministic warmup fetch and insufficient-data HOLD behavior
- Optional data-gap flagging (`data_gap_detected`)
- Strategy API endpoints:
  - `GET /strategy/strategies`
  - `POST /strategy/run`
- Response includes deterministic `summary` field

## Tests
- `tests/test_macro8_strategy_engine.py`: **4 passed**

## Notes
- Macro 8 is signal-only: it does not place orders and does not call OMS/execution.
- Timestamp source is candle data (`open_time`) for replay safety.

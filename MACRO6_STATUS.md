# MACRO 6 Status

## Completion
- Status: ✅ Implemented (Macro 6 scope delivered)

## Delivered
- Deterministic risk engine module (`app/risk/`)
- DB persistence for limits + deterministic daily baseline (`risk_limits`, `daily_equity`)
- Risk endpoints:
  - `GET /v6/risk/status`
  - `POST /v6/risk/check`
- OMS pre-check integration before creating `NEW` order
- Deterministic reject path with persisted `REJECTED` orders and reasons
- Risk-per-trade sizing with `approved_qty`

## Tests
- `tests/test_macro6_risk_engine.py`: **8 passed**
- Combined OMS + Macro5 + Macro6 subset: **19 passed**

## Remaining
- No Macro 6 functional blockers in implemented scope.
- Full suite has two existing market-data test failures outside Macro 6.

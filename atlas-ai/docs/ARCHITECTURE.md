# Architecture

## Processes
* **api**: REST, WebSocket fan-out, auth, backtest jobs, static UI. It never places orders.
* **worker** (`python -m atlas.worker`, or embedded in the API in dev): the only process that trades.
* **PostgreSQL**: config, candles, signals, proposals (decisions), orders, fills, positions, snapshots, risk events,
  activity, backtests, audit. **Redis**: real-time event pub/sub.
* **MT5 bridge** (optional, Windows): wraps the MetaTrader5 API beside the terminal.

Operator actions (close, flatten, reset, calendar refresh) are queued in `commands` and executed by the worker within one fast tick.

## Module map (`backend/atlas`)
| Module | Responsibility |
|---|---|
| `instruments.py` | the 11 instruments, contract specs, pip values, notional, margin, lot rounding |
| `sessions.py` | DST-aware sessions, market hours (FX 24/5, gold daily break), rollover |
| `econ.py` | economic calendar parsing, central-bank detection, news blackout, US10Y (FRED), currency strength |
| `brokers/public.py` | Swissquote quotes (median spread profile) + 1-minute bar builder |
| `brokers/oanda.py` | OANDA v20 data + execution |
| `brokers/mt5.py` | MT5 bridge client |
| `marketdata/` | rate-limited HTTP, candle validation (market-hours-aware gaps/staleness), market data service |
| `indicators.py`, `analysis.py` | causal indicators; swings, structure/BOS, liquidity sweeps, supply/demand zones, session ranges |
| `strategies/` | five confluence strategies (≥ 3 evidence categories), two-sided |
| `decision.py` | AI analyst: factor scoring, classification, calibration |
| `risk.py` | gates, lot sizing, margin/leverage, currency exposure |
| `execution/` | costs, position rules, paper broker, broker executor + reconciliation |
| `portfolio.py` | USD accounting, mark-to-market, analytics |
| `backtest.py` | long/short backtester, OOS, walk-forward |
| `agent.py` | orchestration loops and narration |

## Decision pipeline (each closed entry-timeframe bar, per instrument)
1. Refresh candles (1m/5m/15m/1h/4h), validate them, and check readiness (market open, fresh quote, enough bars, reference agreement).
2. Compute currency strength; load calendar and US10Y context.
3. Each enabled strategy returns a Signal with evidence and invalidation, or a reason why not.
4. The AI analyst scores and classifies the signal; the best proposal is stored.
5. The risk engine checks every rule and sizes in lots, then the proposal is executed (paper or broker) or rejected with reasons.
6. The fast loop applies the position rules on every quote, with broker-held stops in demo/live.
